from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from ma_due_diligence.domain import ReviewActionType, Severity
from ma_due_diligence.persistence import (
    ArtifactKind,
    DealStatus,
    EncryptedLocalDocumentStore,
    PersistenceConflictError,
    PersistentWorkflowRuntime,
    PilotArtifactRecord,
    PilotAuditEvent,
    PilotDatabase,
    PilotDealRecord,
    PilotDocumentService,
    PilotReviewEvent,
    PilotReviewEventType,
    PilotRunRecord,
    StoredDocumentRecord,
    StoredDocumentStatus,
    document_key_from_environment,
    generate_document_key,
)
from ma_due_diligence.specialists.fixtures import (
    build_specialist_engagement,
    create_specialist_fixture_vdr,
)
from ma_due_diligence.workflow_final import (
    HumanReviewSubmission,
    ReviewDecision,
    WorkflowRequest,
    WorkflowStatus,
)
from ma_due_diligence.workflow_final.checkpointing import EncryptedCheckpointSerializer


def _deal(deal_id: str = "deal-northstar") -> PilotDealRecord:
    timestamp = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    return PilotDealRecord(
        deal_id=deal_id,
        name="Project Northstar",
        target_name="SecureTech",
        buyer_name="Northstar Holdings",
        transaction_type="acquisition",
        reporting_currency="gbp",
        as_of_date=date(2026, 6, 30),
        materiality_threshold="1000000",
        unit="units",
        workstreams=("financial", "commercial", "legal_contractual", "operational"),
        notes="Controlled synthetic-data pilot",
        status=DealStatus.ACTIVE,
        created_by="pilot-admin",
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_encrypted_document_store_round_trip_and_context_binding(tmp_path: Path) -> None:
    store = EncryptedLocalDocumentStore(tmp_path / "objects", bytes(range(32)))
    content = b"highly confidential diligence evidence"

    blob = store.put(deal_id="deal-a", document_id="doc-1", content=content)

    encrypted_path = tmp_path / "objects" / blob.storage_key
    encrypted_payload = encrypted_path.read_bytes()
    assert content not in encrypted_payload
    assert blob.plaintext_size_bytes == len(content)
    assert blob.encrypted_size_bytes == len(encrypted_payload)
    assert (
        store.read(
            deal_id="deal-a",
            document_id="doc-1",
            storage_key=blob.storage_key,
            expected_sha256=blob.plaintext_sha256,
        )
        == content
    )

    with pytest.raises(InvalidTag):
        store.read(
            deal_id="deal-b",
            document_id="doc-1",
            storage_key=blob.storage_key,
            expected_sha256=blob.plaintext_sha256,
        )
    with pytest.raises(ValueError, match="invalid storage key"):
        store.read(
            deal_id="deal-a",
            document_id="doc-1",
            storage_key="../escape.madd",
            expected_sha256=blob.plaintext_sha256,
        )


def test_encrypted_document_store_deletes_only_valid_internal_key(tmp_path: Path) -> None:
    store = EncryptedLocalDocumentStore(tmp_path / "objects", bytes(range(32)))
    blob = store.put(deal_id="deal-a", document_id="doc-1", content=b"evidence")
    encrypted_path = tmp_path / "objects" / blob.storage_key

    store.delete(blob.storage_key)

    assert not encrypted_path.exists()
    with pytest.raises(ValueError, match="invalid storage key"):
        store.delete("../../outside")


def test_document_key_helpers_validate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = generate_document_key()
    monkeypatch.setenv("MADD_DOCUMENT_KEY", encoded)
    assert len(document_key_from_environment()) == 32

    monkeypatch.setenv("MADD_DOCUMENT_KEY", "YQ==")
    with pytest.raises(RuntimeError, match="exactly 32 bytes"):
        document_key_from_environment()

    monkeypatch.setenv("MADD_DOCUMENT_KEY", "%%%")
    with pytest.raises(RuntimeError, match="not valid URL-safe base64"):
        document_key_from_environment()


def test_encrypted_checkpoint_serializer_rejects_wrong_key() -> None:
    serializer = EncryptedCheckpointSerializer(bytes(range(32)))
    payload = {"target": "SecureTech", "status": "review_required"}

    encoded = serializer.dumps_typed(payload)

    assert b"SecureTech" not in encoded[1]
    assert serializer.loads_typed(encoded) == payload
    with pytest.raises(InvalidTag):
        EncryptedCheckpointSerializer(bytes(reversed(range(32)))).loads_typed(encoded)


def test_database_persists_deal_document_run_artifact_and_audit(tmp_path: Path) -> None:
    database_path = tmp_path / "pilot.sqlite3"
    database = PilotDatabase(database_path)
    database.initialize()
    deal = _deal()
    database.create_deal(deal)

    store = EncryptedLocalDocumentStore(tmp_path / "objects", bytes(range(32)))
    blob = store.put(
        deal_id=deal.deal_id,
        document_id="doc-accounts",
        content=b"FY25 revenue GBP 108m",
    )
    document = StoredDocumentRecord(
        document_id="doc-accounts",
        deal_id=deal.deal_id,
        original_filename="FY25 accounts.pdf",
        storage_key=blob.storage_key,
        plaintext_sha256=blob.plaintext_sha256,
        plaintext_size_bytes=blob.plaintext_size_bytes,
        encrypted_size_bytes=blob.encrypted_size_bytes,
        content_type="application/pdf",
        status=StoredDocumentStatus.STORED,
        metadata={"period": "FY25", "workstream": "financial"},
        created_by="analyst-1",
        created_at=deal.created_at,
    )
    database.add_document(document)

    run = PilotRunRecord(
        run_id="run-1",
        deal_id=deal.deal_id,
        status="review_required",
        review_policy="when_needed",
        state={"review_reasons": 7, "warning_count": 5},
        created_by="analyst-1",
        created_at=deal.created_at,
        updated_at=deal.updated_at,
    )
    database.save_run(run)
    artifact = PilotArtifactRecord(
        artifact_id="finding-1",
        deal_id=deal.deal_id,
        run_id=run.run_id,
        kind=ArtifactKind.FINDING,
        payload={"title": "Revenue sources disagree", "severity": "critical"},
        created_at=deal.created_at,
    )
    database.add_artifact(artifact)
    audit = PilotAuditEvent(
        event_id="event-1",
        deal_id=deal.deal_id,
        actor_id="analyst-1",
        action="document_uploaded",
        object_type="document",
        object_id=document.document_id,
        detail={"sha256": document.plaintext_sha256},
        occurred_at=deal.created_at,
    )
    database.append_audit_event(audit)

    reopened = PilotDatabase(database_path)
    assert reopened.schema_version() == 4
    assert reopened.get_deal(deal.deal_id) == deal
    assert reopened.get_document(deal.deal_id, document.document_id) == document
    assert reopened.get_run(deal.deal_id, run.run_id) == run
    assert reopened.list_artifacts(deal.deal_id, run.run_id) == (artifact,)
    assert reopened.list_audit_events(deal.deal_id) == (audit,)
    assert reopened.list_documents_by_checksum(deal.deal_id, blob.plaintext_sha256) == (document,)


def test_database_queries_and_foreign_keys_preserve_deal_scope(tmp_path: Path) -> None:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    first = _deal("deal-a")
    second = replace(first, deal_id="deal-b", name="Project Cedar")
    database.create_deal(first)
    database.create_deal(second)
    timestamp = first.created_at
    run = PilotRunRecord(
        run_id="run-a",
        deal_id=first.deal_id,
        status="created",
        review_policy="when_needed",
        created_at=timestamp,
        updated_at=timestamp,
    )
    database.save_run(run)

    assert database.get_run(second.deal_id, run.run_id) is None
    with pytest.raises(PersistenceConflictError, match="another deal"):
        database.save_run(replace(run, deal_id=second.deal_id))

    orphan = StoredDocumentRecord(
        document_id="orphan",
        deal_id="missing-deal",
        original_filename="orphan.pdf",
        storage_key="0123456789abcdef/0123456789abcdef0123456789abcdef.madd",
        plaintext_sha256="0" * 64,
        plaintext_size_bytes=1,
        encrypted_size_bytes=64,
        content_type="application/pdf",
        created_at=timestamp,
    )
    with pytest.raises(PersistenceConflictError):
        database.add_document(orphan)


def test_database_updates_run_state_without_losing_creation_time(tmp_path: Path) -> None:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    deal = _deal()
    database.create_deal(deal)
    original = PilotRunRecord(
        run_id="run-1",
        deal_id=deal.deal_id,
        status="analyzing",
        review_policy="when_needed",
        state={"completed_nodes": 4},
        created_at=deal.created_at,
        updated_at=deal.created_at,
    )
    database.save_run(original)
    updated = replace(
        original,
        status="review_required",
        state={"completed_nodes": 6, "review_reasons": 7},
        updated_at=deal.updated_at + timedelta(minutes=5),
    )

    database.save_run(updated)

    loaded = database.get_run(deal.deal_id, original.run_id)
    assert loaded == updated
    assert loaded is not None
    assert loaded.created_at == original.created_at


def test_review_history_is_append_only_ordered_and_deal_scoped(tmp_path: Path) -> None:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    deal = _deal()
    database.create_deal(deal)
    run = PilotRunRecord(
        run_id="run-review",
        deal_id=deal.deal_id,
        status="review_required",
        review_policy="when_needed",
        created_at=deal.created_at,
        updated_at=deal.updated_at,
    )
    database.save_run(run)
    event = PilotReviewEvent(
        event_id="review-event-1",
        deal_id=deal.deal_id,
        run_id=run.run_id,
        subject_type="finding",
        subject_id="finding-1",
        event_type=PilotReviewEventType.SEVERITY_CHANGED,
        actor_id="reviewer-1",
        actor_display_name="Deal Reviewer",
        rationale="Evidence supports a lower severity.",
        prior_state={"severity": "high"},
        resulting_state={"severity": "medium"},
        occurred_at=deal.updated_at,
    )

    database.append_review_events((event,))

    reopened = PilotDatabase(database.path)
    assert reopened.list_review_events(deal.deal_id, run.run_id) == (event,)
    assert reopened.list_review_events(
        deal.deal_id,
        run.run_id,
        subject_type="finding",
        subject_id="finding-1",
    ) == (event,)
    assert reopened.list_review_events("another-deal", run.run_id) == ()
    with pytest.raises(PersistenceConflictError):
        database.append_review_events((event,))
    with (
        sqlite3.connect(database.path) as connection,
        pytest.raises(sqlite3.DatabaseError, match="review events are immutable"),
    ):
        connection.execute(
            "UPDATE pilot_review_events SET rationale = ? WHERE event_id = ?",
            ("tampered", event.event_id),
        )
    with (
        sqlite3.connect(database.path) as connection,
        pytest.raises(sqlite3.DatabaseError, match="review events are immutable"),
    ):
        connection.execute(
            "DELETE FROM pilot_review_events WHERE event_id = ?",
            (event.event_id,),
        )


def test_document_service_atomically_registers_blob_metadata_and_audit(tmp_path: Path) -> None:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    deal = _deal()
    database.create_deal(deal)
    object_root = tmp_path / "objects"
    service = PilotDocumentService(
        database,
        EncryptedLocalDocumentStore(object_root, bytes(range(32))),
    )

    record = service.store_document(
        deal_id=deal.deal_id,
        document_id="doc-1",
        original_filename="management accounts.pdf",
        content=b"confidential evidence",
        content_type="application/pdf",
        actor_id="analyst-1",
        metadata={"period": "LTM"},
        occurred_at=deal.created_at,
    )

    assert database.list_documents(deal.deal_id) == (record,)
    assert service.read_document(deal_id=deal.deal_id, document_id=record.document_id) == (
        b"confidential evidence"
    )
    audit = database.list_audit_events(deal.deal_id)
    assert len(audit) == 1
    assert audit[0].object_id == record.document_id
    assert audit[0].detail["plaintext_sha256"] == record.plaintext_sha256


def test_document_service_removes_blob_when_database_registration_fails(tmp_path: Path) -> None:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    deal = _deal()
    database.create_deal(deal)
    object_root = tmp_path / "objects"
    service = PilotDocumentService(
        database,
        EncryptedLocalDocumentStore(object_root, bytes(range(32))),
    )
    service.store_document(
        deal_id=deal.deal_id,
        document_id="doc-1",
        original_filename="accounts.pdf",
        content=b"confidential evidence",
        content_type="application/pdf",
        actor_id="analyst-1",
        occurred_at=deal.created_at,
    )
    existing_blobs = tuple(object_root.rglob("*.madd"))

    with pytest.raises(PersistenceConflictError):
        service.store_document(
            deal_id=deal.deal_id,
            document_id="doc-1",
            original_filename="accounts.pdf",
            content=b"confidential evidence",
            content_type="application/pdf",
            actor_id="analyst-1",
            occurred_at=deal.created_at,
        )

    assert tuple(object_root.rglob("*.madd")) == existing_blobs


def test_encrypted_workflow_checkpoint_survives_runtime_restart(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoints.sqlite3"
    manifest = create_specialist_fixture_vdr(tmp_path / "vdr")
    engagement = build_specialist_engagement()
    thread_id = "persistent-review-run"
    key = bytes(range(32))

    with PersistentWorkflowRuntime(checkpoint_path, key) as first_runtime:
        paused = first_runtime.application.start(
            WorkflowRequest(engagement.engagement_id, engagement, manifest),
            thread_id=thread_id,
        )
        assert paused["status"] is WorkflowStatus.REVIEW_REQUIRED
        finding_id = paused["review_request"].finding_ids[0]

    database_bytes = b"".join(
        path.read_bytes() for path in tmp_path.glob("checkpoints.sqlite3*") if path.is_file()
    )
    assert b"SecureTech" not in database_bytes

    with PersistentWorkflowRuntime(checkpoint_path, key) as second_runtime:
        restored = second_runtime.application.state(thread_id=thread_id)
        assert restored["status"] is WorkflowStatus.REVIEW_REQUIRED
        assert restored["review_request"] == paused["review_request"]
        completed = second_runtime.application.resume(
            thread_id=thread_id,
            submission=HumanReviewSubmission(
                "Deal Team Reviewer",
                "Reviewed after application restart.",
                (
                    ReviewDecision(
                        "finding",
                        finding_id,
                        ReviewActionType.CHANGE_SEVERITY,
                        "Material but mitigable.",
                        Severity.MEDIUM,
                    ),
                ),
            ),
        )

    assert completed["status"] in {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.COMPLETED_WITH_WARNINGS,
    }
    assert completed["report"].review_action_ids
