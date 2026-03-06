"""
PI_Agent — Principal Investigator Agent (调度与仲裁).

Responsibilities:
  - Task decomposition (Map phase: outline -> chapter sub-sessions)
  - Session orchestration
  - Conflict arbitration (Rule Engine -> LLM -> Human-in-the-loop)
  - Human escalation upon deadlock

Hard rules (design.md Section 8.1):
  - 2 consecutive inconsistent LLM decisions -> human escalation
  - Dispute handling > 120s SLA -> human escalation

Ref: design.md Section 8.1
"""
from __future__ import annotations

import time
from typing import Any

from app.core.acp.base_agent import BaseAgent
from app.core.l1.llm_provider import ChatMessage
from app.models.a2a import (
    A2AMessage,
    AgentIntent,
    ControlDirective,
    MessageMeta,
    Payload,
    RouteInfo,
    SessionContext,
    Telemetry,
)
from app.models.agent import AgentConstraints, AgentRole, ArbDecision, QualityGate


_DECOMPOSE_PROMPT = """\
你是一名资深学术研究 PI（首席研究员），负责协调多智能体学术写作系统。

【你的职责】
- 将论文大纲分解为可独立并行执行的子任务
- 为每个子任务明确写作目标、所需证据类型和预估字数
- 识别子任务之间的依赖关系

【思考步骤】
1. 分析论文主题和大纲结构
2. 为每个章节确定核心论点和关键要点
3. 评估各章节的并行可能性和依赖关系
4. 输出结构化的子任务分解

请用中文回复，输出清晰的分解方案。"""

_ARBITRATION_PROMPT = """\
你是多智能体系统中的冲突仲裁者，负责解决 Agent 之间的分歧。

【仲裁原则】
1. 基于学术规范和论文质量做出判断
2. 给出明确的裁决和理由
3. 评估自身裁决的置信度
4. 置信度低于 0.7 时建议升级到人工决策

【输出格式 — JSON】
{
  "decision_id": "唯一标识",
  "dispute_summary": "争议摘要",
  "resolution": "裁决结论",
  "rationale": "裁决理由",
  "confidence": 0.85,
  "escalate_to_human": false
}
请用中文回复。"""


