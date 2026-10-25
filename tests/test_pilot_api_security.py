from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ma_due_diligence.api.pilot_app import PilotApiContext, create_pilot_app
from ma_due_diligence.persistence import PilotDatabase, PilotDealRecord
from ma_due_diligence.security import DealRole
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
        workstreams=("financial",),
        created_by="user-admin",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _client(tmp_path: Path) -> tuple[TestClient, PilotAuthService]:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    database.create_deal(_deal("deal-a", "Project Alpha"))
    database.create_deal(_deal("deal-b", "Project Beta"))
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
    return TestClient(create_pilot_app(PilotApiContext(database, auth))), auth


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/pilot/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_protected_endpoints_require_valid_bearer_session(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    missing = client.get("/pilot/me")
    malformed = client.get("/pilot/me", headers={"Authorization": "Basic value"})

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert malformed.status_code == 401


def test_api_hides_unassigned_deals_even_when_id_is_known(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    token = _login(client, "analyst@example.com", "analyst password long enough")

    visible = client.get("/pilot/deals", headers=_headers(token))
    assigned = client.get("/pilot/deals/deal-a", headers=_headers(token))
    unassigned = client.get("/pilot/deals/deal-b", headers=_headers(token))

    assert visible.status_code == 200
    assert [item["deal_id"] for item in visible.json()] == ["deal-a"]
    assert assigned.status_code == 200
    assert unassigned.status_code == 404
    assert unassigned.json()["detail"] == "deal not found"


def test_non_admin_cannot_create_deals_or_assign_memberships(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    token = _login(client, "analyst@example.com", "analyst password long enough")
    deal_payload = {
        "name": "Project Cedar",
        "target_name": "Cedar Target",
        "transaction_type": "acquisition",
        "reporting_currency": "GBP",
        "as_of_date": "2026-06-30",
        "workstreams": ["financial"],
    }

    create_response = client.post(
        "/pilot/deals",
        headers=_headers(token),
        json=deal_payload,
    )
    membership_response = client.put(
        "/pilot/deals/deal-b/memberships",
        headers=_headers(token),
        json={"user_id": "user-analyst", "role": "analyst"},
    )

    assert create_response.status_code == 403
    assert membership_response.status_code == 403


def test_admin_can_create_deal_and_assign_reviewer(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    admin_token = _login(client, "admin@example.com", "admin password long enough")
    reviewer_token = _login(client, "reviewer@example.com", "reviewer password long enough")
    create_response = client.post(
        "/pilot/deals",
        headers=_headers(admin_token),
        json={
            "name": "Project Cedar",
            "target_name": "Cedar Target",
            "transaction_type": "acquisition",
            "reporting_currency": "GBP",
            "as_of_date": "2026-06-30",
            "workstreams": ["financial", "commercial"],
        },
    )
    assert create_response.status_code == 201
    deal_id = str(create_response.json()["deal_id"])

    assign_response = client.put(
        f"/pilot/deals/{deal_id}/memberships",
        headers=_headers(admin_token),
        json={"user_id": "user-reviewer", "role": "reviewer"},
    )
    reviewer_access = client.get(f"/pilot/deals/{deal_id}", headers=_headers(reviewer_token))

    assert assign_response.status_code == 200
    assert reviewer_access.status_code == 200


def test_logout_revokes_the_current_session(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    token = _login(client, "analyst@example.com", "analyst password long enough")

    logout = client.post("/pilot/auth/logout", headers=_headers(token))
    after_logout = client.get("/pilot/me", headers=_headers(token))

    assert logout.status_code == 204
    assert after_logout.status_code == 401
