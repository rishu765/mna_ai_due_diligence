from __future__ import annotations

from contextlib import suppress
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import gettempdir

import pytest
from fastapi.testclient import TestClient

from ma_due_diligence.api.pilot_app import PilotApiContext, create_pilot_app
from ma_due_diligence.api.pilot_documents import (
    PilotDocumentProcessingService,
    UploadPolicy,
    UploadRejectedError,
)
from ma_due_diligence.persistence import (
    EncryptedLocalDocumentStore,
    PilotDatabase,
    PilotDealRecord,
    PilotDocumentService,
    StoredDocumentStatus,
)
from ma_due_diligence.security import DealRole
from ma_due_diligence.security.service import PilotAuthService
from ma_due_diligence.specialists.fixtures import create_specialist_fixture_vdr
from ma_due_diligence.vdr.ingestion import manifest_from_json

_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
_EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"


def _deal(deal_id: str = "deal-a") -> PilotDealRecord:
    return PilotDealRecord(
        deal_id=deal_id,
        name="Project Northstar",
        target_name="SecureTech",
        buyer_name="Northstar Holdings",
        transaction_type="acquisition",
        reporting_currency="GBP",
        as_of_date=date(2026, 6, 30),
        workstreams=("financial", "commercial", "legal_contractual", "operational"),
        created_by="user-admin",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _services(
    tmp_path: Path,
    *,
    policy: UploadPolicy | None = None,
) -> tuple[PilotDatabase, PilotDocumentProcessingService]:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    database.create_deal(_deal())
    store = EncryptedLocalDocumentStore(tmp_path / "documents", bytes(range(32)))
    processor = PilotDocumentProcessingService(
        database,
        PilotDocumentService(database, store),
        policy=policy,
    )
    return database, processor


def test_valid_csv_is_scanned_encrypted_parsed_and_indexed(tmp_path: Path) -> None:
    database, processor = _services(tmp_path)

    record = processor.process_upload(
        deal_id="deal-a",
        encoded_filename="revenue_by_customer.csv",
        content_type="text/csv",
        content=b"customer,revenue\nAlpha,42000000\nBeta,12000000\n",
        actor_id="user-analyst",
        batch_id="batch-1",
    )

    assert record.status is StoredDocumentStatus.INDEXED
    assert record.metadata["document_type"] == "sales_report"
    assert record.metadata["table_row_count"] == 3
    assert record.metadata["chunk_count"] == 3
    assert database.get_document("deal-a", record.document_id) == record
    chunks = database.list_document_chunks("deal-a", record.document_id)
    assert len(chunks) == 3
    assert chunks[1]["row_numbers"] == [2]
    assert [event.action for event in database.list_audit_events("deal-a")] == [
        "document_stored",
        "document_processing_completed",
    ]


def test_parse_failure_is_persisted_without_discarding_document(tmp_path: Path) -> None:
    database, processor = _services(tmp_path)

    record = processor.process_upload(
        deal_id="deal-a",
        encoded_filename="broken.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7\nnot a real document",
        actor_id="user-analyst",
        batch_id="batch-2",
    )

    assert record.status is StoredDocumentStatus.FAILED
    assert record.metadata["processing_stage"] == "failed"
    assert record.metadata["issues"]
    assert str(Path(gettempdir())) not in str(record.metadata["issues"])
    assert "broken.pdf" in str(record.metadata["issues"])
    assert database.get_document("deal-a", record.document_id) == record
    assert database.list_document_chunks("deal-a", record.document_id) == ()


def test_malware_signature_and_duplicate_are_rejected_and_audited(tmp_path: Path) -> None:
    database, processor = _services(tmp_path)
    with pytest.raises(UploadRejectedError, match="failed the local malware"):
        processor.process_upload(
            deal_id="deal-a",
            encoded_filename="eicar.txt",
            content_type="text/plain",
            content=_EICAR,
            actor_id="user-analyst",
            batch_id="batch-3",
        )

    clean = b"metric,value\nrevenue,100\n"
    processor.process_upload(
        deal_id="deal-a",
        encoded_filename="metrics.csv",
        content_type="text/csv",
        content=clean,
        actor_id="user-analyst",
        batch_id="batch-3",
    )
    with pytest.raises(UploadRejectedError, match="Exact duplicate"):
        processor.process_upload(
            deal_id="deal-a",
            encoded_filename="renamed.csv",
            content_type="text/csv",
            content=clean,
            actor_id="user-analyst",
            batch_id="batch-3",
        )

    assert database.list_audit_events("deal-a")[0].action == "document_upload_rejected"


def test_validation_rejects_unsafe_mismatched_and_oversized_files(tmp_path: Path) -> None:
    _, processor = _services(tmp_path, policy=UploadPolicy(maximum_file_bytes=16))
    cases = (
        ("../escape.txt", "text/plain", b"safe", "Filename is unsafe"),
        ("report.pdf", "application/pdf", b"not a pdf", "not a PDF"),
        ("report.exe", "application/octet-stream", b"MZ", "Unsupported file type"),
        ("large.txt", "text/plain", b"a" * 17, "upload limit"),
    )
    for filename, content_type, content, message in cases:
        with pytest.raises(UploadRejectedError, match=message):
            processor.process_upload(
                deal_id="deal-a",
                encoded_filename=filename,
                content_type=content_type,
                content=content,
                actor_id="user-analyst",
                batch_id="batch-4",
            )


def test_authenticated_api_uploads_and_reports_batch_status(tmp_path: Path) -> None:
    database, processor = _services(tmp_path)
    database.create_deal(_deal("deal-b"))
    auth = PilotAuthService(database)
    admin = auth.provision_user(
        email="admin@example.com",
        display_name="Pilot Admin",
        password="admin password long enough",
        is_pilot_admin=True,
        user_id="user-admin",
        occurred_at=_NOW,
    )
    analyst = auth.provision_user(
        email="analyst@example.com",
        display_name="Deal Analyst",
        password="analyst password long enough",
        user_id="user-analyst",
        occurred_at=_NOW,
    )
    principal = auth.login(email=admin.email, password="admin password long enough").principal
    auth.assign_deal_role(
        actor=principal,
        deal_id="deal-a",
        user_id=analyst.user_id,
        role=DealRole.ANALYST,
        occurred_at=_NOW,
    )
    client = TestClient(create_pilot_app(PilotApiContext(database, auth, documents=processor)))
    login = client.post(
        "/pilot/auth/login",
        json={"email": analyst.email, "password": "analyst password long enough"},
    )
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "Content-Type": "text/csv",
        "X-Filename": "revenue.csv",
        "X-Upload-Batch": "batch-api",
    }

    uploaded = client.post(
        "/pilot/deals/deal-a/documents",
        headers=headers,
        content=b"period,revenue\nFY2025,100\n",
    )
    duplicate = client.post(
        "/pilot/deals/deal-a/documents",
        headers={**headers, "X-Filename": "renamed.csv"},
        content=b"period,revenue\nFY2025,100\n",
    )
    hidden = client.post(
        "/pilot/deals/deal-b/documents",
        headers=headers,
        content=b"period,revenue\nFY2025,100\n",
    )
    batch = client.get(
        "/pilot/deals/deal-a/document-batches/batch-api",
        headers={"Authorization": headers["Authorization"]},
    )

    assert uploaded.status_code == 201
    assert uploaded.json()["status"] == "indexed"
    assert duplicate.status_code == 409
    assert hidden.status_code == 404
    assert batch.status_code == 200
    assert batch.json()["complete"] is True
    assert batch.json()["status_counts"]["indexed"] == 1
    assert batch.json()["rejection_count"] == 1
    assert batch.json()["rejections"][0]["filename"] == "renamed.csv"


