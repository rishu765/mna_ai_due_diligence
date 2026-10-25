"""SQLite persistence adapter for the controlled pilot boundary."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import cast

from .models import (
    ArtifactKind,
    DealStatus,
    JsonObject,
    PilotArtifactRecord,
    PilotAuditEvent,
    PilotDealRecord,
    PilotRunRecord,
    StoredDocumentRecord,
    StoredDocumentStatus,
)

_SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS pilot_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_deals (
    deal_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target_name TEXT NOT NULL,
    buyer_name TEXT,
    transaction_type TEXT NOT NULL,
    reporting_currency TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    materiality_threshold TEXT,
    unit TEXT NOT NULL,
    workstreams_json TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_documents (
    document_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    plaintext_sha256 TEXT NOT NULL,
    plaintext_size_bytes INTEGER NOT NULL CHECK (plaintext_size_bytes >= 0),
    encrypted_size_bytes INTEGER NOT NULL CHECK (encrypted_size_bytes > 0),
    content_type TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (deal_id) REFERENCES pilot_deals(deal_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pilot_documents_deal_checksum
ON pilot_documents(deal_id, plaintext_sha256);

CREATE TABLE IF NOT EXISTS pilot_runs (
    run_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL,
    status TEXT NOT NULL,
    review_policy TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (deal_id, run_id),
    FOREIGN KEY (deal_id) REFERENCES pilot_deals(deal_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pilot_runs_deal_updated
ON pilot_runs(deal_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS pilot_artifacts (
    artifact_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    created_at TEXT NOT NULL,
    UNIQUE (deal_id, artifact_id),
    FOREIGN KEY (deal_id, run_id) REFERENCES pilot_runs(deal_id, run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pilot_artifacts_deal_run_kind
ON pilot_artifacts(deal_id, run_id, kind);

CREATE TABLE IF NOT EXISTS pilot_audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    deal_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (deal_id) REFERENCES pilot_deals(deal_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pilot_audit_deal_sequence
ON pilot_audit_events(deal_id, sequence);
"""


class PersistenceConflictError(RuntimeError):
    """Raised when an identifier already belongs to another persisted object."""


