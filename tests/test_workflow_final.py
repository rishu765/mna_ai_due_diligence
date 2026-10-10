from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ma_due_diligence.domain import ReviewActionType, Severity
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever
from ma_due_diligence.specialists.analyzers import CommercialDiligenceAnalyzer
from ma_due_diligence.specialists.coordinator import SpecialistCoordinator
from ma_due_diligence.specialists.fixtures import (
    build_specialist_engagement,
    create_specialist_fixture_vdr,
)
from ma_due_diligence.specialists.models import AgentId, SpecialistContext, SpecialistResult
from ma_due_diligence.specialists.plans import OPERATIONAL_PLAN
from ma_due_diligence.workflow_final import (
    HumanReviewSubmission,
    ReviewDecision,
    ReviewPolicy,
    WorkflowApplication,
    WorkflowRequest,
    WorkflowStatus,
    build_workflow,
)
from ma_due_diligence.workflow_final.models import RetryPolicy, WorkflowState
from ma_due_diligence.workflow_final.reporting import (
    DiligenceReportGenerator,
    render_markdown,
    validate_report,
)
from ma_due_diligence.workflow_final.services import WorkflowServices


def _paused(
    tmp_path: Path, *, policy: ReviewPolicy = ReviewPolicy.WHEN_NEEDED
) -> tuple[WorkflowApplication, WorkflowState]:
    manifest = create_specialist_fixture_vdr(tmp_path)
    engagement = build_specialist_engagement()
    app = WorkflowApplication(build_workflow())
    state = app.start(
        WorkflowRequest(engagement.engagement_id, engagement, manifest, policy),
        thread_id=f"run-{policy.value}",
    )
    return app, state


def test_graph_pauses_with_checkpointed_evidence_and_no_report(tmp_path: Path) -> None:
    app, state = _paused(tmp_path)
    assert state["status"] is WorkflowStatus.REVIEW_REQUIRED
    assert state["documents"]
    assert state["retrieved_evidence"]
    assert state["financial"].ebitda_bridge.final_adjusted_ebitda is not None
    assert state["specialist_result"].findings
    assert state["conflicts"]
    assert "report" not in state
    assert app.state(thread_id="run-when_needed")["review_request"] == state["review_request"]


def test_resume_applies_review_and_generates_consistent_report(tmp_path: Path) -> None:
    app, state = _paused(tmp_path)
    finding_id = state["review_request"].finding_ids[0]
    submission = HumanReviewSubmission(
        "Deal Team Reviewer",
        "Reviewed the evidence and adjusted severity.",
        (
            ReviewDecision(
                "finding",
                finding_id,
                ReviewActionType.CHANGE_SEVERITY,
                "The exposure is material but mitigable.",
                Severity.MEDIUM,
            ),
        ),
    )
    completed = app.resume(thread_id="run-when_needed", submission=submission)
    assert completed["status"] in {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.COMPLETED_WITH_WARNINGS,
    }
    reviewed = next(
        item.finding.finding
        for item in completed["final_findings"]
        if item.finding.finding.finding_id == finding_id
    )
    assert reviewed.severity is Severity.MEDIUM
    assert completed["review_actions"][0].prior_state
    assert completed["review_actions"][0].resulting_state
    assert completed["report"].review_action_ids
    validate_report(completed["report"], completed["final_findings"], completed["financial"])
    markdown = render_markdown(completed["report"])
    assert "Due-Diligence Report" in markdown
    assert "Source:" in markdown


def test_request_more_evidence_stops_in_waiting_state(tmp_path: Path) -> None:
    app, state = _paused(tmp_path)
    finding_id = state["review_request"].finding_ids[0]
    completed = app.resume(
        thread_id="run-when_needed",
        submission=HumanReviewSubmission(
            "Deal Team Reviewer",
            "Support is incomplete.",
            (
                ReviewDecision(
                    "finding",
                    finding_id,
                    ReviewActionType.REQUEST_MORE_EVIDENCE,
                    "Provide the underlying customer schedule.",
                ),
            ),
        ),
    )
    assert completed["status"] is WorkflowStatus.WAITING_FOR_INFORMATION
    assert "report" not in completed
    assert completed["final_result"].failure_code is not None


@dataclass
class FlakyNarrativeProvider:
    attempts: int = 0

    def draft(self, title: str, grounded_text: tuple[str, ...]) -> str:
        self.attempts += 1
        if self.attempts == 1:
            raise TimeoutError("temporary provider timeout")
        return " ".join(grounded_text) or f"No material items for {title}."


def test_report_generation_retries_once(tmp_path: Path) -> None:
    provider = FlakyNarrativeProvider()
    services = WorkflowServices(report_generator=DiligenceReportGenerator(provider))
    app = WorkflowApplication(build_workflow(services, retry_policy=RetryPolicy(report=1)))
    manifest = create_specialist_fixture_vdr(tmp_path)
    engagement = build_specialist_engagement()
    state = app.start(
        WorkflowRequest(
            engagement.engagement_id,
            engagement,
            manifest,
            ReviewPolicy.NEVER,
        ),
        thread_id="report-retry",
    )
    assert state["report"] is not None
    assert state["retry_counts"]["report"] == 1
    assert provider.attempts > 1


def test_invalid_manifest_fails_with_stable_code(tmp_path: Path) -> None:
    engagement = build_specialist_engagement()
    app = WorkflowApplication(build_workflow())
    state = app.start(
        WorkflowRequest(engagement.engagement_id, engagement, tmp_path / "missing.json"),
        thread_id="invalid-input",
    )
    assert state["status"] is WorkflowStatus.FAILED
    assert state["failure_code"] is not None
    assert state["failure_code"].value == "invalid_input"
    assert state["final_result"].errors


class FailingOperationalAnalyzer:
    agent_id = AgentId.OPERATIONAL
    retrieval_plan = OPERATIONAL_PLAN

    def analyze(self, context: SpecialistContext) -> SpecialistResult:
        raise RuntimeError("fixture specialist failure")


def test_graph_isolates_one_specialist_failure(tmp_path: Path) -> None:
    def coordinator_factory(retriever: HybridDiligenceRetriever) -> SpecialistCoordinator:
        return SpecialistCoordinator(
            retriever,
            analyzers=(CommercialDiligenceAnalyzer(), FailingOperationalAnalyzer()),
        )

    services = WorkflowServices(coordinator_factory=coordinator_factory)
    app = WorkflowApplication(build_workflow(services))
    engagement = build_specialist_engagement()
    state = app.start(
        WorkflowRequest(
            engagement.engagement_id,
            engagement,
            create_specialist_fixture_vdr(tmp_path),
            ReviewPolicy.NEVER,
        ),
        thread_id="partial-specialist",
    )
    assert state["status"] is WorkflowStatus.COMPLETED_WITH_WARNINGS
    assert len(state["specialist_result"].specialist_results) == 1
    assert len(state["specialist_result"].errors) == 1
    assert state["evaluation"].failed_specialists == 1
