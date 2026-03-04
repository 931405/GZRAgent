"""
Agent Constraint Declaration Models.

Every Agent must declare its constraints — this is the ACP (Agent Control
Protocol) "identity card" that determines what actions are allowed, forbidden,
and what quality gates must pass before output emission.

Ref: design.md Section 7.2
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    """Predefined agent roles in the PD-MAWS system."""
    PI = "PI"                           # 调度与仲裁
    WRITER = "WRITER"                   # 编撰者
    RESEARCHER = "RESEARCHER"           # 文献检索
    DIAGRAM = "DIAGRAM"                 # 图表生成
    RED_TEAM = "RED_TEAM"               # 对抗审查
    HUMAN_PROXY = "HUMAN_PROXY"         # 人类代理
    FORMAT_CONTROLLER = "FORMAT_CONTROLLER"  # 排版规范
    DATA_ANALYST = "DATA_ANALYST"       # 数据分析


class QualityGate(BaseModel):
    """A quality gate that must pass before EMIT.

    Quality gates are checked in the VERIFY phase of the ACP state machine.
    If any gate fails, the agent cannot proceed to EMIT.
    """
    name: str = Field(description="Gate identifier")
    description: str = Field(default="", description="What this gate checks")
    gate_type: str = Field(
        default="assertion",
        description="Gate type: assertion | threshold | schema_check | custom",
    )
    threshold: Optional[float] = Field(
        default=None,
        description="Numeric threshold (for threshold-type gates)",
    )
    required: bool = Field(
        default=True,
        description="If True, failure blocks EMIT; if False, only warns",
    )


class AgentConstraints(BaseModel):
    """Constraint declaration for an Agent.

    Ref: design.md Section 7.2 — every Agent MUST declare:
      - Role
      - AllowedActions
      - ForbiddenActions
      - QualityGates

    Violation of ForbiddenActions → immediate NACK + audit record.
    """
    agent_id: str = Field(
        description="Unique agent instance identifier",
    )
    role: AgentRole = Field(
        description="The agent's role in the system",
    )
    allowed_actions: List[str] = Field(
        default_factory=list,
        description="Actions this agent is permitted to perform",
    )
    forbidden_actions: List[str] = Field(
        default_factory=list,
        description="Actions this agent is NEVER permitted to perform. "
                    "Violation triggers immediate NACK + audit.",
    )
    quality_gates: List[QualityGate] = Field(
        default_factory=list,
        description="Quality gates checked during VERIFY phase",
    )
    max_consecutive_errors: int = Field(
        default=3,
        ge=1,
        description="After this many consecutive errors, auto-report to ANP",
    )
    token_budget: int = Field(
        default=200_000,
        ge=0,
        description="Per-agent soft token budget",
    )
    llm_provider: str = Field(
        default="openai",
        description="LLM provider type for this agent",
    )
    llm_model: str = Field(
        default="",
        description="Specific model override (empty = use provider default)",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
    )


class EvidenceOutput(BaseModel):
    """Structured evidence output from Literature_Researcher_Agent.

    Ref: design.md Section 8.2
    """
    claim: str = Field(description="The factual claim being evidenced")
    evidence_ids: List[str] = Field(description="IDs of evidence documents")
    doi_or_ref: str = Field(default="", description="DOI or reference")
    confidence: float = Field(ge=0.0, le=1.0, description="Evidence confidence")
    retrieved_at: int = Field(description="Retrieval timestamp (ms)")


class ArbDecision(BaseModel):
    """Arbitration decision structure output by PI_Agent.

    Ref: design.md Section 8.1
    """
    decision_id: str
    dispute_summary: str
    resolution: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    escalate_to_human: bool = False
    affected_sessions: List[str] = Field(default_factory=list)