def test_representative_vdr_produces_complete_transparent_batch_report(tmp_path: Path) -> None:
    _, processor = _services(tmp_path)
    manifest_path = create_specialist_fixture_vdr(tmp_path / "representative-vdr")
    manifest = manifest_from_json(manifest_path)
    content_types = {
        ".csv": "text/csv",
        ".htm": "text/html",
        ".html": "text/html",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    for entry in manifest.entries:
        source = Path(entry.source_path)
        with suppress(UploadRejectedError):
            processor.process_upload(
                deal_id="deal-a",
                encoded_filename=source.name,
                content_type=content_types.get(
                    source.suffix.casefold(), "application/octet-stream"
                ),
                content=source.read_bytes(),
                actor_id="user-analyst",
                batch_id="batch-representative",
            )

    report = processor.batch_payload("deal-a", "batch-representative")
    document_count = report["document_count"]
    rejection_count = report["rejection_count"]
    status_counts = report["status_counts"]
    assert isinstance(document_count, int)
    assert isinstance(rejection_count, int)
    assert isinstance(status_counts, dict)
    assert report["complete"] is True
    assert document_count + rejection_count == len(manifest.entries)
    assert status_counts["stored"] == 0
    assert status_counts["processing"] == 0
    assert status_counts["indexed"] > 0
