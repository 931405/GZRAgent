"""
FastAPI REST API routes for session management and document operations.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["sessions", "documents"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    topic: str = Field(description="Paper topic / title")
    outline: list[dict[str, Any]] = Field(default_factory=list, description="Paper outline sections")
    max_turns: int = Field(default=6, ge=1)
    budget_limit: int = Field(default=200_000, ge=0)


class SessionResponse(BaseModel):
    session_id: str
    state: str
    version: int
    participants: list[str]
    turn_counter: int
    budget_utilization: float


class CreateDocumentRequest(BaseModel):
    session_id: str
    sections: list[dict[str, Any]] = Field(default_factory=list)


class PatchDocumentRequest(BaseModel):
    author_agent: str
    base_version_hash: str
    patches: list[dict[str, Any]]
    commit_message: str = ""


class StartWorkflowRequest(BaseModel):
    session_id: str
    paper_topic: str
    outline: list[dict[str, Any]]


class WorkflowResponse(BaseModel):
    session_id: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------

@router.post("/sessions", response_model=SessionResponse)
async def create_session(req: CreateSessionRequest) -> SessionResponse:
    """Create a new writing session."""
    from app.main import get_registry
    import uuid

    registry = get_registry()
    session_id = f"sess_{uuid.uuid4()}"

    entry = await registry.create_session(
        session_id=session_id,
        max_turns=req.max_turns,
        budget_limit=req.budget_limit,
    )

    return SessionResponse(
        session_id=entry.session_id,
        state=entry.state.value,
        version=entry.session_version,
        participants=entry.participants,
        turn_counter=entry.turn_counter,
        budget_utilization=entry.budget_snapshot.utilization_pct,
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Get session state."""
    from app.main import get_registry

    registry = get_registry()
    entry = await registry.get_session(session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return SessionResponse(
        session_id=entry.session_id,
        state=entry.state.value,
        version=entry.session_version,
        participants=entry.participants,
        turn_counter=entry.turn_counter,
        budget_utilization=entry.budget_snapshot.utilization_pct,
    )


@router.get("/sessions", response_model=list[str])
async def list_sessions() -> list[str]:
    """List all session IDs."""
    from app.main import get_registry
    registry = get_registry()
    return await registry.list_sessions()


# ---------------------------------------------------------------------------
# Document endpoints
# ---------------------------------------------------------------------------

@router.post("/documents")
async def create_document(req: CreateDocumentRequest) -> dict:
    """Create a new document on the Blackboard."""
    from app.main import get_blackboard

    bb = get_blackboard()
    doc = await bb.create_document(
        session_id=req.session_id,
        sections=[s for s in req.sections],
    )
    return {
        "draft_id": doc.draft_id,
        "state": doc.state.value,
        "version_hash": doc.current_version_hash,
    }


@router.get("/documents/{draft_id}")
async def get_document(draft_id: str) -> dict:
    """Get document state."""
    from app.main import get_blackboard

    bb = get_blackboard()
    doc = await bb.get_document(draft_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {draft_id}")

    return doc.model_dump()


@router.post("/documents/{draft_id}/patch")
async def patch_document(draft_id: str, req: PatchDocumentRequest) -> dict:
    """Submit a patch to a document."""
    from app.main import get_blackboard
    from app.core.anp.blackboard import VersionConflictError, DocumentLockedError

    bb = get_blackboard()
    try:
        doc = await bb.submit_patch(
            draft_id=draft_id,
            author_agent=req.author_agent,
            base_version_hash=req.base_version_hash,
            patches=req.patches,
            commit_message=req.commit_message,
        )
        return {
            "draft_id": doc.draft_id,
            "state": doc.state.value,
            "new_version_hash": doc.current_version_hash,
        }
    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DocumentLockedError as e:
        raise HTTPException(status_code=423, detail=str(e))


# ---------------------------------------------------------------------------
# Workflow endpoints
# ---------------------------------------------------------------------------

@router.post("/workflow/start", response_model=WorkflowResponse)
async def start_workflow(req: StartWorkflowRequest) -> WorkflowResponse:
    """Start the writing workflow for a session."""
    from app.workflow.graph import compile_workflow

    workflow = compile_workflow()
    initial_state = {
        "session_id": req.session_id,
        "paper_topic": req.paper_topic,
        "outline": req.outline,
    }

    result = await workflow.ainvoke(initial_state)

    return WorkflowResponse(
        session_id=req.session_id,
        status=result.get("status", "unknown"),
        result=result,
    )


# ---------------------------------------------------------------------------
# Health & System endpoints
# ---------------------------------------------------------------------------

@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "PD-MAWS"}


@router.get("/system/token-usage")
async def get_token_usage() -> dict:
    """Get global token budget usage."""
    from app.main import get_circuit_breaker
    cb = get_circuit_breaker()
    return await cb.get_global_usage()
