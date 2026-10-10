"""Small, explicit M6/7 evaluation suite across distinct quality dimensions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from ma_due_diligence.domain import ReviewActionType
from ma_due_diligence.specialists.fixtures import (
    build_specialist_engagement,
    create_specialist_fixture_vdr,
)
from ma_due_diligence.workflow_final import (
    HumanReviewSubmission,
    ReviewDecision,
    WorkflowApplication,
    WorkflowRequest,
    WorkflowStatus,
    build_workflow,
)
from ma_due_diligence.workflow_final.models import WorkflowState


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    scenario_id: str
    dimension: str
    description: str
    passed: bool
    evidence: str


@dataclass(frozen=True, slots=True)
class FinalEvaluationResult:
    generated_at: datetime
    scenarios: tuple[EvaluationScenario, ...]

    @property
    def passed(self) -> int:
        return sum(item.passed for item in self.scenarios)

    @property
    def total(self) -> int:
        return len(self.scenarios)


def run_final_evaluation() -> FinalEvaluationResult:
    with TemporaryDirectory(prefix="madd-evaluation-") as directory:
        manifest = create_specialist_fixture_vdr(Path(directory))
        engagement = build_specialist_engagement()
        app = WorkflowApplication(build_workflow())
        paused = app.start(
            WorkflowRequest(engagement.engagement_id, engagement, manifest),
            thread_id="final-evaluation",
        )
        completed = _approve_review(app, paused, "final-evaluation")
    financial = completed["financial"]
    coordinator = completed["specialist_result"]
    report = completed["report"]
    evidence_ids = {
        evidence.evidence_id
        for item in completed["final_findings"]
        for evidence in item.finding.finding.evidence
    }
    cited_ids = {
        citation.evidence_id
        for section in report.sections
        for finding in section.findings
        for citation in finding.citations
    }
    reported_ebitda = financial.ebitda_bridge.reported_ebitda.value
    final_ebitda = financial.ebitda_bridge.final_adjusted_ebitda
    total_adjustment = financial.ebitda_bridge.total_adjustment
    bridge_reconciles = (
        reported_ebitda is not None
        and final_ebitda is not None
        and total_adjustment is not None
        and final_ebitda == reported_ebitda + total_adjustment
    )
    checks = (
        (
            "E01",
            "ingestion_quality",
            "fixture VDR ingests a broad corpus",
            len(completed["documents"]) >= 20,
            f"documents={len(completed['documents'])}",
        ),
        (
            "E02",
            "ingestion_quality",
            "malformed/duplicate items remain visible as warnings",
            bool(completed["warnings"]),
            f"warnings={len(completed['warnings'])}",
        ),
        (
            "E03",
            "retrieval_relevance",
            "core retrieval returns multi-document evidence",
            len(completed["retrieved_evidence"]) >= 5,
            f"results={len(completed['retrieved_evidence'])}",
        ),
        (
            "E04",
            "evidence_accuracy",
            "all report citations come from finding evidence",
            cited_ids <= evidence_ids,
            f"citations={len(cited_ids)}",
        ),
        (
            "E05",
            "financial_calculation",
            "EBITDA bridge reconciles deterministically",
            bridge_reconciles,
            str(final_ebitda),
        ),
        (
            "E06",
            "financial_calculation",
            "customer concentration is quantified",
            financial.concentration.largest_customer_percent == Decimal("42.00"),
            str(financial.concentration.largest_customer_percent),
        ),
        (
            "E07",
            "finding_detection",
            "specialists produce evidence-backed findings",
            len(completed["final_findings"]) >= 8,
            f"findings={len(completed['final_findings'])}",
        ),
        (
            "E08",
            "finding_detection",
            "compound customer risk is created",
            any(
                item.finding.finding.category == "compound_customer_retention"
                for item in completed["final_findings"]
            ),
            "compound risk inspected",
        ),
        (
            "E09",
            "contradiction_detection",
            "cross-document conflicts are retained",
            bool(completed["conflicts"]),
            f"conflicts={len(completed['conflicts'])}",
        ),
        (
            "E10",
            "contradiction_detection",
            "superseded versions are distinguished",
            bool(coordinator.investigation.superseded_claim_ids),
            f"superseded={len(coordinator.investigation.superseded_claim_ids)}",
        ),
        (
            "E11",
            "human_review",
            "workflow pauses before report generation",
            paused["status"] is WorkflowStatus.REVIEW_REQUIRED and "report" not in paused,
            paused["status"].value,
        ),
        (
            "E12",
            "human_review",
            "review decisions preserve audit actions",
            bool(completed["review_actions"]),
            f"actions={len(completed['review_actions'])}",
        ),
        (
            "E13",
            "report_consistency",
            "report values match M3 outputs",
            completed["evaluation"].report_consistent,
            "report_consistent=true",
        ),
        (
            "E14",
            "end_to_end",
            "run completes with a report and no fatal error",
            completed["status"]
            in {WorkflowStatus.COMPLETED, WorkflowStatus.COMPLETED_WITH_WARNINGS}
            and report is not None,
            completed["status"].value,
        ),
    )
    return FinalEvaluationResult(
        datetime.now(UTC),
        tuple(EvaluationScenario(*item) for item in checks),
    )


def _approve_review(
    app: WorkflowApplication, state: WorkflowState, thread_id: str
) -> WorkflowState:
    decisions = [
        ReviewDecision(
            "finding",
            finding_id,
            ReviewActionType.APPROVE_FINDING,
            "Analyst reviewed the cited evidence and approved this candidate finding.",
        )
        for finding_id in state["review_request"].finding_ids
    ]
    for conflict in state.get("conflicts", ()):
        if conflict.conflict_id in state["review_request"].conflict_ids:
            decisions.append(
                ReviewDecision(
                    "conflict",
                    conflict.conflict_id,
                    ReviewActionType.RESOLVE_CONFLICT,
                    "Analyst selected the direct source for the final presentation.",
                    preferred_source_id=conflict.observation_fact_ids[0],
                )
            )
    submission = HumanReviewSubmission(
        "Evaluation Analyst",
        "Completed the required material-ambiguity review.",
        tuple(decisions),
    )
    return app.resume(thread_id=thread_id, submission=submission)


def main() -> None:
    result = run_final_evaluation()
    payload = asdict(result)
    payload["generated_at"] = result.generated_at.isoformat()
    payload["passed"] = result.passed
    payload["total"] = result.total
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
