"""
Human Proxy Agent — elevates human actions to first-class system citizens.

Capabilities:
  - INTERRUPT: redirect agent/session flow at any time
  - FORCE_UPDATE_DRAFT: highest-privilege direct Blackboard write
  - After force-write, triggers sub-session re-verify

Ref: design.md Section 8.5
"""
from __future__ import annotations

import time
from typing import Any

from app.core.acp.base_agent import BaseAgent
from app.core.l1.llm_provider import ChatMessage
from app.models.a2a import (
    A2AMessage, AgentIntent, MessageMeta, Payload,
    RouteInfo, SessionContext, Telemetry,
)
from app.models.agent import AgentConstraints, AgentRole


class HumanProxyAgent(BaseAgent):
    """Human Proxy — bridges human input into the agent protocol."""

    def __init__(self, agent_id: str = "Human_Proxy_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.HUMAN_PROXY,
            allowed_actions=[
                "FORCE_UPDATE_DRAFT",
                "INTERRUPT",
                "APPROVE_ARBITRATION",
                "REJECT_ARBITRATION",
                "RESUME_SESSION",
                "HALT_SESSION",
                "COMPRESS_CONTEXT",
            ],
            forbidden_actions=[],  # Human has highest privilege
            quality_gates=[],  # Human output is not auto-gated
        )
        super().__init__(agent_id, constraints)

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        """Human input doesn't need LLM planning — pass through."""
        return {"action": message.route.intent.value, "data": message.payload.data}

    async def execute(self, message: A2AMessage, plan: dict[str, Any]) -> dict[str, Any]:
        """Execute human action."""
        return {"action": plan["action"], "result": plan["data"], "executed_by": "human"}

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Human actions are auto-verified."""
        return {}

    async def emit(self, execution_result: dict[str, Any], verification_result: dict[str, Any]) -> A2AMessage:
        now_ms = int(time.time() * 1000)
        intent = AgentIntent.FORCE_UPDATE_DRAFT
        action = execution_result.get("action", "")
        if action == "INTERRUPT":
            intent = AgentIntent.INTERRUPT
        elif action == "HALT":
            intent = AgentIntent.HALT

        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=SessionContext(session_id="", session_version=0, current_turn=0),
            route=RouteInfo(source_agent=self.agent_id, target_agent="PI_Agent_01", intent=intent),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(),
        )
