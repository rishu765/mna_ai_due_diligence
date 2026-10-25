"""Durable encrypted LangGraph runtime for the controlled pilot."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from langgraph.checkpoint.sqlite import SqliteSaver

from ma_due_diligence.workflow_final.checkpointing import EncryptedCheckpointSerializer
from ma_due_diligence.workflow_final.graph import WorkflowApplication, build_workflow
from ma_due_diligence.workflow_final.models import RetryPolicy
from ma_due_diligence.workflow_final.services import WorkflowServices


class PersistentWorkflowRuntime:
    """Own the SQLite connection that backs an encrypted checkpointed workflow."""

    def __init__(
        self,
        path: Path,
        key: bytes,
        *,
        services: WorkflowServices | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if len(key) != 32:
            raise ValueError("checkpoint encryption key must contain 32 bytes")
        resolved = path.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(resolved, check_same_thread=False)
        self._connection.execute("PRAGMA busy_timeout = 10000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._checkpointer = SqliteSaver(
            self._connection,
            serde=EncryptedCheckpointSerializer(key),
        )
        self.application = WorkflowApplication(
            build_workflow(
                services,
                retry_policy=retry_policy,
                checkpointer=self._checkpointer,
            )
        )
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> PersistentWorkflowRuntime:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
