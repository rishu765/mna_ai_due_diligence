"""Authentication, session, and deal-authorization records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def utc_now() -> datetime:
    return datetime.now(UTC)


def _required(value: str, name: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


class UserStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


class DealRole(StrEnum):
    ANALYST = "analyst"
    REVIEWER = "reviewer"


class Permission(StrEnum):
    DEAL_READ = "deal_read"
    DOCUMENT_WRITE = "document_write"
    ANALYSIS_RUN = "analysis_run"
    FINDING_DRAFT = "finding_draft"
    REVIEW_DECIDE = "review_decide"
    REPORT_RELEASE = "report_release"
    DEAL_ADMIN = "deal_admin"


@dataclass(frozen=True, slots=True)
class PilotUser:
    user_id: str
    email: str
    display_name: str
    password_hash: str | None
    status: UserStatus
    is_pilot_admin: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _required(self.user_id, "user_id"))
        email = _required(self.email, "email").casefold()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("email is invalid")
        object.__setattr__(self, "email", email)
        object.__setattr__(self, "display_name", _required(self.display_name, "display_name"))
        if self.password_hash is not None:
            object.__setattr__(
                self,
                "password_hash",
                _required(self.password_hash, "password_hash"),
            )
        if self.status is UserStatus.ACTIVE and self.password_hash is None:
            raise ValueError("active users require a password hash")
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")


@dataclass(frozen=True, slots=True)
class DealMembership:
    deal_id: str
    user_id: str
    role: DealRole
    assigned_by: str
    assigned_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("deal_id", "user_id", "assigned_by"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        _aware(self.assigned_at, "assigned_at")


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    user_id: str
    token_sha256: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("session_id", "user_id", "token_sha256"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if len(self.token_sha256) != 64:
            raise ValueError("token_sha256 must contain 64 hexadecimal characters")
        for value, name in (
            (self.created_at, "created_at"),
            (self.expires_at, "expires_at"),
            (self.last_seen_at, "last_seen_at"),
        ):
            _aware(value, name)
        if self.revoked_at is not None:
            _aware(self.revoked_at, "revoked_at")
        if self.expires_at <= self.created_at:
            raise ValueError("session expiry must follow creation")


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    user_id: str
    email: str
    display_name: str
    is_pilot_admin: bool


@dataclass(frozen=True, slots=True)
class AccessSession:
    token: str
    expires_at: datetime
    principal: AuthPrincipal
