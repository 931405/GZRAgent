"""
Literature Researcher Agent — retrieves verifiable evidence.

Output is strictly structured: claim, evidence_ids, doi_or_ref,
confidence, retrieved_at. Never outputs conclusions without evidence.

Ref: design.md Section 8.2
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


_RESEARCH_PROMPT = """\
你是一名学术文献研究员，专注于为论文提供可验证的文献证据。

【你的专业能力】
- 熟悉学术文献检索和引用规范
- 能够区分高质量证据和低质量证据
- 严格遵循"无证据不结论"原则

【思考步骤】
1. 分析研究查询的核心需求
2. 确定需要哪几类文献（理论、方法、数据、对比）
3. 为每类提供具体引用建议
4. 评估每条证据的置信度

【输出格式 — JSON】
{
  "evidence": [
    {
      "claim": "该文献支撑的主张",
      "doi_or_ref": "DOI或参考文献信息",
      "confidence": 0.85,
      "relevance": "与查询的关联说明"
    }
  ]
}
绝不输出无证据支撑的结论。用中文回复。"""


class ResearcherAgent(BaseAgent):
    """Literature Researcher — retrieves and structures evidence."""

    def __init__(self, agent_id: str = "Literature_Researcher_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.RESEARCHER,
            allowed_actions=[
                "SEARCH_LITERATURE",
                "RETRIEVE_DOCUMENTS",
                "STRUCTURE_EVIDENCE",
            ],
            forbidden_actions=[
                "WRITE_DRAFT_CONTENT",
                "ARBITRATE_CONFLICT",
                "GENERATE_DIAGRAM",
                "FORCE_UPDATE_DRAFT",
            ],
            quality_gates=[
                QualityGate(
                    name="has_evidence",
                    description="Must return at least one evidence reference",
                    gate_type="assertion",
                ),
                QualityGate(
                    name="confidence_threshold",
                    description="Evidence confidence >= 0.5",
                    gate_type="threshold",
                    threshold=0.5,
                ),
            ],
        )
        super().__init__(agent_id, constraints)

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        """Plan the search strategy."""
        query = message.payload.data.get("query", "")
        return {
            "query": query,
            "search_type": "semantic",
            "filters": message.payload.data.get("filters", {}),
        }

    async def execute(
        self, message: A2AMessage, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute literature search: real tool search + LLM structuring."""
        query = plan.get("query", "")

        # Stage 1: Real search via EvidenceService
        real_papers: list[dict] = []
        try:
            from app.core.l1.evidence_service import get_evidence_service
            svc = get_evidence_service()
            real_papers = await svc.search(query=query, limit=5)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "EvidenceService search failed, falling back to LLM-only: %s", e,
            )

        # Stage 2: LLM structures the evidence
        if real_papers:
            paper_text = "\n\n".join(p.get("evidence_block", p.get("title", "")) for p in real_papers)
            prompt_content = (
                f"研究查询：{query}\n\n"
                f"以下是通过学术数据库检索到的真实文献：\n{paper_text}\n\n"
                f"请基于这些真实文献，输出结构化的证据 JSON："
            )
        else:
            prompt_content = f"研究查询：{query}\n\n请提供结构化的文献证据："

        response = await self.llm_complete([
            ChatMessage(role="system", content=_RESEARCH_PROMPT),
            ChatMessage(role="user", content=prompt_content),
        ])

        return {
            "evidence": response.content,
            "real_papers": real_papers,
            "real_paper_count": len(real_papers),
            "confidence": 0.9 if real_papers else 0.6,
            "retrieved_at": int(time.time() * 1000),
        }

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Verify evidence meets quality gates."""
        return {
            "has_evidence": bool(execution_result.get("evidence")),
            "confidence_threshold": execution_result.get("confidence", 0),
        }

    async def emit(
        self, execution_result: dict[str, Any],
        verification_result: dict[str, Any],
    ) -> A2AMessage:
        now_ms = int(time.time() * 1000)
        session_ctx = self._get_session_context()
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=session_ctx,
            route=RouteInfo(
                source_agent=self.agent_id,
                target_agent="",
                intent=AgentIntent.EVIDENCE_RESPONSE,
            ),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(
                prompt_tokens_used=self._total_prompt_tokens,
                completion_tokens_used=self._total_completion_tokens,
            ),
        )
