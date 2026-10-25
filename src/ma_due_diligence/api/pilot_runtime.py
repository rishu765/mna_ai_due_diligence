"""Configured local runtime for the authenticated pilot application."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from ma_due_diligence.persistence import (
    EncryptedLocalDocumentStore,
    PersistentWorkflowRuntime,
    PilotDatabase,
    PilotDocumentService,
    document_key_from_environment,
)
from ma_due_diligence.security.service import PilotAuthService

from .pilot_app import PilotApiContext, create_pilot_app
from .pilot_documents import PilotDocumentProcessingService, UploadPolicy
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
        document_key = document_key_from_environment("MADD_DOCUMENT_KEY")
        self.document_store = EncryptedLocalDocumentStore(
            self.data_directory / "documents",
            document_key,
        )
        self.documents = PilotDocumentProcessingService(
            self.database,
            PilotDocumentService(self.database, self.document_store),
            policy=UploadPolicy(
                maximum_file_bytes=_positive_environment_integer(
                    "MADD_MAX_UPLOAD_BYTES", 50 * 1024 * 1024
                )
            ),
        )
        checkpoint_key = document_key_from_environment("MADD_CHECKPOINT_KEY")
        self.workflow = PersistentWorkflowRuntime(
            self.data_directory / "checkpoints.sqlite3",
            checkpoint_key,
        )
        self.runs = PilotRunService(self.database, self.workflow.application)
        self.app: FastAPI = create_pilot_app(
            PilotApiContext(self.database, self.auth, self.runs, self.documents)
        )
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


def _positive_environment_integer(variable: str, default: int) -> int:
    raw = os.environ.get(variable)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{variable} must be an integer") from error
    if value <= 0:
        raise RuntimeError(f"{variable} must be positive")
    return value
