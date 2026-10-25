"""Opaque-session authentication and backend-enforced deal authorization."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ma_due_diligence.persistence.database import PilotDatabase
from ma_due_diligence.persistence.models import PilotDealRecord

from .errors import AuthenticationError, AuthorizationError
from .models import (
    AccessSession,
    AuthPrincipal,
    DealMembership,
    DealRole,
    Permission,
    PilotUser,
    SessionRecord,
    UserStatus,
)
from .passwords import PasswordManager

_ANALYST_PERMISSIONS = frozenset(
    {
        Permission.DEAL_READ,
        Permission.DOCUMENT_WRITE,
        Permission.ANALYSIS_RUN,
        Permission.FINDING_DRAFT,
    }
)
_REVIEWER_PERMISSIONS = _ANALYST_PERMISSIONS | {
    Permission.REVIEW_DECIDE,
    Permission.REPORT_RELEASE,
}


class PilotAuthService:
    def __init__(
        self,
        database: PilotDatabase,
        *,
        password_manager: PasswordManager | None = None,
        session_duration: timedelta = timedelta(hours=8),
    ) -> None:
        if session_duration <= timedelta(0):
            raise ValueError("session_duration must be positive")
        self._database = database
        self._passwords = password_manager or PasswordManager()
        self._session_duration = session_duration
        self._dummy_hash = self._passwords.hash("dummy-password-not-used")

    def provision_user(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        is_pilot_admin: bool = False,
        user_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> PilotUser:
        timestamp = occurred_at or datetime.now(UTC)
        user = PilotUser(
            user_id=user_id or f"user-{uuid4().hex}",
            email=email,
            display_name=display_name,
            password_hash=self._passwords.hash(password),
            status=UserStatus.ACTIVE,
            is_pilot_admin=is_pilot_admin,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._database.create_user(user)
        return user

    def login(
        self,
        *,
        email: str,
        password: str,
        now: datetime | None = None,
    ) -> AccessSession:
        timestamp = now or datetime.now(UTC)
        user = self._database.get_user_by_email(email)
        candidate_hash = (
            self._dummy_hash if user is None or user.password_hash is None else user.password_hash
        )
        password_valid = self._passwords.verify(candidate_hash, password)
        if user is None or user.status is not UserStatus.ACTIVE or not password_valid:
            raise AuthenticationError("invalid email or password")

        if self._passwords.needs_rehash(candidate_hash):
            refreshed_hash = self._passwords.hash(password)
            self._database.update_user_password_hash(user.user_id, refreshed_hash, timestamp)
            user = replace(
                user,
                password_hash=refreshed_hash,
                updated_at=timestamp,
            )

        raw_token = f"madd_{secrets.token_urlsafe(32)}"
        session = SessionRecord(
            session_id=f"session-{uuid4().hex}",
            user_id=user.user_id,
            token_sha256=_token_hash(raw_token),
            created_at=timestamp,
            expires_at=timestamp + self._session_duration,
            last_seen_at=timestamp,
        )
        self._database.create_session(session)
        return AccessSession(raw_token, session.expires_at, _principal(user))

    def authenticate(self, token: str, *, now: datetime | None = None) -> AuthPrincipal:
        timestamp = now or datetime.now(UTC)
        if not token.startswith("madd_") or len(token) < 32:
            raise AuthenticationError("invalid or expired session")
        session = self._database.get_session_by_token_hash(_token_hash(token))
        if session is None or session.revoked_at is not None or session.expires_at <= timestamp:
            if session is not None and session.revoked_at is None:
                self._database.revoke_session(session.session_id, timestamp)
            raise AuthenticationError("invalid or expired session")
        user = self._database.get_user(session.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise AuthenticationError("invalid or expired session")
        if timestamp - session.last_seen_at >= timedelta(minutes=5):
            self._database.touch_session(session.session_id, timestamp)
        return _principal(user)

    def logout(self, token: str, *, now: datetime | None = None) -> None:
        session = self._database.get_session_by_token_hash(_token_hash(token))
        if session is not None:
            self._database.revoke_session(session.session_id, now or datetime.now(UTC))

    def assign_deal_role(
        self,
        *,
        actor: AuthPrincipal,
        deal_id: str,
        user_id: str,
        role: DealRole,
        occurred_at: datetime | None = None,
    ) -> DealMembership:
        if not actor.is_pilot_admin:
            raise AuthorizationError("pilot administrator permission is required")
        if self._database.get_deal(deal_id) is None:
            raise KeyError(f"deal not found: {deal_id}")
        if self._database.get_user(user_id) is None:
            raise KeyError(f"user not found: {user_id}")
        membership = DealMembership(
            deal_id=deal_id,
            user_id=user_id,
            role=role,
            assigned_by=actor.user_id,
            assigned_at=occurred_at or datetime.now(UTC),
        )
        self._database.assign_deal_membership(membership)
        return membership

    def deactivate_user(
        self,
        *,
        actor: AuthPrincipal,
        user_id: str,
        occurred_at: datetime | None = None,
    ) -> None:
        if not actor.is_pilot_admin:
            raise AuthorizationError("pilot administrator permission is required")
        if actor.user_id == user_id:
            raise AuthorizationError("pilot administrators cannot deactivate their own account")
        self._database.set_user_status(
            user_id,
            UserStatus.DEACTIVATED,
            occurred_at or datetime.now(UTC),
        )

    def require_permission(
        self,
        principal: AuthPrincipal,
        deal_id: str,
        permission: Permission,
    ) -> DealMembership | None:
        if principal.is_pilot_admin:
            return None
        membership = self._database.get_deal_membership(deal_id, principal.user_id)
        allowed = frozenset() if membership is None else _permissions_for(membership.role)
        if permission not in allowed:
            raise AuthorizationError("deal access denied")
        return membership

    def accessible_deals(self, principal: AuthPrincipal) -> tuple[PilotDealRecord, ...]:
        if principal.is_pilot_admin:
            return self._database.list_deals()
        return self._database.list_deals_for_user(principal.user_id)


def _permissions_for(role: DealRole) -> frozenset[Permission]:
    if role is DealRole.ANALYST:
        return _ANALYST_PERMISSIONS
    if role is DealRole.REVIEWER:
        return frozenset(_REVIEWER_PERMISSIONS)
    return frozenset()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _principal(user: PilotUser) -> AuthPrincipal:
    return AuthPrincipal(user.user_id, user.email, user.display_name, user.is_pilot_admin)
