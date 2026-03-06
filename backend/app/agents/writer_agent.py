"""
Academic Writer Agent — draft composition with evidence grounding.

Modifies the Document Blackboard via Patch operations (never full text).
Each write carries version_hash for optimistic locking.

Ref: design.md Section 8 (implicit), Section 4.4
"""
from __future__ import annotations

import re
import time
from typing import Any

from app.core.acp.base_agent import BaseAgent
from app.core.l1.llm_provider import ChatMessage
from app.models.a2a import (
    A2AMessage, AgentIntent, MessageMeta, Payload,
    RouteInfo, SessionContext, Telemetry, DocumentPointer,
)
from app.models.agent import AgentConstraints, AgentRole, QualityGate


_PLAN_PROMPT = """\
你是一名资深学术论文写手。请为指定章节制定写作计划。

【思考步骤】
1. 分析章节主题在全文中的定位
2. 确定需要哪些类型的证据和引用
3. 规划论证结构：背景 → 问题 → 论证 → 小结
4. 列出需要的图表或数据

请输出：论证大纲、所需证据清单、预估字数。用中文回复。"""

_EXECUTE_PROMPT = """\
你是一名资深学术论文写手，具备深厚的学术写作功底。

【写作规范】
- 每段开头给出段落主旨句
- 引用格式：使用 [作者, 年份] 格式
- 禁止使用"我认为""本文认为"等主观表述
- 专业术语首次出现时须简要说明
- 段落间有清晰的逻辑过渡

【写作后自检】
□ 每个核心主张都有引用支撑
□ 逻辑连贯、过渡自然
□ 无主观表述
如有问题请直接修正。

用中文撰写，输出严谨的学术文章。"""


class WriterAgent(BaseAgent):
    """Academic Writer — composes draft sections with evidence grounding."""

    def __init__(self, agent_id: str = "Academic_Writer_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.WRITER,
            allowed_actions=[
                "WRITE_DRAFT_CONTENT",
                "REQUEST_EVIDENCE",
                "REQUEST_DIAGRAM",
                "REQUEST_DATA_ANALYSIS",
                "SUBMIT_PATCH",
            ],
            forbidden_actions=[
                "ARBITRATE_CONFLICT",
                "FORCE_UPDATE_DRAFT",
                "HALT_SESSION",
            ],
            quality_gates=[
                QualityGate(
                    name="has_citations",
                    description="Output must include grounded citations",
                    gate_type="assertion",
                ),
                QualityGate(
                    name="word_count_met",
                    description="Section meets minimum word count",
                    gate_type="threshold",
                    threshold=100,
                ),
            ],
        )
        super().__init__(agent_id, constraints)

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        """Plan the writing strategy for the assigned section."""
        response = await self.llm_complete([
            ChatMessage(role="system", content=_PLAN_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"章节任务：{message.payload.data.get('assignment', '')}\n"
                    f"上下文：{message.payload.data.get('context', '')}\n\n"
                    "请制定写作计划："
                ),
            ),
        ])
        return {"outline": response.content, "needs_evidence": True}

    async def execute(
        self, message: A2AMessage, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Write the section content using LLM."""
        evidence = message.payload.data.get("evidence", "暂无可用文献")
        response = await self.llm_complete([
            ChatMessage(role="system", content=_EXECUTE_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"写作计划：\n{plan.get('outline', '')}\n\n"
                    f"可用文献：{evidence}\n\n"
                    "请撰写该章节内容："
                ),
            ),
        ])
        return {
            "content": response.content,
            "word_count": len(response.content),
            "citations": self._extract_citations(response.content),
        }

    def _extract_citations(self, text: str) -> list[str]:
        """Extract citation references from text."""
        return re.findall(r'\[([^\]]+)\]', text)

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Verify the written content meets quality gates."""
        return {
            "has_citations": len(execution_result.get("citations", [])) > 0,
            "word_count_met": execution_result.get("word_count", 0),
        }

    async def emit(
        self,
        execution_result: dict[str, Any],
        verification_result: dict[str, Any],
    ) -> A2AMessage:
        """Emit a PATCH request to the Blackboard."""
        now_ms = int(time.time() * 1000)
        session_ctx = self._get_session_context()
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=session_ctx,
            route=RouteInfo(
                source_agent=self.agent_id,
                target_agent="blackboard",
                intent=AgentIntent.REQUEST_DRAFT_PATCH,
            ),
            payload=Payload(
                context_grounding=execution_result.get("citations", []),
                data={"content": execution_result.get("content", "")},
            ),
            telemetry=Telemetry(
                prompt_tokens_used=self._total_prompt_tokens,
                completion_tokens_used=self._total_completion_tokens,
            ),
        )
