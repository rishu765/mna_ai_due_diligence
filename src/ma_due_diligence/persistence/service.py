"""Application service composing metadata persistence and encrypted blob storage."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .database import PilotDatabase
from .document_store import EncryptedLocalDocumentStore
from .models import JsonObject, PilotAuditEvent, StoredDocumentRecord


class PilotDocumentService:
    """Keeps encrypted blob creation and database registration consistent."""

    def __init__(
        self,
        database: PilotDatabase,
        document_store: EncryptedLocalDocumentStore,
    ) -> None:
        self._database = database
        self._document_store = document_store

    def store_document(
        self,
        *,
        deal_id: str,
        document_id: str,
        original_filename: str,
        content: bytes,
        content_type: str,
        actor_id: str,
        metadata: JsonObject | None = None,
        occurred_at: datetime | None = None,
    ) -> StoredDocumentRecord:
        timestamp = occurred_at or datetime.now(UTC)
        blob = self._document_store.put(
            deal_id=deal_id,
            document_id=document_id,
            content=content,
        )
        record = StoredDocumentRecord(
            document_id=document_id,
            deal_id=deal_id,
            original_filename=original_filename,
            storage_key=blob.storage_key,
            plaintext_sha256=blob.plaintext_sha256,
            plaintext_size_bytes=blob.plaintext_size_bytes,
            encrypted_size_bytes=blob.encrypted_size_bytes,
            content_type=content_type,
            metadata={} if metadata is None else metadata,
            created_by=actor_id,
            created_at=timestamp,
        )
        event = PilotAuditEvent(
            event_id=f"audit-{uuid4().hex}",
            deal_id=deal_id,
            actor_id=actor_id,
            action="document_stored",
            object_type="document",
            object_id=document_id,
            detail={
                "plaintext_sha256": blob.plaintext_sha256,
                "plaintext_size_bytes": blob.plaintext_size_bytes,
                "content_type": content_type,
            },
            occurred_at=timestamp,
        )
        try:
            self._database.add_document_with_audit(record, event)
        except Exception:
            self._document_store.delete(blob.storage_key)
            raise
        return record

    def read_document(self, *, deal_id: str, document_id: str) -> bytes:
        record = self._database.get_document(deal_id, document_id)
        if record is None:
            raise KeyError(f"document not found in deal: {document_id}")
        return self._document_store.read(
            deal_id=deal_id,
            document_id=document_id,
            storage_key=record.storage_key,
            expected_sha256=record.plaintext_sha256,
        )
