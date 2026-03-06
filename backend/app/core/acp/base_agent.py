"""
ACP Base Agent — the foundation for all agents in the system.

Architecture: Constraint Declaration + State Machine + L1 Skills (三位一体)

Each agent inherits from BaseAgent and:
  1. Declares constraints (Role, AllowedActions, ForbiddenActions, QualityGates)
  2. Runs through the unified ACP state machine lifecycle
  3. Uses L1 Skills (LLM Provider, Retriever, etc.) during EXECUTE phase

Ref: design.md Sections 7.1, 7.2
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.config import LLMProviderType, get_settings
from app.core.acp.state_machine import AgentState, AgentStateMachine
from app.core.l1.llm_provider import (
    BaseLLMProvider,
    ChatMessage,
    LLMProviderFactory,
    LLMResponse,
)
from app.models.a2a import A2AMessage, AgentIntent
from app.models.agent import AgentConstraints, AgentRole, QualityGate

logger = logging.getLogger(__name__)


class ConstraintViolationError(Exception):
    """Raised when an agent attempts a forbidden action."""


class QualityGateFailure(Exception):
    """Raised when a quality gate fails during VERIFY."""


class BaseAgent(ABC):
    """Abstract base class for all PD-MAWS agents.

    Lifecycle:
        1. __init__: Configure constraints and bind LLM Provider
        2. receive_task(): Entry point — receives A2A message
        3. plan(): PLAN phase — analyze task, build strategy
        4. execute(): EXECUTE phase — perform work using Skills
        5. verify(): VERIFY phase — check quality gates
        6. emit(): EMIT phase — produce output message
        7. wait()/done(): Terminal phases

    Subclasses MUST implement: plan(), execute(), verify(), emit()
    Subclasses MUST call super().__init__() and set self.constraints
    """

    def __init__(
        self,
        agent_id: str,
        constraints: AgentConstraints,
    ) -> None:
        self.agent_id = agent_id
        self.constraints = constraints

        # State machine
        self._state_machine = AgentStateMachine(
            agent_id=agent_id,
            max_consecutive_errors=constraints.max_consecutive_errors,
        )

        # LLM Provider (lazy init)
        self._llm_provider: Optional[BaseLLMProvider] = None

        # Current message context (set in receive_task for emit() access)
        self._current_message: Optional[A2AMessage] = None

        # Telemetry
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._task_start_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> AgentState:
        return self._state_machine.state

    @property
    def role(self) -> AgentRole:
        return self.constraints.role

    @property
    def should_escalate(self) -> bool:
        return self._state_machine.should_escalate

    # ------------------------------------------------------------------
    # LLM Provider
    # ------------------------------------------------------------------

    def get_llm_provider(self) -> BaseLLMProvider:
        """Get or create the LLM provider for this agent."""
        if self._llm_provider is None:
            settings = get_settings()
            provider_type = self.constraints.llm_provider
            config = settings.get_provider_config(LLMProviderType(provider_type))
            self._llm_provider = LLMProviderFactory.create(
                provider_type,
                api_key=config.api_key,
                base_url=config.base_url,
                default_model=self.constraints.llm_model or config.default_model,
                timeout=config.timeout,
                max_retries=config.max_retries,
            )
        return self._llm_provider

    async def llm_complete(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> LLMResponse:
        """Call LLM and track token usage."""
        provider = self.get_llm_provider()
        response = await provider.complete(messages, **kwargs)

        self._total_prompt_tokens += response.prompt_tokens
        self._total_completion_tokens += response.completion_tokens

        return response

    # ------------------------------------------------------------------
    # Constraint enforcement
    # ------------------------------------------------------------------

    def check_action_allowed(self, action: str) -> bool:
        """Check if an action is allowed by constraints."""
        if action in self.constraints.forbidden_actions:
            raise ConstraintViolationError(
                f"Agent {self.agent_id} (role={self.role.value}): "
                f"Forbidden action attempted: {action}"
            )
        if self.constraints.allowed_actions:
            return action in self.constraints.allowed_actions
        return True  # No allowlist = everything not forbidden is allowed

    def check_quality_gates(self, results: dict[str, Any]) -> list[str]:
        """Run all quality gates against results.

        Returns: List of failed gate names (empty = all passed).
        """
        failures = []
        for gate in self.constraints.quality_gates:
            passed = self._evaluate_gate(gate, results)
            if not passed:
                if gate.required:
                    failures.append(gate.name)
                else:
                    logger.warning(
                        "Agent %s: optional gate '%s' failed",
                        self.agent_id, gate.name,
                    )
        return failures

    def _evaluate_gate(
        self, gate: QualityGate, results: dict[str, Any]
    ) -> bool:
        """Evaluate a single quality gate."""
        if gate.gate_type == "threshold":
            value = results.get(gate.name, 0)
            return float(value) >= (gate.threshold or 0)
        elif gate.gate_type == "assertion":
            return bool(results.get(gate.name, False))
        elif gate.gate_type == "schema_check":
            return gate.name in results and results[gate.name] is not None
        logger.warning(
            "Agent %s: unknown gate_type '%s' for gate '%s' — treating as FAIL",
            self.agent_id, gate.gate_type, gate.name,
        )
        return False

    # ------------------------------------------------------------------
    # Lifecycle (state machine driven)
    # ------------------------------------------------------------------

    async def receive_task(
        self,
        message: A2AMessage,
    ) -> Optional[A2AMessage]:
        """Main entry point: receive an A2A message and process it.

        Drives through the full state machine lifecycle:
        IDLE -> PLAN -> EXECUTE -> VERIFY -> EMIT -> DONE

        Returns: Output A2A message, or None if interrupted/error.
        """
        self._task_start_time = time.time()
        self._current_message = message
        context = {"input_message": message}

        try:
            # IDLE -> PLAN
            self._state_machine.transition(AgentState.PLAN)
            plan_result = await self.plan(message)
            context["plan"] = plan_result

            # PLAN -> EXECUTE
            self._state_machine.transition(AgentState.EXECUTE)
            exec_result = await self.execute(message, plan_result)
            context["execution"] = exec_result

            # EXECUTE -> VERIFY
            self._state_machine.transition(AgentState.VERIFY)
            verify_result = await self.verify(exec_result)
            context["verification"] = verify_result

            # Check quality gates
            failures = self.check_quality_gates(verify_result)
            if failures:
                logger.warning(
                    "Agent %s: quality gates failed: %s",
                    self.agent_id, failures,
                )
                # VERIFY -> PLAN (re-plan)
                self._state_machine.transition(AgentState.PLAN)
                # For simplicity, error out after one retry
                self._state_machine.transition(AgentState.ERROR)
                raise QualityGateFailure(
                    f"Quality gates failed: {failures}"
                )

            # VERIFY -> EMIT
            self._state_machine.transition(AgentState.EMIT)
            output = await self.emit(exec_result, verify_result)

            # EMIT -> DONE
            self._state_machine.transition(AgentState.DONE)

            logger.info(
                "Agent %s completed task in %.2fs (tokens: %d prompt, %d completion)",
                self.agent_id,
                time.time() - self._task_start_time,
                self._total_prompt_tokens,
                self._total_completion_tokens,
            )
            return output

        except Exception as e:
            try:
                self._state_machine.transition(AgentState.ERROR)
            except Exception as transition_err:
                logger.debug(
                    "Agent %s: state transition to ERROR failed (already terminal): %s",
                    self.agent_id, transition_err,
                )
            logger.error(
                "Agent %s error in state %s: %s",
                self.agent_id, self.state.value, e,
            )
            return None

    def halt(self) -> None:
        """Receive HALT signal. Immediately interrupt."""
        self._state_machine.halt()
        logger.warning("Agent %s received HALT — interrupted", self.agent_id)

    # ------------------------------------------------------------------
    # Abstract methods — subclasses MUST implement
    # ------------------------------------------------------------------

    @abstractmethod
    async def plan(
        self, message: A2AMessage
    ) -> dict[str, Any]:
        """PLAN phase: analyze the task and build a strategy.

        Args:
            message: The incoming A2A task message.

        Returns:
            Plan data (strategy, sub-steps, etc.)
        """
        ...

    @abstractmethod
    async def execute(
        self, message: A2AMessage, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """EXECUTE phase: perform the actual work using L1 Skills.

        Args:
            message: The incoming A2A task message.
            plan: The plan from the PLAN phase.

        Returns:
            Execution results.
        """
        ...

    @abstractmethod
    async def verify(
        self, execution_result: dict[str, Any]
    ) -> dict[str, Any]:
        """VERIFY phase: check quality gates and validate output.

        Args:
            execution_result: Results from EXECUTE phase.

        Returns:
            Verification results (gate name -> pass/fail).
        """
        ...

    @abstractmethod
    async def emit(
        self,
        execution_result: dict[str, Any],
        verification_result: dict[str, Any],
    ) -> A2AMessage:
        """EMIT phase: produce the output A2A message.

        Args:
            execution_result: Results from EXECUTE phase.
            verification_result: Results from VERIFY phase.

        Returns:
            Output A2A message to send downstream.
        """
        ...

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _get_session_context(self) -> "SessionContext":
        """Get session context from the current message for use in emit()."""
        from app.models.a2a import SessionContext
        if self._current_message:
            return self._current_message.session
        return SessionContext(session_id="", session_version=0, current_turn=0)

    def get_telemetry(self) -> dict[str, Any]:
        """Get current telemetry data."""
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "state": self.state.value,
            "total_prompt_tokens": self._total_prompt_tokens,
            "total_completion_tokens": self._total_completion_tokens,
            "elapsed_ms": int((time.time() - self._task_start_time) * 1000)
            if self._task_start_time else 0,
        }
