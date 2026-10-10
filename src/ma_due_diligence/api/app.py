"""Small local FastAPI facade over the checkpointed diligence workflow."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI, HTTPException

from ma_due_diligence.specialists.fixtures import (
    build_specialist_engagement,
    create_specialist_fixture_vdr,
)
from ma_due_diligence.workflow_final import (
    HumanReviewSubmission,
    ReviewDecision,
    WorkflowApplication,
    WorkflowRequest,
    build_workflow,
)
from ma_due_diligence.workflow_final.models import WorkflowState, WorkflowStatus

from .schemas import (
    ReportResponse,
    ReviewResponse,
    StartRunRequest,
    StartRunResponse,
    SubmitReviewRequest,
)


class LocalRunRegistry:
    def __init__(self) -> None:
        self.application = WorkflowApplication(build_workflow())
        self.states: dict[str, WorkflowState] = {}
        self.fixture_directories: dict[str, TemporaryDirectory[str]] = {}

    def start(self, payload: StartRunRequest) -> WorkflowState:
        if payload.run_id in self.states:
            raise ValueError("run_id already exists")
        directory = TemporaryDirectory(prefix="madd-vdr-")
        self.fixture_directories[payload.run_id] = directory
        manifest = create_specialist_fixture_vdr(Path(directory.name))
        engagement = replace(build_specialist_engagement(), engagement_id=payload.run_id)
        request = WorkflowRequest(
            payload.run_id,
            engagement,
            manifest,
            payload.review_policy,
        )
        state = self.application.start(request, thread_id=payload.run_id)
        self.states[payload.run_id] = state
        return state

    def resume(self, run_id: str, payload: SubmitReviewRequest) -> WorkflowState:
        if run_id not in self.states:
            raise KeyError(run_id)
        decisions = tuple(
            ReviewDecision(
                item.subject_type,
                item.subject_id,
                item.action,
                item.rationale,
                item.severity,
                item.preferred_source_id,
            )
            for item in payload.decisions
        )
        submission = HumanReviewSubmission(payload.reviewer, payload.rationale, decisions)
        state = self.application.resume(thread_id=run_id, submission=submission)
        self.states[run_id] = state
        return state


def create_app(registry: LocalRunRegistry | None = None) -> FastAPI:
    runs = registry or LocalRunRegistry()
    app = FastAPI(
        title="AI Due-Diligence Agent",
        version="1.0.0",
        description="Local, evidence-first M&A diligence workflow API.",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/diligence/runs", response_model=StartRunResponse)
    def start_run(payload: StartRunRequest) -> dict[str, Any]:
        try:
            state = runs.start(payload)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {**_status_payload(payload.run_id, state), "created": True}

    @app.get("/diligence/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        state = _state_or_404(runs, run_id)
        return _status_payload(run_id, state)

    @app.post("/diligence/runs/{run_id}/review", response_model=ReviewResponse)
    def submit_review(run_id: str, payload: SubmitReviewRequest) -> dict[str, Any]:
        state = _state_or_404(runs, run_id)
        if state.get("status") is not WorkflowStatus.REVIEW_REQUIRED:
            raise HTTPException(status_code=409, detail="run is not awaiting analyst review")
        try:
            state = runs.resume(run_id, payload)
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            **_status_payload(run_id, state),
            "review_action_count": len(state.get("review_actions", ())),
        }

    @app.get("/diligence/runs/{run_id}/report", response_model=ReportResponse)
    def get_report(run_id: str) -> dict[str, Any]:
        state = _state_or_404(runs, run_id)
        report = state.get("report")
        if report is None:
            raise HTTPException(status_code=409, detail="report is not available")
        return {
            "run_id": run_id,
            "status": state["status"],
            "report": report,
        }

    return app


def _state_or_404(registry: LocalRunRegistry, run_id: str) -> WorkflowState:
    state = registry.states.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run not found")
    return state


def _status_payload(run_id: str, state: WorkflowState) -> dict[str, Any]:
    request = state.get("review_request")
    failure = state.get("failure_code")
    coordinator = state.get("specialist_result")
    return {
        "run_id": run_id,
        "status": state.get("status", WorkflowStatus.CREATED),
        "failure_code": failure,
        "document_count": len(state.get("documents", ())),
        "finding_count": len(state.get("final_findings", ()))
        or len(coordinator.findings if coordinator else ()),
        "review_required": state.get("status") is WorkflowStatus.REVIEW_REQUIRED,
        "review_reasons": list(request.reasons) if request else [],
        "warnings": list(state.get("warnings", ())),
        "errors": [item.message for item in state.get("errors", ())],
    }


app = create_app()
