"""
Unit tests for PD-MAWS Pydantic models.
"""
import time
import pytest
from app.models.errors import ErrorCode, AckType
from app.models.a2a import (
    A2AMessage, MessageMeta, SessionContext, RouteInfo,
    Payload, AgentIntent, MessagePriority,
)
from app.models.session import SessionState, SessionEntry, VALID_SESSION_TRANSITIONS
from app.models.document import DocumentState, DocumentBlackboard, PatchOperation, VALID_DOCUMENT_TRANSITIONS
from app.models.agent import AgentConstraints, AgentRole, QualityGate, EvidenceOutput


class TestErrorCodes:
    def test_all_error_codes_exist(self):
        expected = [
            "ERR_SCHEMA_INVALID", "ERR_AUTH_INVALID", "ERR_REPLAY_DETECTED",
            "ERR_SESSION_STALE", "ERR_GROUNDING_NOT_FOUND", "ERR_GROUNDING_UNAVAILABLE",
            "ERR_TIMEOUT", "ERR_DEADLOCK_SUSPECTED", "ERR_RATE_LIMITED",
            "ERR_POLICY_VIOLATION", "ERR_VERSION_CONFLICT", "ERR_DOCUMENT_LOCKED",
        ]
        for code in expected:
            assert hasattr(ErrorCode, code)

    def test_ack_types(self):
        assert AckType.ACK.value == "ACK"
        assert AckType.NACK_RETRYABLE.value == "NACK_RETRYABLE"
        assert AckType.NACK_FATAL.value == "NACK_FATAL"


class TestA2AMessage:
    def test_create_minimal_message(self):
        msg = A2AMessage(
            meta=MessageMeta(
                correlation_id="corr-001",
                timestamp_ms=int(time.time() * 1000),
            ),
            session=SessionContext(
                session_id="sess_001",
                session_version=1,
                current_turn=0,
            ),
            route=RouteInfo(
                source_agent="Agent_A",
                target_agent="Agent_B",
                intent=AgentIntent.REQUEST_TASK,
            ),
        )
        assert msg.meta.schema_version == "a2a.v1"
        assert msg.meta.message_id  # auto-generated
        assert msg.route.intent == AgentIntent.REQUEST_TASK

    def test_message_serialization_roundtrip(self):
        msg = A2AMessage(
            meta=MessageMeta(
                correlation_id="corr-002",
                timestamp_ms=1700000000000,
            ),
            session=SessionContext(
                session_id="sess_002",
                session_version=5,
                current_turn=2,
            ),
            route=RouteInfo(
                source_agent="Writer_01",
                target_agent="Researcher_01",
                intent=AgentIntent.REQUEST_EVIDENCE,
            ),
            payload=Payload(
                context_grounding=["doc_ref_1", "doc_ref_2"],
            ),
        )
        json_str = msg.model_dump_json()
        restored = A2AMessage.model_validate_json(json_str)
        assert restored.session.session_id == "sess_002"
        assert restored.payload.context_grounding == ["doc_ref_1", "doc_ref_2"]

    def test_priority_and_ttl(self):
        msg = A2AMessage(
            meta=MessageMeta(
                correlation_id="corr-003",
                timestamp_ms=1700000000000,
                priority=MessagePriority.CRITICAL,
                ttl_ms=5000,
            ),
            session=SessionContext(session_id="s", session_version=1, current_turn=0),
            route=RouteInfo(
                source_agent="A", target_agent="B",
                intent=AgentIntent.HALT,
            ),
        )
        assert msg.meta.priority == MessagePriority.CRITICAL
        assert msg.meta.ttl_ms == 5000


class TestSessionState:
    def test_valid_transitions(self):
        entry = SessionEntry(session_id="s1")
        assert entry.state == SessionState.INIT
        assert entry.can_transition_to(SessionState.RUNNING)
        assert not entry.can_transition_to(SessionState.COMPLETED)

    def test_terminal_states_have_no_transitions(self):
        assert VALID_SESSION_TRANSITIONS[SessionState.COMPLETED] == set()
        assert VALID_SESSION_TRANSITIONS[SessionState.FAILED] == set()

    def test_session_entry_fields(self):
        entry = SessionEntry(
            session_id="sess_test",
            parent_session_id="sess_parent",
            sub_task_id="sec_intro",
            participants=["Writer_01", "Researcher_01"],
        )
        assert entry.session_version == 1
        assert entry.turn_counter == 0
        assert len(entry.participants) == 2


class TestDocumentBlackboard:
    def test_document_state_transitions(self):
        doc = DocumentBlackboard(session_id="s1")
        assert doc.state == DocumentState.EMPTY
        assert doc.can_transition_to(DocumentState.DRAFTING)
        assert not doc.can_transition_to(DocumentState.FINAL)

    def test_patch_operation(self):
        patch = PatchOperation(
            op="replace",
            path="/sections/0/content",
            value="New content here",
        )
        assert patch.op == "replace"
        assert patch.path == "/sections/0/content"


class TestAgentConstraints:
    def test_pi_agent_constraints(self):
        c = AgentConstraints(
            agent_id="PI_01",
            role=AgentRole.PI,
            allowed_actions=["DECOMPOSE_TASK", "ARBITRATE_CONFLICT"],
            forbidden_actions=["WRITE_DRAFT_CONTENT"],
            quality_gates=[
                QualityGate(name="confidence", threshold=0.7, gate_type="threshold"),
            ],
        )
        assert c.role == AgentRole.PI
        assert "WRITE_DRAFT_CONTENT" in c.forbidden_actions
        assert c.quality_gates[0].threshold == 0.7

    def test_evidence_output(self):
        e = EvidenceOutput(
            claim="Neural networks improve accuracy",
            evidence_ids=["doc_001", "doc_002"],
            doi_or_ref="10.1234/example",
            confidence=0.95,
            retrieved_at=int(time.time() * 1000),
        )
        assert e.confidence == 0.95
        assert len(e.evidence_ids) == 2