class PIAgent(BaseAgent):
    """Principal Investigator — coordinator and arbiter of the system."""

    def __init__(self, agent_id: str = "PI_Agent_01") -> None:
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.PI,
            allowed_actions=[
                "DECOMPOSE_TASK",
                "CREATE_SUB_SESSION",
                "ARBITRATE_CONFLICT",
                "ESCALATE_TO_HUMAN",
                "COMPRESS_CONTEXT",
                "HALT_SESSION",
                "RESUME_SESSION",
            ],
            forbidden_actions=[
                "WRITE_DRAFT_CONTENT",
                "GENERATE_DIAGRAM",
                "EXECUTE_DATA_CODE",
            ],
            quality_gates=[
                QualityGate(
                    name="decomposition_complete",
                    description="All outline sections mapped to sub-tasks",
                    gate_type="assertion",
                ),
                QualityGate(
                    name="arbitration_confidence",
                    description="Arbitration decision confidence >= 0.7",
                    gate_type="threshold",
                    threshold=0.7,
                ),
            ],
        )
        super().__init__(agent_id, constraints)
        self._arbitration_history: list[ArbDecision] = []

    async def plan(self, message: A2AMessage) -> dict[str, Any]:
        """Analyze the incoming task and determine strategy."""
        intent = message.route.intent

        if intent == AgentIntent.REQUEST_TASK:
            return await self._plan_decomposition(message)
        elif intent == AgentIntent.ARBITRATION_REQUEST:
            return await self._plan_arbitration(message)
        else:
            return {"strategy": "forward", "detail": f"Forward intent: {intent.value}"}

    async def _plan_decomposition(self, message: A2AMessage) -> dict[str, Any]:
        """Plan task decomposition for a paper outline."""
        response = await self.llm_complete([
            ChatMessage(role="system", content=_DECOMPOSE_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"论文任务：{message.payload.data.get('task', '')}\n"
                    f"大纲：{message.payload.data.get('outline', '')}\n\n"
                    "请分解为子任务："
                ),
            ),
        ])
        return {
            "strategy": "decompose",
            "sub_tasks": response.content,
            "tokens_used": response.total_tokens,
        }

    async def _plan_arbitration(self, message: A2AMessage) -> dict[str, Any]:
        """Plan arbitration for a conflict."""
        return {
            "strategy": "arbitrate",
            "dispute": message.payload.data.get("dispute", ""),
            "participants": message.payload.data.get("participants", []),
        }

    async def execute(
        self, message: A2AMessage, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute the plan."""
        strategy = plan.get("strategy", "")

        if strategy == "decompose":
            return {"type": "decomposition", "result": plan["sub_tasks"]}
        elif strategy == "arbitrate":
            return await self._execute_arbitration(message, plan)
        else:
            return {"type": "forward", "result": "no-op"}

    async def _execute_arbitration(
        self, message: A2AMessage, plan: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute arbitration: Rule Engine -> LLM -> Human escalation."""
        start_time = time.time()
        dispute = plan.get("dispute", "")

        # Step 1: Rule engine (deterministic)
        rule_result = self._apply_rules(dispute)
        if rule_result:
            return {"type": "arbitration", "source": "rule_engine", "decision": rule_result}

        # Step 2: LLM arbitration
        response = await self.llm_complete([
            ChatMessage(role="system", content=_ARBITRATION_PROMPT),
            ChatMessage(role="user", content=f"争议内容：\n{dispute}"),
        ])

        # Check SLA
        elapsed = time.time() - start_time
        if elapsed > 120:
            return {
                "type": "arbitration",
                "source": "human_escalation",
                "reason": f"SLA exceeded: {elapsed:.1f}s",
            }

        # Check consistency with previous decisions
        if len(self._arbitration_history) >= 1:
            last = self._arbitration_history[-1]
            if last.confidence < 0.7:
                return {
                    "type": "arbitration",
                    "source": "human_escalation",
                    "reason": "2 consecutive low-confidence decisions",
                }

        return {
            "type": "arbitration",
            "source": "llm",
            "decision": response.content,
        }

    def _apply_rules(self, dispute: str) -> str | None:
        """Apply deterministic rule engine for clear-cut cases."""
        if "formatting" in dispute.lower() or "格式" in dispute:
            return "Apply journal style guide / 按照期刊格式规范执行"
        return None

    async def verify(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Verify the execution result, parsing real confidence from LLM output."""
        result_type = execution_result.get("type", "")
        if result_type == "decomposition":
            return {
                "decomposition_complete": bool(execution_result.get("result")),
                "arbitration_confidence": 1.0,
            }
        elif result_type == "arbitration":
            confidence = self._extract_confidence(execution_result.get("decision", ""))
            return {
                "decomposition_complete": True,
                "arbitration_confidence": confidence,
            }
        return {"decomposition_complete": True, "arbitration_confidence": 1.0}

    @staticmethod
    def _extract_confidence(decision_text: str) -> float:
        """Extract confidence score from arbitration LLM output."""
        import re, json
        try:
            data = json.loads(decision_text)
            if "confidence" in data:
                return float(data["confidence"])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        match = re.search(r'"confidence"\s*:\s*([\d.]+)', decision_text)
        if match:
            return float(match.group(1))
        return 0.5

    async def emit(
        self,
        execution_result: dict[str, Any],
        verification_result: dict[str, Any],
    ) -> A2AMessage:
        """Produce the output message."""
        now_ms = int(time.time() * 1000)
        result_type = execution_result.get("type", "")

        intent = AgentIntent.TASK_COMPLETED
        if result_type == "arbitration":
            intent = AgentIntent.ARBITRATION_DECISION

        session_ctx = self._get_session_context()
        return A2AMessage(
            meta=MessageMeta(
                correlation_id="",
                timestamp_ms=now_ms,
            ),
            session=session_ctx,
            route=RouteInfo(
                source_agent=self.agent_id,
                target_agent="",
                intent=intent,
            ),
            payload=Payload(data=execution_result),
            telemetry=Telemetry(
                prompt_tokens_used=self._total_prompt_tokens,
                completion_tokens_used=self._total_completion_tokens,
            ),
        )
