---
name: pdmaws-dev
description: Development guide for the PD-MAWS multi-agent academic writing system. Use when adding new agents, modifying workflow, working with the four-layer protocol stack (L1-L4), or extending the system architecture.
---

# PD-MAWS Development Guide

## Architecture Overview

PD-MAWS uses a four-layer protocol stack:

| Layer | Path | Purpose |
|-------|------|---------|
| L1 | `core/l1/` | LLM providers, RAG retriever, academic search, code sandbox, document export |
| L2 | `core/acp/` | Agent state machine (`IDLE→PLAN→EXECUTE→VERIFY→EMIT→DONE`) |
| L3 | `core/a2a/` | Message bus (Redis Streams + Pub/Sub), 6-level message validation |
| L4 | `core/anp/` | Session registry, document blackboard, token circuit breaker, deadlock detection |

Workflow orchestration: `workflow/graph.py` (LangGraph StateGraph).

## Adding a New Agent

1. Create `backend/app/agents/your_agent.py` inheriting from `BaseAgent`:

```python
from app.core.acp.base_agent import BaseAgent
from app.models.agent import AgentConstraints, AgentRole, QualityGate

class YourAgent(BaseAgent):
    def __init__(self, agent_id: str = "Your_Agent_01"):
        constraints = AgentConstraints(
            agent_id=agent_id,
            role=AgentRole.YOUR_ROLE,  # Add to AgentRole enum first
            allowed_actions=["ACTION_1", "ACTION_2"],
            forbidden_actions=["WRITE_DRAFT_CONTENT"],
            quality_gates=[
                QualityGate(name="gate_name", gate_type="assertion"),
            ],
        )
        super().__init__(agent_id, constraints)

    async def plan(self, message): ...
    async def execute(self, message, plan): ...
    async def verify(self, execution_result): ...  # MUST return real values, NOT hardcoded
    async def emit(self, execution_result, verification_result): ...
```

2. Add the role to `models/agent.py` AgentRole enum.
3. Add a workflow node in `workflow/graph.py`.
4. Add prompt in `workflow/prompts.py`.
5. Add config in `config.py`: `agent_yourname_provider` + `agent_yourname_model`.

## Prompt Engineering Rules

All prompts live in `workflow/prompts.py` (workflow layer) or as module-level constants in agent files (A2A layer).

Every prompt MUST include:
- **Role definition** (2-3 lines of domain expertise)
- **CoT steps** (numbered thinking steps)
- **Output format** (explicit JSON schema or tag structure)
- **Self-check** (quality checklist before submission)

Use `__PAPER_CONTEXT__` placeholder for global context injection.

## Context Engineering Rules

- Use `context.py:build_paper_context_block()` to inject global paper context into every node.
- Use `context.py:smart_truncate()` instead of `[:N]` hard cuts.
- Use `context.py:format_evidence_for_writer()` to format real papers for writer prompts.
- The `WritingState.paper_context` dict carries domain, key_arguments, terminology, completed_summary across all nodes.

## Workflow Flow

```
decompose → evidence → write → diagrams → integrate
→ review --(pass)--> format → END
         --(fail)--> revise → integrate (loop, max 2)
```

Evidence is gathered BEFORE writing (correct dependency order).

## Token Tracking

Every LLM call in `graph.py` goes through `_TrackedProvider` which automatically records usage in the circuit breaker. If adding LLM calls outside the workflow, call `_record_token_usage()` manually.

## Quality Gate Rules

- `verify()` MUST return real computed values, NEVER hardcode `True` or fixed numbers.
- Parse LLM output for confidence scores; fall back to 0.5 if parsing fails.
- Unknown `gate_type` values are treated as FAIL (not PASS).

## Security

- JWT auth protects all `/api/` endpoints (optional in dev mode).
- Token endpoint: `POST /api/auth/token`.
- API keys are encrypted via Fernet (see `crypto.py`).
- `DecryptionError` is raised on failure — never silently returns empty string.

## Available Tools

| Tool | Module | Purpose |
|------|--------|---------|
| Academic Search | `core/l1/academic_search.py` | Semantic Scholar, arXiv, CrossRef APIs |
| Evidence Service | `core/l1/evidence_service.py` | Unified search across all sources + Qdrant |
| Code Sandbox | `core/l1/code_sandbox.py` | Safe Python execution with import whitelist |
| Document Export | `core/l1/document_export.py` | Markdown → LaTeX / PDF / DOCX |
| Literature Retriever | `core/l1/retriever.py` | Qdrant vector search for local papers |
