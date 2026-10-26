"""Typed records stored by the pilot persistence boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TypeAlias

JsonObject: TypeAlias = dict[str, object]

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _required(value: str, name: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _optional(value: str | None, name: str) -> str | None:
    return None if value is None else _required(value, name)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


class DealStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETE = "complete"
    ARCHIVED = "archived"


class StoredDocumentStatus(StrEnum):
    STORED = "stored"
    PROCESSING = "processing"
    INDEXED = "indexed"
    PARTIAL = "partial"
    FAILED = "failed"
    DELETED = "deleted"


class ArtifactKind(StrEnum):
    FINDING = "finding"
    CALCULATION = "calculation"
    CONFLICT = "conflict"
    INFORMATION_REQUEST = "information_request"
    REVIEW_ACTION = "review_action"
    REPORT = "report"
    WORKFLOW_SNAPSHOT = "workflow_snapshot"


class PilotReviewEventType(StrEnum):
    ASSIGNED = "assigned"
    COMMENTED = "commented"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    SEVERITY_CHANGED = "severity_changed"
    INFORMATION_REQUESTED = "information_requested"
    CONFLICT_RESOLVED = "conflict_resolved"


@dataclass(frozen=True, slots=True)
class PilotDealRecord:
    deal_id: str
    name: str
    target_name: str
    buyer_name: str | None
    transaction_type: str
    reporting_currency: str
    as_of_date: date
    materiality_threshold: str | None = None
    unit: str = "units"
    workstreams: tuple[str, ...] = ()
    notes: str | None = None
    status: DealStatus = DealStatus.DRAFT
    created_by: str = "system"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("deal_id", "name", "target_name", "transaction_type", "unit", "created_by"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "buyer_name", _optional(self.buyer_name, "buyer_name"))
        object.__setattr__(
            self,
            "materiality_threshold",
            _optional(self.materiality_threshold, "materiality_threshold"),
        )
        object.__setattr__(self, "notes", _optional(self.notes, "notes"))
        currency = _required(self.reporting_currency, "reporting_currency").upper()
        if not _CURRENCY_PATTERN.fullmatch(currency):
            raise ValueError("reporting_currency must be a three-letter code")
        object.__setattr__(self, "reporting_currency", currency)
        normalized_workstreams = tuple(_required(item, "workstream") for item in self.workstreams)
        if len(set(normalized_workstreams)) != len(normalized_workstreams):
            raise ValueError("workstreams must not contain duplicates")
        object.__setattr__(self, "workstreams", normalized_workstreams)
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")


@dataclass(frozen=True, slots=True)
class StoredDocumentRecord:
    document_id: str
    deal_id: str
    original_filename: str
    storage_key: str
    plaintext_sha256: str
    plaintext_size_bytes: int
    encrypted_size_bytes: int
    content_type: str
    status: StoredDocumentStatus = StoredDocumentStatus.STORED
    metadata: JsonObject = field(default_factory=dict)
    created_by: str = "system"
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in (
            "document_id",
            "deal_id",
            "original_filename",
            "storage_key",
            "content_type",
            "created_by",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        checksum = self.plaintext_sha256.casefold()
        if not _SHA256_PATTERN.fullmatch(checksum):
            raise ValueError("plaintext_sha256 must be a lowercase SHA-256 hex digest")
        object.__setattr__(self, "plaintext_sha256", checksum)
        if self.plaintext_size_bytes < 0 or self.encrypted_size_bytes <= 0:
            raise ValueError("document sizes are invalid")
        _aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class PilotRunRecord:
    run_id: str
    deal_id: str
    status: str
    review_policy: str
    state: JsonObject = field(default_factory=dict)
    created_by: str = "system"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("run_id", "deal_id", "status", "review_policy", "created_by"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")


@dataclass(frozen=True, slots=True)
class PilotArtifactRecord:
    artifact_id: str
    deal_id: str
    run_id: str
    kind: ArtifactKind
    payload: JsonObject
    schema_version: int = 1
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("artifact_id", "deal_id", "run_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        _aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class PilotReviewEvent:
    event_id: str
    deal_id: str
    run_id: str
    subject_type: str
    subject_id: str
    event_type: PilotReviewEventType
    actor_id: str
    actor_display_name: str
    rationale: str
    prior_state: JsonObject = field(default_factory=dict)
    resulting_state: JsonObject = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "deal_id",
            "run_id",
            "subject_type",
            "subject_id",
            "actor_id",
            "actor_display_name",
            "rationale",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.subject_type not in {"run", "finding", "conflict"}:
            raise ValueError("review event subject_type must be run, finding, or conflict")
        _aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class PilotAuditEvent:
    event_id: str
    deal_id: str
    actor_id: str
    action: str
    object_type: str
    object_id: str
    detail: JsonObject = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("event_id", "deal_id", "actor_id", "action", "object_type", "object_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        _aware(self.occurred_at, "occurred_at")
