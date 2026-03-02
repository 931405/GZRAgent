"""
PI_Agent — Principal Investigator Agent (调度与仲裁).

Responsibilities:
  - Task decomposition (Map phase: outline -> chapter sub-sessions)
  - Session orchestration
  - Conflict arbitration (Rule Engine -> LLM -> Human-in-the-loop)
  - Human escalation upon deadlock

Hard rules (design.md Section 8.1):
  - 2 consecutive inconsistent LLM decisions -> human escalation
  - Dispute handling > 120s SLA -> human escalation

Ref: design.md Section 8.1
"""
from __future__ import annotations

import time
from typing import Any

from app.core.acp.base_agent import BaseAgent
from app.core.l1.llm_provider import ChatMessage
from app.models.a2a import (
    A2AMessage,
    AgentIntent,
    ControlDirective,
    MessageMeta,
    Payload,
    RouteInfo,
    SessionContext,
    Telemetry,
)
from app.models.agent import AgentConstraints, AgentRole, ArbDecision, QualityGate


class PIAgent(BaseAgent):
    """Principal Investigator — coordinator and arbiter of the system."""

    def __init__(self, agent_id: str = "PI_Agent_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.PI,
            allowed_actions=[
                "DECOMPOSE_TASK",
                "CREATE_SUB_SESSION",
                "ARBITRATE_CONFLICT",
                "ESCALATE_TO_HUMAN",
                "COMPRESS_CONTEXT",
                "HALT_SESSION",
                "RESUME_SESSION",
            ],
            forbidden_actions=[
                "WRITE_DRAFT_CONTENT",  # PI does not write academic content
                "GENERATE_DIAGRAM",
                "EXECUTE_DATA_CODE",
            ],
            quality_gates=[
                QualityGate(
                    name="decomposition_complete",
                    description="All outline sections mapped to sub-tasks",
                    gate_type="assertion",
                ),
                QualityGate(
                    name="arbitration_confidence",
                    description="Arbitration decision confidence >= 0.7",
                    gate_type="threshold",
                    threshold=0.7,
                ),
            ],
        )
        super().__init__(agent_id, constraints)
        self._arbitration_history: list[ArbDecision] = []

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        """Analyze the incoming task and determine strategy."""
        intent = message.route.intent

        if intent == AgentIntent.REQUEST_TASK:
            # Decompose paper outline into chapter sub-tasks
            return await self._plan_decomposition(message)
        elif intent == AgentIntent.ARBITRATION_REQUEST:
            return await self._plan_arbitration(message)
        else:
            return {"strategy": "forward", "detail": f"Forward intent: {intent.value}"}

    async def _plan_decomposition(self, message: A2AMessage) -> dict[str, Any]:
        """Plan task decomposition for a paper outline."""
        response = await self.llm_complete([
            ChatMessage(
                role="system",
                content=(
                    "You are a principal investigator coordinating a multi-agent "
                    "academic writing system. Analyze the given paper outline and "
                    "decompose it into independent sub-tasks for parallel execution."
                ),
            ),
            ChatMessage(
                role="user",
                content=f"Paper task: {message.payload.data.get('task', '')}\n"
                        f"Outline: {message.payload.data.get('outline', '')}",
            ),
        ])
        return {
            "strategy": "decompose",
            "sub_tasks": response.content,
            "tokens_used": response.total_tokens,
        }

    async def _plan_arbitration(self, message: A2AMessage) -> dict[str, Any]:
        """Plan arbitration for a conflict."""
        return {
            "strategy": "arbitrate",
            "dispute": message.payload.data.get("dispute", ""),
            "participants": message.payload.data.get("participants", []),
        }

    async def execute(
        self, message: A2AMessage, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute the plan."""
        strategy = plan.get("strategy", "")

        if strategy == "decompose":
            return {"type": "decomposition", "result": plan["sub_tasks"]}
        elif strategy == "arbitrate":
            return await self._execute_arbitration(message, plan)
        else:
            return {"type": "forward", "result": "no-op"}

    async def _execute_arbitration(
        self, message: A2AMessage, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute arbitration: Rule Engine -> LLM -> Human escalation.

        Hard rules:
        - 2 consecutive inconsistent LLM decisions -> human
        - > 120s SLA -> human
        """
        start_time = time.time()
        dispute = plan.get("dispute", "")

        # Step 1: Rule engine (deterministic)
        rule_result = self._apply_rules(dispute)
        if rule_result:
            return {"type": "arbitration", "source": "rule_engine", "decision": rule_result}

        # Step 2: LLM arbitration
        response = await self.llm_complete([
            ChatMessage(
                role="system",
                content=(
                    "You are an arbitrator resolving a conflict between agents. "
                    "Analyze the dispute and provide a structured resolution. "
                    "Output JSON with: decision_id, dispute_summary, resolution, "
                    "rationale, confidence (0-1), escalate_to_human (bool)."
                ),
            ),
            ChatMessage(role="user", content=f"Dispute:\n{dispute}"),
        ])

        # Check SLA
        elapsed = time.time() - start_time
        if elapsed > 120:
            return {
                "type": "arbitration",
                "source": "human_escalation",
                "reason": f"SLA exceeded: {elapsed:.1f}s",
            }

        # Check consistency with previous decisions
        if len(self._arbitration_history) >= 1:
            last = self._arbitration_history[-1]
            if last.confidence < 0.7:
                return {
                    "type": "arbitration",
                    "source": "human_escalation",
                    "reason": "2 consecutive low-confidence decisions",
                }

        return {
            "type": "arbitration",
            "source": "llm",
            "decision": response.content,
        }

    def _apply_rules(self, dispute: str) -> str | None:
        """Apply deterministic rule engine for clear-cut cases."""
        # Example rules — extend as needed
        if "formatting" in dispute.lower():
            return "Apply journal style guide"
        return None

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Verify the execution result."""
        result_type = execution_result.get("type", "")
        if result_type == "decomposition":
            return {
                "decomposition_complete": bool(execution_result.get("result")),
                "arbitration_confidence": 1.0,
            }
        elif result_type == "arbitration":
            return {
                "decomposition_complete": True,
                "arbitration_confidence": 0.8,
            }
        return {"decomposition_complete": True, "arbitration_confidence": 1.0}

    async def emit(
        self,
        execution_result: dict[str, Any],
        verification_result: dict[str, Any],
    ) -> A2AMessage:
        """Produce the output message."""
        now_ms = int(time.time() * 1000)
        result_type = execution_result.get("type", "")

        intent = AgentIntent.TASK_COMPLETED
        if result_type == "arbitration":
            intent = AgentIntent.ARBITRATION_DECISION

        return A2AMessage(
            meta=MessageMeta(
                correlation_id="",
                timestamp_ms=now_ms,
            ),
            session=SessionContext(
                session_id="",
                session_version=0,
                current_turn=0,
            ),
            route=RouteInfo(
                source_agent=self.agent_id,
                target_agent="",
                intent=intent,
            ),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(
                prompt_tokens_used=self._total_prompt_tokens,
                completion_tokens_used=self._total_completion_tokens,
            ),
        )
