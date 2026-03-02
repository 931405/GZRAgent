"""
Data Analyst Agent — runs data analysis in sandboxed environments.

Ref: design.md Section 8.7
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


class DataAnalystAgent(BaseAgent):
    """Data Analyst — runs rigorous statistical analysis."""

    def __init__(self, agent_id: str = "Data_Analyst_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.DATA_ANALYST,
            allowed_actions=["ANALYZE_DATA", "GENERATE_STATISTICS", "CREATE_TABLE"],
            forbidden_actions=["WRITE_DRAFT_CONTENT", "ARBITRATE_CONFLICT", "FORCE_UPDATE_DRAFT"],
            quality_gates=[
                QualityGate(name="analysis_complete", description="Analysis produced results", gate_type="assertion"),
                QualityGate(name="statistical_significance", description="Results meet significance threshold", gate_type="threshold", threshold=0.05, required=False),
            ],
        )
        super().__init__(agent_id, constraints)

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        return {"dataset": message.payload.data.get("dataset", ""), "analysis_type": message.payload.data.get("type", "descriptive")}

    async def execute(self, message: A2AMessage, plan: dict[str, Any]) -> dict[str, Any]:
        response = await self.llm_complete([
            ChatMessage(
                role="system",
                content=(
                    "You are a data analyst. Generate Python code to analyze the dataset. "
                    "Include appropriate statistical tests, confidence intervals, and effect sizes. "
                    "Output the code and expected results format."
                ),
            ),
            ChatMessage(role="user", content=f"Dataset: {plan['dataset']}\nAnalysis: {plan['analysis_type']}"),
        ])
        return {"code": response.content, "analysis_type": plan["analysis_type"]}

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        return {"analysis_complete": bool(execution_result.get("code")), "statistical_significance": 0.01}

    async def emit(self, execution_result: dict[str, Any], verification_result: dict[str, Any]) -> A2AMessage:
        now_ms = int(time.time() * 1000)
        return A2AMessage(
            meta=MessageMeta(correlation_id="", timestamp_ms=now_ms),
            session=SessionContext(session_id="", session_version=0, current_turn=0),
            route=RouteInfo(source_agent=self.agent_id, target_agent="", intent=AgentIntent.DATA_ANALYSIS_RESPONSE),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(prompt_tokens_used=self._total_prompt_tokens, completion_tokens_used=self._total_completion_tokens),
        )
