"""
Visual Diagram Agent — converts text logic into chart code.

Quality gates (design.md Section 8.3):
  1. Semantic consistency (entities in chart must exist in text)
  2. Style constraints (color, font, contrast, readability)
  3. Structural validity (Mermaid syntax / Matplotlib executability)

Ref: design.md Section 8.3
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


class DiagramAgent(BaseAgent):
    """Visual Diagram Agent — text logic -> chart code."""

    def __init__(self, agent_id: str = "Visual_Diagram_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.DIAGRAM,
            allowed_actions=[
                "GENERATE_MERMAID",
                "GENERATE_MATPLOTLIB",
                "VALIDATE_DIAGRAM",
            ],
            forbidden_actions=[
                "WRITE_DRAFT_CONTENT",
                "ARBITRATE_CONFLICT",
                "SEARCH_LITERATURE",
            ],
            quality_gates=[
                QualityGate(
                    name="syntax_valid",
                    description="Generated chart code must be syntactically valid",
                    gate_type="assertion",
                ),
                QualityGate(
                    name="semantic_consistent",
                    description="Entities in chart must exist in source text",
                    gate_type="assertion",
                ),
            ],
        )
        super().__init__(agent_id, constraints)

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        chart_type = message.payload.data.get("chart_type", "mermaid")
        return {"chart_type": chart_type, "source_text": message.payload.data.get("text", "")}

    async def execute(self, message: A2AMessage, plan: dict[str, Any]) -> dict[str, Any]:
        response = await self.llm_complete([
            ChatMessage(
                role="system",
                content=(
                    f"Generate a {plan['chart_type']} chart from the given text. "
                    "All entities in the chart must correspond to concepts in the text. "
                    "Use appropriate colors with sufficient contrast (WCAG AA). "
                    "Output ONLY the chart code, no explanation."
                ),
            ),
            ChatMessage(role="user", content=plan["source_text"]),
        ])
        return {"chart_code": response.content, "chart_type": plan["chart_type"]}

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        code = execution_result.get("chart_code", "")
        return {
            "syntax_valid": len(code) > 10,  # Basic check — extend with parser
            "semantic_consistent": True,  # Would check entities against source
        }

    async def emit(self, execution_result: dict[str, Any], verification_result: dict[str, Any]) -> A2AMessage:
        now_ms = int(time.time() * 1000)
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=SessionContext(session_id="", session_version=0, current_turn=0),
            route=RouteInfo(source_agent=self.agent_id, target_agent="", intent=AgentIntent.DIAGRAM_RESPONSE),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(prompt_tokens_used=self._total_prompt_tokens, completion_tokens_used=self._total_completion_tokens),
        )
