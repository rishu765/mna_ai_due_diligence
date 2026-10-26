"""SQLite persistence adapter for the controlled pilot boundary."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import cast

from ma_due_diligence.security.models import (
    DealMembership,
    DealRole,
    PilotUser,
    SessionRecord,
    UserStatus,
)

from .models import (
    ArtifactKind,
    DealStatus,
    JsonObject,
    PilotArtifactRecord,
    PilotAuditEvent,
    PilotDealRecord,
    PilotReviewEvent,
    PilotReviewEventType,
    PilotRunRecord,
    StoredDocumentRecord,
    StoredDocumentStatus,
)

_SCHEMA_VERSION = 4

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

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS pilot_users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT,
    status TEXT NOT NULL,
    is_pilot_admin INTEGER NOT NULL CHECK (is_pilot_admin IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_deal_memberships (
    deal_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    assigned_by TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (deal_id, user_id),
    FOREIGN KEY (deal_id) REFERENCES pilot_deals(deal_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES pilot_users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pilot_memberships_user
ON pilot_deal_memberships(user_id, deal_id);

CREATE TABLE IF NOT EXISTS pilot_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_sha256 TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES pilot_users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pilot_sessions_user_expiry
ON pilot_sessions(user_id, expires_at);
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS pilot_document_chunks (
    chunk_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    chunk_text TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    UNIQUE (deal_id, document_id, chunk_index),
    FOREIGN KEY (deal_id) REFERENCES pilot_deals(deal_id) ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES pilot_documents(document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pilot_chunks_deal_document
ON pilot_document_chunks(deal_id, document_id, chunk_index);
"""