class PilotDatabase:
    """Deal-scoped repository backed by a single SQLite database file."""

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(_SCHEMA_V1)
            connection.execute(
                "INSERT OR IGNORE INTO pilot_schema_migrations(version, applied_at) "
                "VALUES (?, datetime('now'))",
                (_SCHEMA_VERSION,),
            )

    def schema_version(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM pilot_schema_migrations"
            ).fetchone()
        return int(row["version"])

    def create_deal(self, record: PilotDealRecord) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pilot_deals (
                        deal_id, name, target_name, buyer_name, transaction_type,
                        reporting_currency, as_of_date, materiality_threshold, unit,
                        workstreams_json, notes, status, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.deal_id,
                        record.name,
                        record.target_name,
                        record.buyer_name,
                        record.transaction_type,
                        record.reporting_currency,
                        record.as_of_date.isoformat(),
                        record.materiality_threshold,
                        record.unit,
                        _json_dumps(list(record.workstreams)),
                        record.notes,
                        record.status.value,
                        record.created_by,
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(f"deal_id already exists: {record.deal_id}") from error

    def get_deal(self, deal_id: str) -> PilotDealRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM pilot_deals WHERE deal_id = ?",
                (deal_id,),
            ).fetchone()
        return None if row is None else _deal_from_row(row)

    def add_document(self, record: StoredDocumentRecord) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pilot_documents (
                        document_id, deal_id, original_filename, storage_key,
                        plaintext_sha256, plaintext_size_bytes, encrypted_size_bytes,
                        content_type, status, metadata_json, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.document_id,
                        record.deal_id,
                        record.original_filename,
                        record.storage_key,
                        record.plaintext_sha256,
                        record.plaintext_size_bytes,
                        record.encrypted_size_bytes,
                        record.content_type,
                        record.status.value,
                        _json_dumps(record.metadata),
                        record.created_by,
                        record.created_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(
                f"document cannot be stored for deal {record.deal_id}: {record.document_id}"
            ) from error

    def add_document_with_audit(
        self,
        record: StoredDocumentRecord,
        event: PilotAuditEvent,
    ) -> None:
        """Atomically register an encrypted document and its creation event."""

        if event.deal_id != record.deal_id:
            raise ValueError("document and audit event must belong to the same deal")
        if event.object_type != "document" or event.object_id != record.document_id:
            raise ValueError("document audit event must identify the stored document")
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pilot_documents (
                        document_id, deal_id, original_filename, storage_key,
                        plaintext_sha256, plaintext_size_bytes, encrypted_size_bytes,
                        content_type, status, metadata_json, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.document_id,
                        record.deal_id,
                        record.original_filename,
                        record.storage_key,
                        record.plaintext_sha256,
                        record.plaintext_size_bytes,
                        record.encrypted_size_bytes,
                        record.content_type,
                        record.status.value,
                        _json_dumps(record.metadata),
                        record.created_by,
                        record.created_at.isoformat(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO pilot_audit_events (
                        event_id, deal_id, actor_id, action, object_type,
                        object_id, detail_json, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.deal_id,
                        event.actor_id,
                        event.action,
                        event.object_type,
                        event.object_id,
                        _json_dumps(event.detail),
                        event.occurred_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(
                f"document cannot be stored for deal {record.deal_id}: {record.document_id}"
            ) from error

    def get_document(self, deal_id: str, document_id: str) -> StoredDocumentRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM pilot_documents WHERE deal_id = ? AND document_id = ?",
                (deal_id, document_id),
            ).fetchone()
        return None if row is None else _document_from_row(row)

    def list_documents_by_checksum(
        self,
        deal_id: str,
        plaintext_sha256: str,
    ) -> tuple[StoredDocumentRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM pilot_documents
                WHERE deal_id = ? AND plaintext_sha256 = ?
                ORDER BY created_at, document_id
                """,
                (deal_id, plaintext_sha256.casefold()),
            ).fetchall()
        return tuple(_document_from_row(row) for row in rows)

    def list_documents(self, deal_id: str) -> tuple[StoredDocumentRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM pilot_documents
                WHERE deal_id = ?
                ORDER BY created_at, document_id
                """,
                (deal_id,),
            ).fetchall()
        return tuple(_document_from_row(row) for row in rows)

    def save_run(self, record: PilotRunRecord) -> None:
        try:
            with self._connection() as connection:
                existing = connection.execute(
                    "SELECT deal_id, created_at FROM pilot_runs WHERE run_id = ?",
                    (record.run_id,),
                ).fetchone()
                if existing is not None and str(existing["deal_id"]) != record.deal_id:
                    raise PersistenceConflictError(
                        f"run_id {record.run_id} belongs to another deal"
                    )
                created_at = (
                    record.created_at.isoformat()
                    if existing is None
                    else str(existing["created_at"])
                )
                connection.execute(
                    """
                    INSERT INTO pilot_runs (
                        run_id, deal_id, status, review_policy, state_json,
                        created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        status = excluded.status,
                        review_policy = excluded.review_policy,
                        state_json = excluded.state_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record.run_id,
                        record.deal_id,
                        record.status,
                        record.review_policy,
                        _json_dumps(record.state),
                        record.created_by,
                        created_at,
                        record.updated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(
                f"run cannot be stored for deal {record.deal_id}: {record.run_id}"
            ) from error

    def get_run(self, deal_id: str, run_id: str) -> PilotRunRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM pilot_runs WHERE deal_id = ? AND run_id = ?",
                (deal_id, run_id),
            ).fetchone()
        return None if row is None else _run_from_row(row)

    def add_artifact(self, record: PilotArtifactRecord) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pilot_artifacts (
                        artifact_id, deal_id, run_id, kind, payload_json,
                        schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.artifact_id,
                        record.deal_id,
                        record.run_id,
                        record.kind.value,
                        _json_dumps(record.payload),
                        record.schema_version,
                        record.created_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(
                f"artifact cannot be stored for deal {record.deal_id}: {record.artifact_id}"
            ) from error

    def list_artifacts(
        self,
        deal_id: str,
        run_id: str,
        *,
        kind: ArtifactKind | None = None,
    ) -> tuple[PilotArtifactRecord, ...]:
        parameters: tuple[str, ...]
        if kind is None:
            sql = (
                "SELECT * FROM pilot_artifacts WHERE deal_id = ? AND run_id = ? "
                "ORDER BY created_at, artifact_id"
            )
            parameters = (deal_id, run_id)
        else:
            sql = (
                "SELECT * FROM pilot_artifacts WHERE deal_id = ? AND run_id = ? AND kind = ? "
                "ORDER BY created_at, artifact_id"
            )
            parameters = (deal_id, run_id, kind.value)
        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def append_audit_event(self, event: PilotAuditEvent) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pilot_audit_events (
                        event_id, deal_id, actor_id, action, object_type,
                        object_id, detail_json, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.deal_id,
                        event.actor_id,
                        event.action,
                        event.object_type,
                        event.object_id,
                        _json_dumps(event.detail),
                        event.occurred_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(
                f"audit event cannot be stored for deal {event.deal_id}: {event.event_id}"
            ) from error

    def list_audit_events(self, deal_id: str) -> tuple[PilotAuditEvent, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM pilot_audit_events
                WHERE deal_id = ?
                ORDER BY sequence
                """,
                (deal_id,),
            ).fetchall()
        return tuple(_audit_from_row(row) for row in rows)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_object(payload: str) -> JsonObject:
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("persisted JSON payload must be an object")
    return cast(JsonObject, decoded)


def _string_list(payload: str) -> tuple[str, ...]:
    decoded = json.loads(payload)
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise ValueError("persisted workstreams must be a list of strings")
    return tuple(cast(list[str], decoded))


def _deal_from_row(row: sqlite3.Row) -> PilotDealRecord:
    return PilotDealRecord(
        deal_id=str(row["deal_id"]),
        name=str(row["name"]),
        target_name=str(row["target_name"]),
        buyer_name=None if row["buyer_name"] is None else str(row["buyer_name"]),
        transaction_type=str(row["transaction_type"]),
        reporting_currency=str(row["reporting_currency"]),
        as_of_date=date.fromisoformat(str(row["as_of_date"])),
        materiality_threshold=(
            None if row["materiality_threshold"] is None else str(row["materiality_threshold"])
        ),
        unit=str(row["unit"]),
        workstreams=_string_list(str(row["workstreams_json"])),
        notes=None if row["notes"] is None else str(row["notes"]),
        status=DealStatus(str(row["status"])),
        created_by=str(row["created_by"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _document_from_row(row: sqlite3.Row) -> StoredDocumentRecord:
    return StoredDocumentRecord(
        document_id=str(row["document_id"]),
        deal_id=str(row["deal_id"]),
        original_filename=str(row["original_filename"]),
        storage_key=str(row["storage_key"]),
        plaintext_sha256=str(row["plaintext_sha256"]),
        plaintext_size_bytes=int(row["plaintext_size_bytes"]),
        encrypted_size_bytes=int(row["encrypted_size_bytes"]),
        content_type=str(row["content_type"]),
        status=StoredDocumentStatus(str(row["status"])),
        metadata=_json_object(str(row["metadata_json"])),
        created_by=str(row["created_by"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def _run_from_row(row: sqlite3.Row) -> PilotRunRecord:
    return PilotRunRecord(
        run_id=str(row["run_id"]),
        deal_id=str(row["deal_id"]),
        status=str(row["status"]),
        review_policy=str(row["review_policy"]),
        state=_json_object(str(row["state_json"])),
        created_by=str(row["created_by"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _artifact_from_row(row: sqlite3.Row) -> PilotArtifactRecord:
    return PilotArtifactRecord(
        artifact_id=str(row["artifact_id"]),
        deal_id=str(row["deal_id"]),
        run_id=str(row["run_id"]),
        kind=ArtifactKind(str(row["kind"])),
        payload=_json_object(str(row["payload_json"])),
        schema_version=int(row["schema_version"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def _audit_from_row(row: sqlite3.Row) -> PilotAuditEvent:
    return PilotAuditEvent(
        event_id=str(row["event_id"]),
        deal_id=str(row["deal_id"]),
        actor_id=str(row["actor_id"]),
        action=str(row["action"]),
        object_type=str(row["object_type"]),
        object_id=str(row["object_id"]),
        detail=_json_object(str(row["detail_json"])),
        occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
    )
