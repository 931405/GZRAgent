"""
Document Blackboard Manager.

Manages document state, version-controlled patches (Git-like), and
conflict detection with optimistic locking.

Key invariant (design.md §1.2.2):
  All document modifications MUST go through Diff/Patch with version lock.
  No full-text transmission in control-plane messages.

Ref: design.md Section 4.4
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import redis.asyncio as redis
import uuid

from app.models.document import (
    DocumentBlackboard,
    DocumentState,
    DraftVersion,
    PatchOperation,
    SectionContent,
    VALID_DOCUMENT_TRANSITIONS,
)

logger = logging.getLogger(__name__)

_BLACKBOARD_PREFIX = "pdmaws:blackboard:"
_BLACKBOARD_INDEX = "pdmaws:blackboard_index"


class VersionConflictError(Exception):
    """Raised when a patch is submitted against a stale version."""


class DocumentLockedError(Exception):
    """Raised when trying to modify a locked document."""


class InvalidDocumentTransition(Exception):
    """Raised when an invalid document state transition is attempted."""


class BlackboardManager:
    """Manages the Document Blackboard — shared knowledge base for drafts.

    Features:
    - Git-like version DAG with immutable snapshots
    - Optimistic locking via version_hash
    - Conflict detection for concurrent modifications
    - Section-level content management
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    @staticmethod
    def _key(draft_id: str) -> str:
        return f"{_BLACKBOARD_PREFIX}{draft_id}"

    @staticmethod
    def _compute_hash(content: str) -> str:
        """Compute a deterministic hash for content versioning."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_document(
        self,
        session_id: str,
        sections: Optional[list[dict]] = None,
    ) -> DocumentBlackboard:
        """Create a new empty document on the blackboard."""
        draft_id = f"doc_{uuid.uuid4()}"
        initial_hash = self._compute_hash(draft_id + str(time.time()))

        doc = DocumentBlackboard(
            draft_id=draft_id,
            session_id=session_id,
            state=DocumentState.EMPTY,
            current_version_hash=initial_hash,
            sections=[
                SectionContent(**s) for s in (sections or [])
            ],
        )

        key = self._key(draft_id)
        await self._redis.hset(key, mapping={"data": doc.model_dump_json()})  # type: ignore
        await self._redis.sadd(_BLACKBOARD_INDEX, draft_id)

        logger.info("Document created: %s for session %s", draft_id, session_id)
        return doc

    async def get_document(self, draft_id: str) -> Optional[DocumentBlackboard]:
        """Retrieve a document from the blackboard."""
        key = self._key(draft_id)
        raw = await self._redis.hget(key, "data")
        if raw is None:
            return None
        return DocumentBlackboard.model_validate_json(raw)

    async def list_documents(
        self, session_id: Optional[str] = None
    ) -> list[str]:
        """List all document IDs, optionally filtered by session."""
        members = await self._redis.smembers(_BLACKBOARD_INDEX)
        all_ids = [m.decode() if isinstance(m, bytes) else m for m in members]

        if session_id is None:
            return all_ids

        result = []
        for did in all_ids:
            doc = await self.get_document(did)
            if doc and doc.session_id == session_id:
                result.append(did)
        return result

    # ------------------------------------------------------------------
    # Patch submission (with optimistic locking)
    # ------------------------------------------------------------------

    async def submit_patch(
        self,
        draft_id: str,
        author_agent: str,
        base_version_hash: str,
        patches: list[dict[str, Any]],
        commit_message: str = "",
    ) -> DocumentBlackboard:
        """Submit a patch to a document with optimistic locking.

        Args:
            draft_id: Target document.
            author_agent: Agent submitting the patch.
            base_version_hash: The version this patch is based on.
            patches: List of JSON Patch operations.
            commit_message: Human-readable description.

        Raises:
            VersionConflictError: If base_version_hash doesn't match current.
            DocumentLockedError: If document is locked by another agent.
        """
        doc = await self.get_document(draft_id)
        if doc is None:
            raise ValueError(f"Document not found: {draft_id}")

        # Check lock
        if doc.locked_by and doc.locked_by != author_agent:
            raise DocumentLockedError(
                f"Document {draft_id} is locked by {doc.locked_by}"
            )

        # Optimistic lock check
        if doc.current_version_hash != base_version_hash:
            # Version conflict detected
            if doc.state != DocumentState.CONFLICT:
                doc.state = DocumentState.CONFLICT
                doc.pending_patches.extend(
                    [PatchOperation(**p) for p in patches]
                )
                await self._save(doc)

            raise VersionConflictError(
                f"Version conflict on {draft_id}: "
                f"expected {base_version_hash}, "
                f"current is {doc.current_version_hash}"
            )

        # Apply patches
        patch_ops = [PatchOperation(**p) for p in patches]
        self._apply_patches(doc, patch_ops)

        # Create version snapshot
        new_hash = self._compute_hash(
            json.dumps([s.model_dump() for s in doc.sections])
        )
        version = DraftVersion(
            version_hash=new_hash,
            parent_hash=base_version_hash,
            author_agent=author_agent,
            patches=patch_ops,
            timestamp_ms=int(time.time() * 1000),
            commit_message=commit_message,
        )
        doc.version_history.append(version)
        doc.current_version_hash = new_hash

        # Transition state to DRAFTING if needed
        if doc.state == DocumentState.EMPTY:
            doc.state = DocumentState.DRAFTING
        elif doc.state == DocumentState.CONFLICT:
            doc.state = DocumentState.DRAFTING

        await self._save(doc)

        logger.info(
            "Patch applied to %s by %s: %s -> %s (%d ops)",
            draft_id, author_agent, base_version_hash,
            new_hash, len(patches),
        )
        return doc

    def _apply_patches(
        self,
        doc: DocumentBlackboard,
        patches: list[PatchOperation],
    ) -> None:
        """Apply patch operations to document sections."""
        for patch in patches:
            if patch.op == "replace":
                self._apply_replace(doc, patch)
            elif patch.op == "add":
                self._apply_add(doc, patch)
            elif patch.op == "remove":
                self._apply_remove(doc, patch)
            # move, copy, test can be added as needed

    def _apply_replace(
        self, doc: DocumentBlackboard, patch: PatchOperation
    ) -> None:
        """Apply a 'replace' operation."""
        parts = patch.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "sections":
            idx = int(parts[1])
            if 0 <= idx < len(doc.sections):
                if len(parts) == 3 and parts[2] == "content":
                    doc.sections[idx].content = str(patch.value or "")
                elif len(parts) == 3 and parts[2] == "title":
                    doc.sections[idx].title = str(patch.value or "")
                elif len(parts) == 2:
                    if isinstance(patch.value, dict):
                        doc.sections[idx] = SectionContent(**patch.value)

    def _apply_add(
        self, doc: DocumentBlackboard, patch: PatchOperation
    ) -> None:
        """Apply an 'add' operation."""
        parts = patch.path.strip("/").split("/")
        if parts[0] == "sections" and len(parts) == 2:
            if isinstance(patch.value, dict):
                idx = int(parts[1]) if parts[1] != "-" else len(doc.sections)
                section = SectionContent(**patch.value)
                doc.sections.insert(idx, section)

    def _apply_remove(
        self, doc: DocumentBlackboard, patch: PatchOperation
    ) -> None:
        """Apply a 'remove' operation."""
        parts = patch.path.strip("/").split("/")
        if parts[0] == "sections" and len(parts) == 2:
            idx = int(parts[1])
            if 0 <= idx < len(doc.sections):
                doc.sections.pop(idx)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    async def transition_state(
        self, draft_id: str, target: DocumentState
    ) -> DocumentBlackboard:
        """Transition document state.

        Raises InvalidDocumentTransition if not valid.
        """
        doc = await self.get_document(draft_id)
        if doc is None:
            raise ValueError(f"Document not found: {draft_id}")

        if not doc.can_transition_to(target):
            raise InvalidDocumentTransition(
                f"Cannot transition {draft_id}: "
                f"{doc.state} -> {target}"
            )

        doc.state = target
        await self._save(doc)

        logger.info("Document %s state -> %s", draft_id, target.value)
        return doc

    # ------------------------------------------------------------------
    # Locking
    # ------------------------------------------------------------------

    async def lock_document(
        self, draft_id: str, agent_id: str
    ) -> DocumentBlackboard:
        """Acquire a write lock on a document."""
        doc = await self.get_document(draft_id)
        if doc is None:
            raise ValueError(f"Document not found: {draft_id}")

        if doc.locked_by and doc.locked_by != agent_id:
            raise DocumentLockedError(
                f"Document {draft_id} already locked by {doc.locked_by}"
            )

        doc.locked_by = agent_id
        await self._save(doc)
        return doc

    async def unlock_document(
        self, draft_id: str, agent_id: str
    ) -> DocumentBlackboard:
        """Release a write lock on a document."""
        doc = await self.get_document(draft_id)
        if doc is None:
            raise ValueError(f"Document not found: {draft_id}")

        if doc.locked_by and doc.locked_by != agent_id:
            raise DocumentLockedError(
                f"Cannot unlock: {draft_id} is locked by {doc.locked_by}, "
                f"not {agent_id}"
            )

        doc.locked_by = ""
        await self._save(doc)
        return doc

    # ------------------------------------------------------------------
    # Force update (Human Proxy)
    # ------------------------------------------------------------------

    async def force_update(
        self,
        draft_id: str,
        section_id: str,
        new_content: str,
        author: str = "human_proxy",
    ) -> DocumentBlackboard:
        """Force-update a section (Human_Proxy_Agent highest privilege).

        Bypasses optimistic locking. Creates a version record for audit.
        Ref: design.md Section 8.5
        """
        doc = await self.get_document(draft_id)
        if doc is None:
            raise ValueError(f"Document not found: {draft_id}")

        # Find section
        target_section = None
        for s in doc.sections:
            if s.section_id == section_id:
                target_section = s
                break

        if target_section is None:
            raise ValueError(
                f"Section {section_id} not found in {draft_id}"
            )

        old_content = target_section.content
        target_section.content = new_content

        # Create audit version
        new_hash = self._compute_hash(
            json.dumps([s.model_dump() for s in doc.sections])
        )
        version = DraftVersion(
            version_hash=new_hash,
            parent_hash=doc.current_version_hash,
            author_agent=author,
            patches=[PatchOperation(
                op="replace",
                path=f"/sections/{section_id}/content",
                value=new_content,
            )],
            timestamp_ms=int(time.time() * 1000),
            commit_message=f"FORCE_UPDATE by {author}",
        )
        doc.version_history.append(version)
        doc.current_version_hash = new_hash

        await self._save(doc)

        logger.warning(
            "FORCE_UPDATE on %s section %s by %s",
            draft_id, section_id, author,
        )
        return doc

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _save(self, doc: DocumentBlackboard) -> None:
        """Save document to Redis."""
        key = self._key(doc.draft_id)
        await self._redis.hset(key, mapping={"data": doc.model_dump_json()})  # type: ignore
