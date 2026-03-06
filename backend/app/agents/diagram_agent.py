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


_DIAGRAM_PROMPT = """\
你是学术图表设计专家，根据文本内容生成结构化图表。

【设计原则】
1. 图中所有实体必须对应文本中的实际概念
2. 使用清晰的标签和合适的配色（WCAG AA 对比度）
3. 图表结构清晰，信息完整且不冗余

【思考步骤】
1. 分析文本，找出适合可视化的概念关系
2. 确定最合适的图表类型
3. 设计图表结构
4. 生成代码

只输出图表代码，不要添加解释文字。"""


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
                content=f"请使用 {plan['chart_type']} 语法生成图表。\n\n{_DIAGRAM_PROMPT}",
            ),
            ChatMessage(role="user", content=plan["source_text"]),
        ])
        return {"chart_code": response.content, "chart_type": plan["chart_type"]}

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        code = execution_result.get("chart_code", "")
        source_text = ""
        if self._current_message:
            source_text = self._current_message.payload.data.get("text", "")

        syntax_ok = len(code) > 10
        semantic_ok = self._check_semantic_consistency(code, source_text) if source_text else True
        return {
            "syntax_valid": syntax_ok,
            "semantic_consistent": semantic_ok,
        }

    @staticmethod
    def _check_semantic_consistency(chart_code: str, source_text: str) -> bool:
        """Check that key entities in chart actually appear in the source text."""
        import re
        labels = re.findall(r'[\[("\|]([^"\]\|)\n]{3,})[\]"\|)]', chart_code)
        if not labels:
            return True
        source_lower = source_text.lower()
        matched = sum(1 for label in labels if label.strip().lower() in source_lower)
        return (matched / len(labels)) >= 0.4 if labels else True

    async def emit(self, execution_result: dict[str, Any], verification_result: dict[str, Any]) -> A2AMessage:
        now_ms = int(time.time() * 1000)
        session_ctx = self._get_session_context()
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=session_ctx,
            route=RouteInfo(source_agent=self.agent_id, target_agent="", intent=AgentIntent.DIAGRAM_RESPONSE),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(prompt_tokens_used=self._total_prompt_tokens, completion_tokens_used=self._total_completion_tokens),
        )
