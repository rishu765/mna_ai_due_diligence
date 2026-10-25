"""Configured local runtime for the authenticated pilot application."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from ma_due_diligence.persistence import (
    PersistentWorkflowRuntime,
    PilotDatabase,
    document_key_from_environment,
)
from ma_due_diligence.security.service import PilotAuthService

from .pilot_app import PilotApiContext, create_pilot_app
from .pilot_runs import PilotRunService


class PilotApplicationRuntime:
    def __init__(self, data_directory: Path | None = None) -> None:
        self.data_directory = (
            data_directory or Path(os.environ.get("MADD_PILOT_DATA_DIR", "pilot-data"))
        ).resolve()
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.database = PilotDatabase(self.data_directory / "pilot.sqlite3")
        self.database.initialize()
        self.auth = PilotAuthService(self.database)
        checkpoint_key = document_key_from_environment("MADD_CHECKPOINT_KEY")
        self.workflow = PersistentWorkflowRuntime(
            self.data_directory / "checkpoints.sqlite3",
            checkpoint_key,
        )
        self.runs = PilotRunService(self.database, self.workflow.application)
        self.app: FastAPI = create_pilot_app(PilotApiContext(self.database, self.auth, self.runs))
        self._bootstrap_administrator()

    def close(self) -> None:
        self.runs.close()
        self.workflow.close()

    def _bootstrap_administrator(self) -> None:
        email = os.environ.get("MADD_BOOTSTRAP_ADMIN_EMAIL")
        password = os.environ.get("MADD_BOOTSTRAP_ADMIN_PASSWORD")
        display_name = os.environ.get("MADD_BOOTSTRAP_ADMIN_NAME", "Pilot Administrator")
        if not email and not password:
            return
        if not email or not password:
            raise RuntimeError(
                "MADD_BOOTSTRAP_ADMIN_EMAIL and MADD_BOOTSTRAP_ADMIN_PASSWORD must be set together"
            )
        if self.database.get_user_by_email(email) is None:
            self.auth.provision_user(
                email=email,
                display_name=display_name,
                password=password,
                is_pilot_admin=True,
            )
