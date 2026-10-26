from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ma_due_diligence.api.pilot_app import PilotApiContext, create_pilot_app
from ma_due_diligence.persistence import (
    PilotDatabase,
    PilotDealRecord,
    create_rotating_pilot_backup,
    verify_pilot_backup,
)
from ma_due_diligence.pilot_api_cli import _port_from_environment
from ma_due_diligence.security import PilotHttpSecurityPolicy
from ma_due_diligence.security.service import PilotAuthService

_NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def _database(path: Path) -> PilotDatabase:
    database = PilotDatabase(path)
    database.initialize()
    database.create_deal(
        PilotDealRecord(
            deal_id="deal-a",
            name="Project Northstar",
            target_name="SecureTech",
            buyer_name="Northstar Holdings",
            transaction_type="acquisition",
            reporting_currency="GBP",
            as_of_date=date(2026, 6, 30),
            workstreams=("financial",),
            created_by="user-admin",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    return database


def test_https_boundary_exposes_release_and_hsts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path / "pilot.sqlite3")
    monkeypatch.setenv("MADD_ENVIRONMENT", "pilot")
    monkeypatch.setenv("MADD_RELEASE_SHA", "abc123")
    policy = PilotHttpSecurityPolicy(allowed_hosts=("pilot.example",))
    client = TestClient(
        create_pilot_app(
            PilotApiContext(database, PilotAuthService(database), http_security=policy)
        ),
        base_url="https://pilot.example",
    )

    response = client.get("/version")

    assert response.json() == {"environment": "pilot", "release": "abc123"}
    assert response.headers["strict-transport-security"] == ("max-age=31536000; includeSubDomains")


def test_runtime_port_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MADD_PORT", "18000")
    assert _port_from_environment() == 18000

    for invalid in ("not-a-port", "0", "65536"):
        monkeypatch.setenv("MADD_PORT", invalid)
        with pytest.raises(RuntimeError, match="MADD_PORT"):
            _port_from_environment()


def test_scheduled_backups_are_verified_rotated_and_do_not_delete_sentinels(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pilot-data"
    _database(source / "pilot.sqlite3")
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    sentinel = backup_directory / "operator-note.txt"
    sentinel.write_text("retain me", encoding="utf-8")
    key = bytes(range(32))

    created = []
    for offset in range(3):
        archive, _ = create_rotating_pilot_backup(
            source,
            backup_directory,
            key,
            retain=2,
            now=_NOW + timedelta(seconds=offset),
        )
        created.append(archive)

    retained = sorted(backup_directory.glob("*.madd-backup"))
    assert len(retained) == 2
    assert created[0] not in retained
    assert sentinel.read_text(encoding="utf-8") == "retain me"
    assert all(verify_pilot_backup(path, key).files for path in retained)


def test_deployment_manifests_preserve_isolation_and_persistent_volumes() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert "USER madd" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "internal: true" in compose
    assert "pilot_data:/data-root" in compose
    assert '"80:80"' in compose and '"443:443"' in compose
    assert "8000:8000" not in compose
