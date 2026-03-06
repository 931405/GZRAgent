"""
Red Team Reviewer Agent — adversarial review with structured scoring.

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


_REVIEW_PROMPT = """\
你是一名严格的匿名同行评审专家（红队角色），对论文进行系统性对抗审查。

【评审维度 — 每维度 1-10 分】
1. 论点连贯性 (25%): 论证链是否完整、是否有逻辑跳跃
2. 证据充分性 (25%): 主要主张是否有文献/数据支撑
3. 方法严谨性 (20%): 研究设计是否合理
4. 文献覆盖度 (15%): 是否覆盖重要相关工作
5. 写作规范性 (15%): 术语、格式、语言是否符合学术标准

【审查流程】
1. 通读全文，记录整体印象
2. 按章节逐一审查，标注问题位置
3. 每个问题标明严重程度：critical / major / minor
4. 按 5 个维度打分，计算加权总分
5. 加权总分 >= 7.0 为 PASS，否则 FAIL

【输出格式 — JSON】
{
  "overall_impression": "整体评价",
  "dimension_scores": {
    "coherence": 分数,
    "evidence": 分数,
    "methodology": 分数,
    "literature": 分数,
    "writing": 分数
  },
  "weighted_score": 加权总分,
  "passed": true或false,
  "issues": [
    {"severity": "critical", "location": "位置", "issue": "问题", "suggestion": "建议"}
  ],
  "revision_priorities": ["优先修改项1", "优先修改项2"]
}
只输出 JSON。"""


class RedTeamAgent(BaseAgent):
    """Red Team Reviewer — structured adversarial review with scoring rubric."""

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
        content = message.payload.data.get("content", "")
        response = await self.llm_complete([
            ChatMessage(role="system", content=_REVIEW_PROMPT),
            ChatMessage(
                role="user",
                content=f"请审查以下论文初稿：\n\n{content}\n\n请按评审维度输出结构化 JSON 评审结果：",
            ),
        ])
        return {"findings": response.content, "issues_found": True}

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        return {"review_thorough": bool(execution_result.get("findings"))}

    async def emit(self, execution_result: dict[str, Any], verification_result: dict[str, Any]) -> A2AMessage:
        now_ms = int(time.time() * 1000)
        session_ctx = self._get_session_context()
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=session_ctx,
            route=RouteInfo(source_agent=self.agent_id, target_agent="PI_Agent_01", intent=AgentIntent.REVIEW_FEEDBACK),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(prompt_tokens_used=self._total_prompt_tokens, completion_tokens_used=self._total_completion_tokens),
        )
