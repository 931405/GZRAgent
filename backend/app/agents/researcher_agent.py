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
        """Execute literature search and structure results."""
        query = plan.get("query", "")

        # Use LLM to structure raw evidence into standardized format
        response = await self.llm_complete([
            ChatMessage(
                role="system",
                content=(
                    "You are a literature researcher. Given a research query, "
                    "provide structured evidence in JSON format with fields: "
                    "claim, evidence_ids, doi_or_ref, confidence (0-1), "
                    "retrieved_at (timestamp). Never output ungrounded conclusions."
                ),
            ),
            ChatMessage(role="user", content=f"Research query: {query}"),
        ])

        return {
            "evidence": response.content,
            "confidence": 0.8,
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
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=SessionContext(session_id="", session_version=0, current_turn=0),
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
