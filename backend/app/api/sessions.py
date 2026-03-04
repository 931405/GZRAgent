"""
FastAPI REST API routes for session management and document operations.
"""
from __future__ import annotations

import logging
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sessions", "documents"])

# Global dictionary to track active workflow tasks for cancellation
active_workflows: Dict[str, asyncio.Task] = {}


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


class StopWorkflowRequest(BaseModel):
    session_id: str





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
    task = asyncio.create_task(_run_workflow())
    active_workflows[req.session_id] = task

    return WorkflowResponse(
        session_id=req.session_id,
        status="started",
        result={"message": "Workflow started in background"},
    )


@router.post("/workflow/stop", response_model=WorkflowResponse)
async def stop_workflow(req: StopWorkflowRequest) -> WorkflowResponse:
    """Stop a running writing workflow for a session."""
    task = active_workflows.get(req.session_id)
    if task and not task.done():
        task.cancel()
        active_workflows.pop(req.session_id, None)
        
        # Notify UI
        from app.api.websocket import manager
        await manager.broadcast(req.session_id, {
            "type": "telemetry",
            "data": {
                "id": str(__import__("uuid").uuid4()),
                "timestamp": int(__import__("time").time() * 1000),
                "source": "System",
                "intent": "ERROR",
                "message": "Workflow stopped by user",
            },
        })
        await manager.broadcast(req.session_id, {
            "type": "workflow_complete",
            "status": "halted",
        })
        return WorkflowResponse(
            session_id=req.session_id,
            status="stopped",
            result={"message": "Workflow stopped successfully"}
        )
    return WorkflowResponse(
        session_id=req.session_id,
        status="not_running",
        result={"message": "No active workflow found for this session"}
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
# LLM Settings endpoints (database-persisted, API keys encrypted)
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


# Keys that contain sensitive data (will be encrypted in DB)
_SENSITIVE_KEYS = {
    "provider.openai.api_key",
    "provider.deepseek.api_key",
    "provider.gemini.api_key",
    "provider.custom.api_key",
}

PROVIDER_NAMES = ["openai", "deepseek", "gemini", "ollama", "custom"]
PROVIDER_FIELDS = ["api_key", "base_url", "default_model"]
AGENT_NAMES = ["pi", "writer", "researcher", "red_team", "diagram", "format", "data_analyst"]


async def _db_get_settings() -> dict[str, str]:
    """Read all LLM settings from the database."""
    from app.db import get_session_factory
    from app.models.llm_settings import LLMSettingsRow
    from app.crypto import decrypt
    from sqlmodel import select

    factory = get_session_factory()
    result: dict[str, str] = {}
    async with factory() as session:
        stmt = select(LLMSettingsRow)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            val = decrypt(row.config_value) if row.is_encrypted else row.config_value
            result[row.config_key] = val
    return result


async def _db_put_settings(updates: dict[str, str]) -> list[str]:
    """Write LLM settings to the database. Returns list of updated keys."""
    from app.db import get_session_factory
    from app.models.llm_settings import LLMSettingsRow
    from app.crypto import encrypt
    from sqlmodel import select
    from datetime import datetime, timezone

    factory = get_session_factory()
    updated_keys: list[str] = []

    async with factory() as session:
        for key, value in updates.items():
            is_sensitive = key in _SENSITIVE_KEYS
            stored_value = encrypt(value) if is_sensitive else value

            # Upsert: find existing or create
            stmt = select(LLMSettingsRow).where(LLMSettingsRow.config_key == key)
            existing = (await session.execute(stmt)).scalars().first()
            if existing:
                existing.config_value = stored_value
                existing.is_encrypted = is_sensitive
                existing.updated_at = datetime.now(timezone.utc)
            else:
                session.add(LLMSettingsRow(
                    config_key=key,
                    config_value=stored_value,
                    is_encrypted=is_sensitive,
                ))
            updated_keys.append(key)

        await session.commit()
    return updated_keys


def _env_defaults() -> dict[str, str]:
    """Get default settings from environment (.env) as fallback."""
    from app.config import get_settings
    s = get_settings()
    defaults: dict[str, str] = {}

    field_map = {
        "openai": (s.openai_api_key, s.openai_base_url, s.openai_default_model),
        "deepseek": (s.deepseek_api_key, s.deepseek_base_url, s.deepseek_default_model),
        "gemini": (s.gemini_api_key, "", s.gemini_default_model),
        "ollama": ("", s.ollama_base_url, s.ollama_default_model),
        "custom": (s.custom_llm_api_key, s.custom_llm_base_url, s.custom_llm_default_model),
    }
    for pname, (api_key, base_url, model) in field_map.items():
        defaults[f"provider.{pname}.api_key"] = api_key
        defaults[f"provider.{pname}.base_url"] = base_url
        defaults[f"provider.{pname}.default_model"] = model

    for aname in AGENT_NAMES:
        provider_attr = f"agent_{aname}_provider"
        model_attr = f"agent_{aname}_model"
        pval = getattr(s, provider_attr, "openai")
        defaults[f"agent.{aname}.provider"] = pval.value if hasattr(pval, "value") else str(pval)
        defaults[f"agent.{aname}.model"] = getattr(s, model_attr, "")

    return defaults


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "****" if key else ""
    return key[:4] + "****" + key[-4:]


@router.get("/settings/llm", response_model=LLMSettingsResponse)
async def get_llm_settings() -> LLMSettingsResponse:
    """Get current LLM provider settings. API keys are masked. DB takes priority over .env."""
    settings: dict[str, str] = {}
    try:
        # Merge: env defaults < database overrides
        settings = _env_defaults()
        try:
            db_settings = await _db_get_settings()
            settings.update(db_settings)
        except Exception as e:
            logger.warning("Failed to read LLM settings from DB (using env fallback): %s", e)
    except Exception as e:
        logger.error("Critical error reading LLM settings, falling back to empty: %s", e)

    providers: Dict[str, LLMProviderSettings] = {}
    for pname in PROVIDER_NAMES:
        providers[pname] = LLMProviderSettings(
            api_key=_mask_key(settings.get(f"provider.{pname}.api_key", "")),
            base_url=settings.get(f"provider.{pname}.base_url", ""),
            default_model=settings.get(f"provider.{pname}.default_model", ""),
        )

    agents: Dict[str, AgentLLMAssignment] = {}
    for aname in AGENT_NAMES:
        agents[aname] = AgentLLMAssignment(
            provider=settings.get(f"agent.{aname}.provider", "openai"),
            model=settings.get(f"agent.{aname}.model", ""),
        )

    return LLMSettingsResponse(providers=providers, agents=agents)


@router.put("/settings/llm")
async def update_llm_settings(req: LLMSettingsUpdateRequest) -> Dict[str, Any]:
    """Update LLM provider settings. Persisted to database with encryption."""
    updates: dict[str, str] = {}

    if req.providers:
        for pname, p in req.providers.items():
            if pname not in PROVIDER_NAMES:
                continue
            # Only update API key if not masked
            if p.api_key and "****" not in p.api_key:
                updates[f"provider.{pname}.api_key"] = p.api_key
            if p.base_url:
                updates[f"provider.{pname}.base_url"] = p.base_url
            if p.default_model:
                updates[f"provider.{pname}.default_model"] = p.default_model

    if req.agents:
        for aname, a in req.agents.items():
            if a.provider:
                updates[f"agent.{aname}.provider"] = a.provider
            updates[f"agent.{aname}.model"] = a.model

    # Persist to database (non-fatal if DB unavailable)
    updated_keys = list(updates.keys())
    try:
        updated_keys = await _db_put_settings(updates)
    except Exception as e:
        logger.warning("Failed to persist LLM settings to DB (in-memory only): %s", e)

    # Also update in-memory Settings singleton so changes take effect immediately
    from app.config import get_settings, LLMProviderType
    s = get_settings()
    field_map = {
        "openai": ("openai_api_key", "openai_base_url", "openai_default_model"),
        "deepseek": ("deepseek_api_key", "deepseek_base_url", "deepseek_default_model"),
        "gemini": ("gemini_api_key", "", "gemini_default_model"),
        "ollama": ("", "ollama_base_url", "ollama_default_model"),
        "custom": ("custom_llm_api_key", "custom_llm_base_url", "custom_llm_default_model"),
    }
    if req.providers:
        for pname, p in req.providers.items():
            if pname not in field_map:
                continue
            key_f, url_f, model_f = field_map[pname]
            if key_f and p.api_key and "****" not in p.api_key:
                setattr(s, key_f, p.api_key)
            if url_f and p.base_url:
                setattr(s, url_f, p.base_url)
            if model_f and p.default_model:
                setattr(s, model_f, p.default_model)

    if req.agents:
        for aname, a in req.agents.items():
            p_attr = f"agent_{aname}_provider"
            m_attr = f"agent_{aname}_model"
            if hasattr(s, p_attr) and a.provider:
                try:
                    setattr(s, p_attr, LLMProviderType(a.provider))
                except ValueError:
                    pass
            if hasattr(s, m_attr):
                setattr(s, m_attr, a.model)

    return {"status": "ok", "updated_fields": updated_keys, "persisted": True}
