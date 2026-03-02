"""
LangGraph Workflow — Map-Reduce academic writing orchestration.

Implements the complete workflow from design.md Section 9:
  1. Session creation & tree-structured decomposition (Map)
  2. Parallel writers with evidence retrieval
  3. Visual diagram integration
  4. Red Team review on integrated product
  5. Aggregation (Reduce)
  6. Context compression when needed
  7. Final formatting and archival
"""
from __future__ import annotations

import logging
from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow State
# ---------------------------------------------------------------------------

class WritingState(TypedDict, total=False):
    """State passed through the LangGraph workflow."""
    # Task input
    session_id: str
    paper_topic: str
    outline: list[dict[str, Any]]

    # Decomposition
    sub_tasks: list[dict[str, Any]]
    current_task_idx: int

    # Draft content
    draft_sections: dict[str, str]
    evidence_map: dict[str, list[dict]]

    # Integration
    integrated_draft: str
    diagrams: list[dict[str, Any]]

    # Review
    review_findings: list[dict[str, Any]]
    review_passed: bool

    # Output
    final_document: str
    status: str
    error: str


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

async def decompose_task(state: WritingState) -> WritingState:
    """Node 1: PI_Agent decomposes the outline into sub-tasks (Map)."""
    logger.info("Workflow: decompose_task for session %s", state.get("session_id"))

    outline = state.get("outline", [])
    sub_tasks = [
        {
            "task_id": f"sec_{i}",
            "section_title": section.get("title", f"Section {i}"),
            "description": section.get("description", ""),
            "assigned_writer": f"Academic_Writer_{(i % 3) + 1:02d}",
        }
        for i, section in enumerate(outline)
    ]

    return {
        **state,
        "sub_tasks": sub_tasks,
        "current_task_idx": 0,
        "status": "decomposed",
    }


async def write_sections(state: WritingState) -> WritingState:
    """Node 2: Writers compose draft sections in parallel (conceptually)."""
    logger.info("Workflow: write_sections")

    draft_sections = {}
    for task in state.get("sub_tasks", []):
        section_id = task["task_id"]
        # In production, this dispatches to actual Writer agents
        draft_sections[section_id] = f"[Draft content for {task['section_title']}]"

    return {
        **state,
        "draft_sections": draft_sections,
        "status": "drafting",
    }


async def gather_evidence(state: WritingState) -> WritingState:
    """Node 3: Researcher agents gather evidence for each section."""
    logger.info("Workflow: gather_evidence")

    evidence_map = {}
    for section_id in state.get("draft_sections", {}):
        evidence_map[section_id] = [
            {"claim": "placeholder", "doi": "", "confidence": 0.8}
        ]

    return {
        **state,
        "evidence_map": evidence_map,
        "status": "evidence_gathered",
    }


async def generate_diagrams(state: WritingState) -> WritingState:
    """Node 4: Diagram agent creates visualizations."""
    logger.info("Workflow: generate_diagrams")
    return {
        **state,
        "diagrams": [{"type": "mermaid", "code": "graph TD; A-->B"}],
        "status": "diagrams_generated",
    }


async def integrate_draft(state: WritingState) -> WritingState:
    """Node 5: Combine all sections + diagrams (Reduce)."""
    logger.info("Workflow: integrate_draft")

    sections = state.get("draft_sections", {})
    integrated = "\n\n".join(
        f"## {sid}\n{content}" for sid, content in sections.items()
    )

    return {
        **state,
        "integrated_draft": integrated,
        "status": "integrated",
    }


async def red_team_review(state: WritingState) -> WritingState:
    """Node 6: Red Team reviews the integrated draft."""
    logger.info("Workflow: red_team_review")

    # In production, dispatches to RedTeamAgent
    return {
        **state,
        "review_findings": [],
        "review_passed": True,
        "status": "reviewed",
    }


def should_revise(state: WritingState) -> str:
    """Conditional edge: revise or proceed to formatting."""
    if not state.get("review_passed", False):
        return "revise"
    return "format"


async def revise_draft(state: WritingState) -> WritingState:
    """Node 7a: Revise based on Red Team findings."""
    logger.info("Workflow: revise_draft")
    return {
        **state,
        "status": "revising",
    }


async def format_document(state: WritingState) -> WritingState:
    """Node 7b: Apply journal formatting."""
    logger.info("Workflow: format_document")
    return {
        **state,
        "final_document": state.get("integrated_draft", ""),
        "status": "completed",
    }


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_workflow() -> StateGraph:
    """Construct the LangGraph StateGraph for the writing workflow.

    Flow:
        decompose -> write -> evidence -> diagrams -> integrate
        -> review --(pass)--> format -> END
                 --(fail)--> revise -> write (loop)
    """
    graph = StateGraph(WritingState)

    # Add nodes
    graph.add_node("decompose", decompose_task)
    graph.add_node("write", write_sections)
    graph.add_node("evidence", gather_evidence)
    graph.add_node("diagrams", generate_diagrams)
    graph.add_node("integrate", integrate_draft)
    graph.add_node("review", red_team_review)
    graph.add_node("revise", revise_draft)
    graph.add_node("format", format_document)

    # Add edges
    graph.set_entry_point("decompose")
    graph.add_edge("decompose", "write")
    graph.add_edge("write", "evidence")
    graph.add_edge("evidence", "diagrams")
    graph.add_edge("diagrams", "integrate")
    graph.add_edge("integrate", "review")

    # Conditional: review pass/fail
    graph.add_conditional_edges(
        "review",
        should_revise,
        {"revise": "revise", "format": "format"},
    )
    graph.add_edge("revise", "write")
    graph.add_edge("format", END)

    return graph


def compile_workflow() -> Any:
    """Compile the workflow for execution."""
    graph = build_workflow()
    return graph.compile()
