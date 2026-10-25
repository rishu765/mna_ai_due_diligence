from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ma_due_diligence.persistence import PilotDatabase, PilotDealRecord
from ma_due_diligence.security import (
    AuthenticationError,
    AuthorizationError,
    DealRole,
    Permission,
)
from ma_due_diligence.security.service import PilotAuthService

_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _deal(deal_id: str, name: str) -> PilotDealRecord:
    return PilotDealRecord(
        deal_id=deal_id,
        name=name,
        target_name=f"{name} Target",
        buyer_name=None,
        transaction_type="acquisition",
        reporting_currency="GBP",
        as_of_date=date(2026, 6, 30),
        workstreams=("financial", "commercial"),
        created_by="admin",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _setup(tmp_path: Path) -> tuple[PilotDatabase, PilotAuthService]:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    database.create_deal(_deal("deal-a", "Project Alpha"))
    database.create_deal(_deal("deal-b", "Project Beta"))
    return database, PilotAuthService(database)


def test_login_stores_argon2_hash_and_only_session_token_hash(tmp_path: Path) -> None:
    database, auth = _setup(tmp_path)
    user = auth.provision_user(
        email="Analyst@Example.com",
        display_name="A. Analyst",
        password="correct horse battery staple",
        user_id="user-analyst",
        occurred_at=_NOW,
    )

    session = auth.login(
        email="analyst@example.com",
        password="correct horse battery staple",
        now=_NOW,
    )

    assert user.email == "analyst@example.com"
    assert user.password_hash is not None
    assert user.password_hash.startswith("$argon2id$")
    assert "correct horse battery staple" not in user.password_hash
    assert session.token.startswith("madd_")
    assert auth.authenticate(session.token, now=_NOW + timedelta(minutes=1)).user_id == user.user_id

    with sqlite3.connect(database.path) as connection:
        stored_hash = str(
            connection.execute("SELECT token_sha256 FROM pilot_sessions").fetchone()[0]
        )
        database_text = " ".join(
            str(value)
            for row in connection.execute("SELECT * FROM pilot_sessions").fetchall()
            for value in row
        )
    assert len(stored_hash) == 64
    assert session.token not in database_text


def test_login_uses_generic_error_for_unknown_user_and_wrong_password(tmp_path: Path) -> None:
    _, auth = _setup(tmp_path)
    auth.provision_user(
        email="analyst@example.com",
        display_name="A. Analyst",
        password="correct horse battery staple",
        occurred_at=_NOW,
    )

    with pytest.raises(AuthenticationError, match="invalid email or password"):
        auth.login(email="missing@example.com", password="wrong password value", now=_NOW)
    with pytest.raises(AuthenticationError, match="invalid email or password"):
        auth.login(email="analyst@example.com", password="wrong password value", now=_NOW)


def test_expired_and_revoked_sessions_are_rejected(tmp_path: Path) -> None:
    database, auth = _setup(tmp_path)
    auth.provision_user(
        email="analyst@example.com",
        display_name="A. Analyst",
        password="correct horse battery staple",
        occurred_at=_NOW,
    )
    session = auth.login(
        email="analyst@example.com",
        password="correct horse battery staple",
        now=_NOW,
    )

    auth.logout(session.token, now=_NOW + timedelta(minutes=1))
    with pytest.raises(AuthenticationError, match="invalid or expired session"):
        auth.authenticate(session.token, now=_NOW + timedelta(minutes=2))

    short_auth = PilotAuthService(database, session_duration=timedelta(minutes=1))
    expiring = short_auth.login(
        email="analyst@example.com",
        password="correct horse battery staple",
        now=_NOW,
    )
    with pytest.raises(AuthenticationError, match="invalid or expired session"):
        short_auth.authenticate(expiring.token, now=_NOW + timedelta(minutes=2))


def test_deal_roles_enforce_isolation_and_separation_of_duties(tmp_path: Path) -> None:
    _, auth = _setup(tmp_path)
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
    reviewer = auth.provision_user(
        email="reviewer@example.com",
        display_name="Deal Reviewer",
        password="reviewer password long enough",
        user_id="user-reviewer",
        occurred_at=_NOW,
    )
    admin_principal = auth.login(
        email=admin.email,
        password="admin password long enough",
        now=_NOW,
    ).principal
    analyst_principal = auth.login(
        email=analyst.email,
        password="analyst password long enough",
        now=_NOW,
    ).principal
    reviewer_principal = auth.login(
        email=reviewer.email,
        password="reviewer password long enough",
        now=_NOW,
    ).principal
    auth.assign_deal_role(
        actor=admin_principal,
        deal_id="deal-a",
        user_id=analyst.user_id,
        role=DealRole.ANALYST,
        occurred_at=_NOW,
    )
    auth.assign_deal_role(
        actor=admin_principal,
        deal_id="deal-a",
        user_id=reviewer.user_id,
        role=DealRole.REVIEWER,
        occurred_at=_NOW,
    )

    assert [deal.deal_id for deal in auth.accessible_deals(analyst_principal)] == ["deal-a"]
    assert {deal.deal_id for deal in auth.accessible_deals(admin_principal)} == {
        "deal-a",
        "deal-b",
    }
    auth.require_permission(analyst_principal, "deal-a", Permission.DOCUMENT_WRITE)
    auth.require_permission(reviewer_principal, "deal-a", Permission.REPORT_RELEASE)
    with pytest.raises(AuthorizationError, match="deal access denied"):
        auth.require_permission(analyst_principal, "deal-b", Permission.DEAL_READ)
    with pytest.raises(AuthorizationError, match="deal access denied"):
        auth.require_permission(analyst_principal, "deal-a", Permission.REVIEW_DECIDE)
    with pytest.raises(AuthorizationError, match="administrator"):
        auth.assign_deal_role(
            actor=analyst_principal,
            deal_id="deal-b",
            user_id=analyst.user_id,
            role=DealRole.ANALYST,
            occurred_at=_NOW,
        )


def test_admin_deactivation_revokes_existing_sessions(tmp_path: Path) -> None:
    _, auth = _setup(tmp_path)
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
    admin_principal = auth.login(
        email=admin.email,
        password="admin password long enough",
        now=_NOW,
    ).principal
    analyst_session = auth.login(
        email=analyst.email,
        password="analyst password long enough",
        now=_NOW,
    )

    auth.deactivate_user(actor=admin_principal, user_id=analyst.user_id, occurred_at=_NOW)

    with pytest.raises(AuthenticationError, match="invalid or expired session"):
        auth.authenticate(analyst_session.token, now=_NOW + timedelta(minutes=1))
    with pytest.raises(AuthorizationError, match="own account"):
        auth.deactivate_user(actor=admin_principal, user_id=admin.user_id, occurred_at=_NOW)