_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS pilot_review_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    deal_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_display_name TEXT NOT NULL,
    rationale TEXT NOT NULL,
    prior_state_json TEXT NOT NULL,
    resulting_state_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (deal_id, run_id) REFERENCES pilot_runs(deal_id, run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pilot_review_events_run_sequence
ON pilot_review_events(deal_id, run_id, sequence);

CREATE INDEX IF NOT EXISTS idx_pilot_review_events_subject
ON pilot_review_events(deal_id, run_id, subject_type, subject_id, sequence);

CREATE TRIGGER IF NOT EXISTS pilot_review_events_no_update
BEFORE UPDATE ON pilot_review_events
BEGIN
    SELECT RAISE(ABORT, 'review events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS pilot_review_events_no_delete
BEFORE DELETE ON pilot_review_events
BEGIN
    SELECT RAISE(ABORT, 'review events are immutable');
END;
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
                (1,),
            )
            connection.executescript(_SCHEMA_V2)
            connection.execute(
                "INSERT OR IGNORE INTO pilot_schema_migrations(version, applied_at) "
                "VALUES (?, datetime('now'))",
                (2,),
            )
            connection.executescript(_SCHEMA_V3)
            connection.execute(
                "INSERT OR IGNORE INTO pilot_schema_migrations(version, applied_at) "
                "VALUES (?, datetime('now'))",
                (3,),
            )
            connection.executescript(_SCHEMA_V4)
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

    def integrity_check(self) -> bool:
        """Return whether SQLite reports a structurally valid pilot database."""

        with self._connection() as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        return row is not None and str(row[0]) == "ok"

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

    def list_deals_for_user(self, user_id: str) -> tuple[PilotDealRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT deals.* FROM pilot_deals AS deals
                JOIN pilot_deal_memberships AS memberships
                  ON memberships.deal_id = deals.deal_id
                WHERE memberships.user_id = ?
                ORDER BY deals.updated_at DESC, deals.deal_id
                """,
                (user_id,),
            ).fetchall()
        return tuple(_deal_from_row(row) for row in rows)

    def list_deals(self) -> tuple[PilotDealRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM pilot_deals ORDER BY updated_at DESC, deal_id"
            ).fetchall()
        return tuple(_deal_from_row(row) for row in rows)

    def create_user(self, user: PilotUser) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pilot_users (
                        user_id, email, display_name, password_hash, status,
                        is_pilot_admin, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.user_id,
                        user.email,
                        user.display_name,
                        user.password_hash,
                        user.status.value,
                        int(user.is_pilot_admin),
                        user.created_at.isoformat(),
                        user.updated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(f"user or email already exists: {user.email}") from error

    def get_user(self, user_id: str) -> PilotUser | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM pilot_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return None if row is None else _user_from_row(row)

    def get_user_by_email(self, email: str) -> PilotUser | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM pilot_users WHERE email = ? COLLATE NOCASE",
                (email.casefold(),),
            ).fetchone()
        return None if row is None else _user_from_row(row)

    def update_user_password_hash(
        self,
        user_id: str,
        password_hash: str,
        updated_at: datetime,
    ) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE pilot_users
                SET password_hash = ?, updated_at = ?
                WHERE user_id = ? AND status = ?
                """,
                (password_hash, updated_at.isoformat(), user_id, UserStatus.ACTIVE.value),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"active user not found: {user_id}")

    def set_user_status(
        self,
        user_id: str,
        status: UserStatus,
        updated_at: datetime,
    ) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE pilot_users SET status = ?, updated_at = ? WHERE user_id = ?",
                (status.value, updated_at.isoformat(), user_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"user not found: {user_id}")
            if status is UserStatus.DEACTIVATED:
                connection.execute(
                    """
                    UPDATE pilot_sessions
                    SET revoked_at = COALESCE(revoked_at, ?)
                    WHERE user_id = ?
                    """,
                    (updated_at.isoformat(), user_id),
                )

    def assign_deal_membership(self, membership: DealMembership) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pilot_deal_memberships (
                        deal_id, user_id, role, assigned_by, assigned_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(deal_id, user_id) DO UPDATE SET
                        role = excluded.role,
                        assigned_by = excluded.assigned_by,
                        assigned_at = excluded.assigned_at
                    """,
                    (
                        membership.deal_id,
                        membership.user_id,
                        membership.role.value,
                        membership.assigned_by,
                        membership.assigned_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(
                f"membership references an unknown user or deal: {membership.deal_id}"
            ) from error

    def get_deal_membership(self, deal_id: str, user_id: str) -> DealMembership | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM pilot_deal_memberships
                WHERE deal_id = ? AND user_id = ?
                """,
                (deal_id, user_id),
            ).fetchone()
        return None if row is None else _membership_from_row(row)

    def create_session(self, session: SessionRecord) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pilot_sessions (
                        session_id, user_id, token_sha256, created_at,
                        expires_at, last_seen_at, revoked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.user_id,
                        session.token_sha256,
                        session.created_at.isoformat(),
                        session.expires_at.isoformat(),
                        session.last_seen_at.isoformat(),
                        None if session.revoked_at is None else session.revoked_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError("session could not be created") from error

    def get_session_by_token_hash(self, token_sha256: str) -> SessionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM pilot_sessions WHERE token_sha256 = ?",
                (token_sha256,),
            ).fetchone()
        return None if row is None else _session_from_row(row)

    def touch_session(self, session_id: str, seen_at: datetime) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE pilot_sessions SET last_seen_at = ?
                WHERE session_id = ? AND revoked_at IS NULL
                """,
                (seen_at.isoformat(), session_id),
            )

    def revoke_session(self, session_id: str, revoked_at: datetime) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE pilot_sessions
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE session_id = ?
                """,
                (revoked_at.isoformat(), session_id),
            )

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

    def update_document_processing(
        self,
        record: StoredDocumentRecord,
        event: PilotAuditEvent,
        chunks: tuple[JsonObject, ...] = (),
    ) -> None:
        """Atomically persist a processing result and its audit event."""

        if event.deal_id != record.deal_id:
            raise ValueError("document and audit event must belong to the same deal")
        if event.object_type != "document" or event.object_id != record.document_id:
            raise ValueError("document audit event must identify the processed document")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE pilot_documents
                SET status = ?, metadata_json = ?
                WHERE deal_id = ? AND document_id = ?
                """,
                (
                    record.status.value,
                    _json_dumps(record.metadata),
                    record.deal_id,
                    record.document_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"document not found in deal: {record.document_id}")
            connection.execute(
                "DELETE FROM pilot_document_chunks WHERE deal_id = ? AND document_id = ?",
                (record.deal_id, record.document_id),
            )
            for chunk in chunks:
                chunk_index = chunk.get("chunk_index")
                chunk_text = chunk.get("text")
                if not isinstance(chunk_index, int) or chunk_index < 0:
                    raise ValueError("persisted chunk index must be a nonnegative integer")
                if not isinstance(chunk_text, str) or not chunk_text.strip():
                    raise ValueError("persisted chunk text must not be blank")
                connection.execute(
                    """
                    INSERT INTO pilot_document_chunks (
                        chunk_id, deal_id, document_id, chunk_index, chunk_text, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{record.document_id}:chunk:{chunk_index}",
                        record.deal_id,
                        record.document_id,
                        chunk_index,
                        chunk_text,
                        _json_dumps(chunk),
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

    def list_document_chunks(
        self,
        deal_id: str,
        document_id: str,
    ) -> tuple[JsonObject, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT metadata_json
                FROM pilot_document_chunks
                WHERE deal_id = ? AND document_id = ?
                ORDER BY chunk_index
                """,
                (deal_id, document_id),
            ).fetchall()
        return tuple(_json_object(str(row["metadata_json"])) for row in rows)

    def save_run(self, record: PilotRunRecord) -> None:
        try:
            with self._connection() as connection:
                _save_run(connection, record)
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

    def get_latest_run(self, deal_id: str) -> PilotRunRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM pilot_runs
                WHERE deal_id = ?
                ORDER BY updated_at DESC, run_id DESC
                LIMIT 1
                """,
                (deal_id,),
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

    def add_artifact_with_audit(
        self,
        record: PilotArtifactRecord,
        event: PilotAuditEvent,
    ) -> None:
        """Atomically retain a derived artifact and its creation event."""

        if event.deal_id != record.deal_id:
            raise ValueError("artifact and audit event must belong to the same deal")
        if event.object_type != "artifact" or event.object_id != record.artifact_id:
            raise ValueError("artifact audit event must identify the stored artifact")
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
                _append_audit_event(connection, event)
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

    def append_review_events(self, events: tuple[PilotReviewEvent, ...]) -> None:
        if not events:
            return
        try:
            with self._connection() as connection:
                _append_review_events(connection, events)
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError("review events could not be appended") from error

    def save_run_with_review_events(
        self,
        record: PilotRunRecord,
        events: tuple[PilotReviewEvent, ...],
        audit_event: PilotAuditEvent,
    ) -> None:
        if any(
            event.deal_id != record.deal_id or event.run_id != record.run_id for event in events
        ):
            raise ValueError("review events must belong to the saved run")
        if audit_event.deal_id != record.deal_id or audit_event.object_id != record.run_id:
            raise ValueError("review audit event must belong to the saved run")
        try:
            with self._connection() as connection:
                _save_run(connection, record)
                _append_review_events(connection, events)
                _append_audit_event(connection, audit_event)
        except sqlite3.IntegrityError as error:
            raise PersistenceConflictError(
                f"review result cannot be stored for run {record.run_id}"
            ) from error

    def list_review_events(
        self,
        deal_id: str,
        run_id: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> tuple[PilotReviewEvent, ...]:
        filters = ["deal_id = ?", "run_id = ?"]
        parameters: list[str] = [deal_id, run_id]
        if subject_type is not None:
            filters.append("subject_type = ?")
            parameters.append(subject_type)
        if subject_id is not None:
            filters.append("subject_id = ?")
            parameters.append(subject_id)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM pilot_review_events WHERE {' AND '.join(filters)} ORDER BY sequence",
                tuple(parameters),
            ).fetchall()
        return tuple(_review_event_from_row(row) for row in rows)

    def append_audit_event(self, event: PilotAuditEvent) -> None:
        try:
            with self._connection() as connection:
                _append_audit_event(connection, event)
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


def _save_run(connection: sqlite3.Connection, record: PilotRunRecord) -> None:
    existing = connection.execute(
        "SELECT deal_id, created_at FROM pilot_runs WHERE run_id = ?",
        (record.run_id,),
    ).fetchone()
    if existing is not None and str(existing["deal_id"]) != record.deal_id:
        raise PersistenceConflictError(f"run_id {record.run_id} belongs to another deal")
    created_at = record.created_at.isoformat() if existing is None else str(existing["created_at"])
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


def _append_review_events(
    connection: sqlite3.Connection,
    events: tuple[PilotReviewEvent, ...],
) -> None:
    for event in events:
        connection.execute(
            """
            INSERT INTO pilot_review_events (
                event_id, deal_id, run_id, subject_type, subject_id,
                event_type, actor_id, actor_display_name, rationale,
                prior_state_json, resulting_state_json, metadata_json,
                occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.deal_id,
                event.run_id,
                event.subject_type,
                event.subject_id,
                event.event_type.value,
                event.actor_id,
                event.actor_display_name,
                event.rationale,
                _json_dumps(event.prior_state),
                _json_dumps(event.resulting_state),
                _json_dumps(event.metadata),
                event.occurred_at.isoformat(),
            ),
        )


def _append_audit_event(connection: sqlite3.Connection, event: PilotAuditEvent) -> None:
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


def _review_event_from_row(row: sqlite3.Row) -> PilotReviewEvent:
    return PilotReviewEvent(
        event_id=str(row["event_id"]),
        deal_id=str(row["deal_id"]),
        run_id=str(row["run_id"]),
        subject_type=str(row["subject_type"]),
        subject_id=str(row["subject_id"]),
        event_type=PilotReviewEventType(str(row["event_type"])),
        actor_id=str(row["actor_id"]),
        actor_display_name=str(row["actor_display_name"]),
        rationale=str(row["rationale"]),
        prior_state=_json_object(str(row["prior_state_json"])),
        resulting_state=_json_object(str(row["resulting_state_json"])),
        metadata=_json_object(str(row["metadata_json"])),
        occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
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


def _user_from_row(row: sqlite3.Row) -> PilotUser:
    return PilotUser(
        user_id=str(row["user_id"]),
        email=str(row["email"]),
        display_name=str(row["display_name"]),
        password_hash=None if row["password_hash"] is None else str(row["password_hash"]),
        status=UserStatus(str(row["status"])),
        is_pilot_admin=bool(row["is_pilot_admin"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _membership_from_row(row: sqlite3.Row) -> DealMembership:
    return DealMembership(
        deal_id=str(row["deal_id"]),
        user_id=str(row["user_id"]),
        role=DealRole(str(row["role"])),
        assigned_by=str(row["assigned_by"]),
        assigned_at=datetime.fromisoformat(str(row["assigned_at"])),
    )


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=str(row["session_id"]),
        user_id=str(row["user_id"]),
        token_sha256=str(row["token_sha256"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        expires_at=datetime.fromisoformat(str(row["expires_at"])),
        last_seen_at=datetime.fromisoformat(str(row["last_seen_at"])),
        revoked_at=(
            None if row["revoked_at"] is None else datetime.fromisoformat(str(row["revoked_at"]))
        ),
    )
