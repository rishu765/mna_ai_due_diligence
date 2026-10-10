"""Reproducible offline final workflow demo with a real pause/resume cycle."""

from pathlib import Path
from tempfile import TemporaryDirectory

from ma_due_diligence.evaluation_final import _approve_review
from ma_due_diligence.specialists.fixtures import (
    build_specialist_engagement,
    create_specialist_fixture_vdr,
)
from ma_due_diligence.workflow_final import WorkflowApplication, WorkflowRequest, build_workflow
from ma_due_diligence.workflow_final.reporting import render_markdown


def main() -> None:
    with TemporaryDirectory(prefix="madd-demo-") as directory:
        manifest = create_specialist_fixture_vdr(Path(directory))
        engagement = build_specialist_engagement()
        application = WorkflowApplication(build_workflow())
        paused = application.start(
            WorkflowRequest(engagement.engagement_id, engagement, manifest),
            thread_id="offline-final-demo",
        )
        print(f"Paused status: {paused['status'].value}")
        print(f"Review reasons: {len(paused['review_request'].reasons)}")
        completed = _approve_review(application, paused, "offline-final-demo")
        print(f"Final status: {completed['status'].value}")
        print(f"Documents: {len(completed['documents'])}")
        print(f"Prioritized findings: {len(completed['final_findings'])}")
        print(f"Review actions: {len(completed['review_actions'])}")
        print(f"Trace events: {len(completed['trace'])}")
        evaluation = completed["evaluation"]
        print(
            "Evaluation: "
            f"citation coverage={evaluation.citation_coverage_percent}%; "
            f"report consistent={evaluation.report_consistent}; "
            f"specialists completed={evaluation.completed_specialists}; "
            f"specialists failed={evaluation.failed_specialists}"
        )
        print()
        print(render_markdown(completed["report"]))


if __name__ == "__main__":
    main()
