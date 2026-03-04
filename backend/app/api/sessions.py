"""
FastAPI REST API routes for session management and document operations.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["sessions", "documents"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    topic: str = Field(description="Paper topic / title")
    outline: List[Dict[str, Any]] = Field(default_factory=list, description="Paper outline sections")
    max_turns: int = Field(default=6, ge=1)
    budget_limit: int = Field(default=200_000, ge=0)


class SessionResponse(BaseModel):
    session_id: str
    state: str
    version: int
    participants: List[str]
    turn_counter: int
    budget_utilization: float


class CreateDocumentRequest(BaseModel):
    session_id: str
    sections: List[Dict[str, Any]] = Field(default_factory=list)


class PatchDocumentRequest(BaseModel):
    author_agent: str
    base_version_hash: str
    patches: List[Dict[str, Any]]
    commit_message: str = ""


class StartWorkflowRequest(BaseModel):
    session_id: str
    paper_topic: str
    outline: List[Dict[str, Any]]


class WorkflowResponse(BaseModel):
    session_id: str
    status: str
    result: Dict[str, Any] = Field(default_factory=dict)


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


@router.get("/sessions", response_model=List[str])
async def list_sessions() -> List[str]:
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
    """Start the writing workflow for a session (async, fire-and-forget)."""
    import asyncio
    from app.workflow.graph import compile_workflow

    workflow = compile_workflow()
    initial_state = {
        "session_id": req.session_id,
        "paper_topic": req.paper_topic,
        "outline": req.outline,
    }

    async def _run_workflow():
        """Background task that runs the full workflow."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            result = await workflow.ainvoke(initial_state)
            logger.info("Workflow completed for session %s: status=%s",
                        req.session_id, result.get("status"))
        except Exception as e:
            logger.error("Workflow failed for session %s: %s", req.session_id, e)
            # Broadcast error to WebSocket
            from app.api.websocket import manager
            await manager.broadcast(req.session_id, {
                "type": "telemetry",
                "data": {
                    "id": str(__import__("uuid").uuid4()),
                    "timestamp": int(__import__("time").time() * 1000),
                    "source": "System",
                    "intent": "ERROR",
                    "message": f"Workflow failed: {e}",
                },
            })

    # Fire and forget — workflow runs in the background
    asyncio.create_task(_run_workflow())

    return WorkflowResponse(
        session_id=req.session_id,
        status="started",
        result={"message": "Workflow started in background"},
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


# ---------------------------------------------------------------------------
# LLM Settings endpoints
# ---------------------------------------------------------------------------

class LLMProviderSettings(BaseModel):
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""


class AgentLLMAssignment(BaseModel):
    provider: str = ""
    model: str = ""


class LLMSettingsResponse(BaseModel):
    providers: Dict[str, LLMProviderSettings] = Field(default_factory=dict)
    agents: Dict[str, AgentLLMAssignment] = Field(default_factory=dict)


class LLMSettingsUpdateRequest(BaseModel):
    providers: Optional[Dict[str, LLMProviderSettings]] = None
    agents: Optional[Dict[str, AgentLLMAssignment]] = None


@router.get("/settings/llm", response_model=LLMSettingsResponse)
async def get_llm_settings() -> LLMSettingsResponse:
    """Get current LLM provider settings (keys are masked)."""
    from app.config import get_settings
    s = get_settings()

    def mask_key(key: str) -> str:
        if not key or len(key) < 8:
            return "****" if key else ""
        return key[:4] + "****" + key[-4:]

    providers = {
        "openai": LLMProviderSettings(
            api_key=mask_key(s.openai_api_key),
            base_url=s.openai_base_url,
            default_model=s.openai_default_model,
        ),
        "deepseek": LLMProviderSettings(
            api_key=mask_key(s.deepseek_api_key),
            base_url=s.deepseek_base_url,
            default_model=s.deepseek_default_model,
        ),
        "gemini": LLMProviderSettings(
            api_key=mask_key(s.gemini_api_key),
            base_url="",
            default_model=s.gemini_default_model,
        ),
        "ollama": LLMProviderSettings(
            api_key="",
            base_url=s.ollama_base_url,
            default_model=s.ollama_default_model,
        ),
        "custom": LLMProviderSettings(
            api_key=mask_key(s.custom_llm_api_key),
            base_url=s.custom_llm_base_url,
            default_model=s.custom_llm_default_model,
        ),
    }

    agent_names = ["pi", "writer", "researcher", "red_team", "diagram", "format", "data_analyst"]
    agents: Dict[str, AgentLLMAssignment] = {}
    for name in agent_names:
        provider_attr = f"agent_{name}_provider"
        model_attr = f"agent_{name}_model"
        agents[name] = AgentLLMAssignment(
            provider=getattr(s, provider_attr, "openai").value
            if hasattr(getattr(s, provider_attr, ""), "value")
            else str(getattr(s, provider_attr, "openai")),
            model=getattr(s, model_attr, ""),
        )

    return LLMSettingsResponse(providers=providers, agents=agents)


@router.put("/settings/llm")
async def update_llm_settings(req: LLMSettingsUpdateRequest) -> Dict[str, Any]:
    """Update LLM provider settings at runtime."""
    from app.config import get_settings, LLMProviderType
    s = get_settings()

    updated_fields: List[str] = []

    if req.providers:
        field_map = {
            "openai": ("openai_api_key", "openai_base_url", "openai_default_model"),
            "deepseek": ("deepseek_api_key", "deepseek_base_url", "deepseek_default_model"),
            "gemini": ("gemini_api_key", "", "gemini_default_model"),
            "ollama": ("", "ollama_base_url", "ollama_default_model"),
            "custom": ("custom_llm_api_key", "custom_llm_base_url", "custom_llm_default_model"),
        }
        for provider_name, provider_settings in req.providers.items():
            if provider_name not in field_map:
                continue
            key_field, url_field, model_field = field_map[provider_name]
            # Only update api_key if it's not a masked value
            if key_field and provider_settings.api_key and "****" not in provider_settings.api_key:
                setattr(s, key_field, provider_settings.api_key)
                updated_fields.append(key_field)
            if url_field and provider_settings.base_url:
                setattr(s, url_field, provider_settings.base_url)
                updated_fields.append(url_field)
            if model_field and provider_settings.default_model:
                setattr(s, model_field, provider_settings.default_model)
                updated_fields.append(model_field)

    if req.agents:
        for agent_name, assignment in req.agents.items():
            provider_attr = f"agent_{agent_name}_provider"
            model_attr = f"agent_{agent_name}_model"
            if hasattr(s, provider_attr) and assignment.provider:
                try:
                    setattr(s, provider_attr, LLMProviderType(assignment.provider))
                    updated_fields.append(provider_attr)
                except ValueError:
                    pass
            if hasattr(s, model_attr):
                setattr(s, model_attr, assignment.model)
                updated_fields.append(model_attr)

    return {"status": "ok", "updated_fields": updated_fields}
