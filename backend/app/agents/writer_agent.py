"""
Academic Writer Agent — draft composition with evidence grounding.

Modifies the Document Blackboard via Patch operations (never full text).
Each write carries version_hash for optimistic locking.

Ref: design.md Section 8 (implicit), Section 4.4
"""
from __future__ import annotations

import time
from typing import Any

from app.core.acp.base_agent import BaseAgent
from app.core.l1.llm_provider import ChatMessage
from app.models.a2a import (
    A2AMessage, AgentIntent, MessageMeta, Payload,
    RouteInfo, SessionContext, Telemetry, DocumentPointer,
)
from app.models.agent import AgentConstraints, AgentRole, QualityGate


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
            ChatMessage(
                role="system",
                content=(
                    "You are an academic writer. Plan how to write the assigned "
                    "section. Identify what evidence and references are needed, "
                    "outline the argument structure, and list any diagrams required."
                ),
            ),
            ChatMessage(
                role="user",
                content=f"Assignment: {message.payload.data.get('assignment', '')}\n"
                        f"Context: {message.payload.data.get('context', '')}",
            ),
        ])
        return {"outline": response.content, "needs_evidence": True}

    async def execute(
        self, message: A2AMessage, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Write the section content using LLM."""
        response = await self.llm_complete([
            ChatMessage(
                role="system",
                content=(
                    "You are an academic writer. Write the section based on the "
                    "plan and available evidence. Include proper citations using "
                    "[ref_id] format. Output well-structured academic prose."
                ),
            ),
            ChatMessage(
                role="user",
                content=f"Plan:\n{plan.get('outline', '')}\n\n"
                        f"Evidence: {message.payload.data.get('evidence', 'none available')}",
            ),
        ])
        return {
            "content": response.content,
            "word_count": len(response.content.split()),
            "citations": self._extract_citations(response.content),
        }

    def _extract_citations(self, text: str) -> list[str]:
        """Extract citation references from text."""
        import re
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
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=SessionContext(session_id="", session_version=0, current_turn=0),
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
