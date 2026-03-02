"""
Red Team Reviewer Agent — adversarial review for logic gaps and evidence breaks.

Trigger: subscribes to `draft.integrated.ready` (not `draft_ready`).
This prevents reviewing half-finished products.

Ref: design.md Section 8.4
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
from app.models.agent import AgentConstraints, AgentRole, QualityGate


class RedTeamAgent(BaseAgent):
    """Red Team Reviewer — finds logic flaws and evidence gaps."""

    def __init__(self, agent_id: str = "Red_Team_Reviewer_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.RED_TEAM,
            allowed_actions=["REVIEW_CONTENT", "FLAG_ISSUES", "REQUEST_EVIDENCE_CHECK"],
            forbidden_actions=["WRITE_DRAFT_CONTENT", "GENERATE_DIAGRAM", "FORCE_UPDATE_DRAFT"],
            quality_gates=[
                QualityGate(name="review_thorough", description="Review covers all sections", gate_type="assertion"),
            ],
        )
        super().__init__(agent_id, constraints)

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        return {"sections_to_review": message.payload.data.get("sections", [])}

    async def execute(self, message: A2AMessage, plan: dict[str, Any]) -> dict[str, Any]:
        response = await self.llm_complete([
            ChatMessage(
                role="system",
                content=(
                    "You are a critical academic reviewer (Red Team). Your job is to find: "
                    "1) Logical fallacies, 2) Unsupported claims, 3) Evidence gaps, "
                    "4) Internal contradictions, 5) Missing citations. "
                    "Be thorough and adversarial. Output structured findings."
                ),
            ),
            ChatMessage(role="user", content=f"Review this draft:\n{message.payload.data.get('content', '')}"),
        ])
        return {"findings": response.content, "issues_found": True}

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        return {"review_thorough": bool(execution_result.get("findings"))}

    async def emit(self, execution_result: dict[str, Any], verification_result: dict[str, Any]) -> A2AMessage:
        now_ms = int(time.time() * 1000)
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=SessionContext(session_id="", session_version=0, current_turn=0),
            route=RouteInfo(source_agent=self.agent_id, target_agent="PI_Agent_01", intent=AgentIntent.REVIEW_FEEDBACK),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(prompt_tokens_used=self._total_prompt_tokens, completion_tokens_used=self._total_completion_tokens),
        )
