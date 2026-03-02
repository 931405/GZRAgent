"""
Format Controller Agent — typography and citation formatting.

Ref: design.md Section 8.6
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


class FormatAgent(BaseAgent):
    """Format Controller — applies journal-specific formatting rules."""

    def __init__(self, agent_id: str = "Format_Controller_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.FORMAT_CONTROLLER,
            allowed_actions=["FORMAT_DOCUMENT", "CONVERT_CITATIONS", "APPLY_TEMPLATE"],
            forbidden_actions=["WRITE_DRAFT_CONTENT", "SEARCH_LITERATURE", "ARBITRATE_CONFLICT"],
            quality_gates=[
                QualityGate(name="format_valid", description="Document conforms to target format", gate_type="assertion"),
            ],
        )
        super().__init__(agent_id, constraints)

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        return {"target_format": message.payload.data.get("format", "IEEE"), "content": message.payload.data.get("content", "")}

    async def execute(self, message: A2AMessage, plan: dict[str, Any]) -> dict[str, Any]:
        response = await self.llm_complete([
            ChatMessage(
                role="system",
                content=f"Apply {plan['target_format']} formatting to the document. Convert citations to the journal's required style.",
            ),
            ChatMessage(role="user", content=plan["content"]),
        ])
        return {"formatted_content": response.content, "format": plan["target_format"]}

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        return {"format_valid": bool(execution_result.get("formatted_content"))}

    async def emit(self, execution_result: dict[str, Any], verification_result: dict[str, Any]) -> A2AMessage:
        now_ms = int(time.time() * 1000)
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=SessionContext(session_id="", session_version=0, current_turn=0),
            route=RouteInfo(source_agent=self.agent_id, target_agent="", intent=AgentIntent.FORMAT_COMPLETED),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(prompt_tokens_used=self._total_prompt_tokens, completion_tokens_used=self._total_completion_tokens),
        )
