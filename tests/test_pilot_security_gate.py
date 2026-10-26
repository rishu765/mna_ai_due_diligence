from __future__ import annotations

import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ma_due_diligence.api.pilot_app import PilotApiContext, create_pilot_app
from ma_due_diligence.persistence import (
    BackupValidationError,
    PilotDatabase,
    PilotDealRecord,
    create_pilot_backup,
    restore_pilot_backup,
    verify_pilot_backup,
)
from ma_due_diligence.security import PilotHttpSecurityPolicy
from ma_due_diligence.security.service import PilotAuthService

_NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def _secured_client(tmp_path: Path, *, attempt_limit: int = 5) -> TestClient:
    database = PilotDatabase(tmp_path / "pilot.sqlite3")
    database.initialize()
    auth = PilotAuthService(database)
    auth.provision_user(
        email="admin@example.com",
        display_name="Pilot Admin",
        password="admin password long enough",
        is_pilot_admin=True,
        user_id="user-admin",
        occurred_at=_NOW,
    )
    policy = PilotHttpSecurityPolicy(
        login_attempt_limit=attempt_limit,
        login_window_seconds=60,
        login_block_seconds=120,
    )
    return TestClient(create_pilot_app(PilotApiContext(database, auth, http_security=policy)))


def test_http_security_headers_host_allowlist_and_readiness(tmp_path: Path) -> None:
    client = _secured_client(tmp_path)

    health = client.get("/health")
    ready = client.get("/ready")
    login = client.post(
        "/pilot/auth/login",
        json={"email": "admin@example.com", "password": "admin password long enough"},
    )
    bad_host = client.get("/health", headers={"Host": "untrusted.example"})

    assert health.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok"}
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    assert login.headers["cache-control"] == "no-store"
    assert bad_host.status_code == 400


def test_repeated_login_failures_are_temporarily_blocked(tmp_path: Path) -> None:
    client = _secured_client(tmp_path, attempt_limit=2)
    invalid = {"email": "admin@example.com", "password": "incorrect password"}

    first = client.post("/pilot/auth/login", json=invalid)
    second = client.post("/pilot/auth/login", json=invalid)
    blocked = client.post(
        "/pilot/auth/login",
        json={"email": "admin@example.com", "password": "admin password long enough"},
    )

    assert first.status_code == 401
    assert second.status_code == 401
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    assert blocked.json()["detail"] == "login temporarily unavailable"


def test_encrypted_backup_verifies_and_restores_complete_pilot_state(tmp_path: Path) -> None:
    source = tmp_path / "pilot-data"
    database = PilotDatabase(source / "pilot.sqlite3")
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
    checkpoint = sqlite3.connect(source / "checkpoints.sqlite3")
    checkpoint.execute("CREATE TABLE checkpoint_marker(value TEXT NOT NULL)")
    checkpoint.execute("INSERT INTO checkpoint_marker VALUES ('recoverable')")
    checkpoint.commit()
    checkpoint.close()
    blob = source / "documents" / "0123456789abcdef" / ("a" * 32 + ".madd")
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"encrypted-document-envelope")
    key = bytes(range(32))
    archive = tmp_path / "pilot-backup.madd-backup"

    created = create_pilot_backup(source, archive, key)
    verified = verify_pilot_backup(archive, key)
    restored_directory = tmp_path / "restored-pilot-data"
    restored = restore_pilot_backup(archive, restored_directory, key)

    assert b"SecureTech" not in archive.read_bytes()
    assert created == verified == restored
    restored_database = PilotDatabase(restored_directory / "pilot.sqlite3")
    assert restored_database.integrity_check()
    assert restored_database.get_deal("deal-a") is not None
    assert (restored_directory / blob.relative_to(source)).read_bytes() == blob.read_bytes()
    with sqlite3.connect(restored_directory / "checkpoints.sqlite3") as connection:
        assert connection.execute("SELECT value FROM checkpoint_marker").fetchone() == (
            "recoverable",
        )

    with pytest.raises(BackupValidationError, match="authentication failed"):
        verify_pilot_backup(archive, bytes(reversed(range(32))))
    with pytest.raises(FileExistsError, match="already exists"):
        create_pilot_backup(source, archive, key)
    with pytest.raises(FileExistsError, match="must not exist"):
        restore_pilot_backup(archive, restored_directory, key)


def test_authenticated_read_path_has_bounded_pilot_smoke_performance(tmp_path: Path) -> None:
    client = _secured_client(tmp_path)
    token = client.post(
        "/pilot/auth/login",
        json={"email": "admin@example.com", "password": "admin password long enough"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    started = time.perf_counter()
    responses = [client.get("/pilot/deals", headers=headers) for _ in range(100)]
    elapsed = time.perf_counter() - started

    assert all(response.status_code == 200 for response in responses)
    assert elapsed < 10.0
