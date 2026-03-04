"""
Document Blackboard Models.

Implements the document version-controlled blackboard:
  - Document state machine (EMPTY -> DRAFTING -> ... -> FINAL)
  - PatchOperation (JSON Patch RFC 6902)
  - DraftVersion (immutable version snapshot)
  - DocumentBlackboard (the complete document entity)

Ref: design.md Section 4.4
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field
import uuid


class DocumentState(str, Enum):
    """Document lifecycle states.

    State flow:
        EMPTY -> DRAFTING -> CONFLICT -> DRAFTING  (resolved)
        DRAFTING -> REVIEW_PENDING -> DRAFTING  (rejected)
        REVIEW_PENDING -> INTEGRATED -> FINAL

    Ref: design.md Section 4.4
    """
    EMPTY = "EMPTY"
    DRAFTING = "DRAFTING"
    CONFLICT = "CONFLICT"
    REVIEW_PENDING = "REVIEW_PENDING"
    INTEGRATED = "INTEGRATED"
    FINAL = "FINAL"


VALID_DOCUMENT_TRANSITIONS: Dict[DocumentState, Set[DocumentState]] = {
    DocumentState.EMPTY: {DocumentState.DRAFTING},
    DocumentState.DRAFTING: {
        DocumentState.DRAFTING,        # patch accepted
        DocumentState.CONFLICT,        # concurrent conflict
        DocumentState.REVIEW_PENDING,  # submitted for review
    },
    DocumentState.CONFLICT: {
        DocumentState.DRAFTING,  # conflict resolved
    },
    DocumentState.REVIEW_PENDING: {
        DocumentState.DRAFTING,     # review rejected
        DocumentState.INTEGRATED,   # graphics merged
    },
    DocumentState.INTEGRATED: {
        DocumentState.REVIEW_PENDING,  # Red Team rejection
        DocumentState.FINAL,           # approved
    },
    DocumentState.FINAL: set(),  # terminal
}


class PatchOperation(BaseModel):
    """A single JSON Patch operation (RFC 6902).

    Used instead of full-text overwrite to enable:
    - Bandwidth efficiency
    - Conflict detection via version_hash
    - Full audit trail
    """
    op: str = Field(
        description="Operation type: add | remove | replace | move | copy | test",
    )
    path: str = Field(
        description="JSON Pointer path (e.g. /sections/3/content)",
    )
    value: Any = Field(
        default=None,
        description="Value for add/replace operations",
    )
    from_path: Optional[str] = Field(
        default=None,
        alias="from",
        description="Source path for move/copy operations",
    )


class DraftVersion(BaseModel):
    """An immutable snapshot of a document version.

    Conceptually similar to a Git commit — once created, cannot be modified.
    """
    version_hash: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique hash for this version (used for optimistic locking)",
    )
    parent_hash: str = Field(
        default="",
        description="Hash of the parent version (forms version DAG)",
    )
    author_agent: str = Field(
        description="Agent who created this version",
    )
    patches: List[PatchOperation] = Field(
        default_factory=list,
        description="Patches applied on top of parent_hash",
    )
    timestamp_ms: int = Field(
        description="Creation timestamp",
    )
    commit_message: str = Field(
        default="",
        description="Human-readable description of changes",
    )


class SectionContent(BaseModel):
    """Content of a single document section."""
    section_id: str
    title: str = ""
    content: str = ""
    order: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentBlackboard(BaseModel):
    """The Document Blackboard — shared knowledge base for document content.

    Separates long-form text (data plane) from control messages.
    All modifications must go through Patch with version_hash locking.

    Ref: design.md Section 4.4
    """
    draft_id: str = Field(
        default_factory=lambda: f"doc_{uuid.uuid4()}",
    )
    session_id: str = Field(
        description="Owning session ID",
    )
    state: DocumentState = Field(
        default=DocumentState.EMPTY,
    )
    current_version_hash: str = Field(
        default="",
        description="Hash of the latest accepted version",
    )
    sections: List[SectionContent] = Field(
        default_factory=list,
        description="Current materialized sections",
    )
    version_history: List[DraftVersion] = Field(
        default_factory=list,
        description="Ordered list of all committed versions",
    )
    pending_patches: List[PatchOperation] = Field(
        default_factory=list,
        description="Patches waiting to be applied (e.g. during CONFLICT)",
    )
    locked_by: str = Field(
        default="",
        description="Agent ID holding the write lock (empty = unlocked)",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
    )

    def can_transition_to(self, target: DocumentState) -> bool:
        """Check whether transition from current state to target is valid."""
        return target in VALID_DOCUMENT_TRANSITIONS.get(self.state, set())
