from __future__ import annotations

from fastapi.testclient import TestClient

from ma_due_diligence.api.app import LocalRunRegistry, create_app
from ma_due_diligence.evaluation_final import run_final_evaluation


def test_api_health_start_status_review_and_report() -> None:
    registry = LocalRunRegistry()
    client = TestClient(create_app(registry))
    assert client.get("/health").json() == {"status": "ok"}
    start = client.post(
        "/diligence/runs",
        json={"run_id": "api-fixture", "fixture_mode": True},
    )
    assert start.status_code == 200
    assert start.json()["status"] == "review_required"
    state = registry.states["api-fixture"]
    finding_id = state["review_request"].finding_ids[0]
    review = client.post(
        "/diligence/runs/api-fixture/review",
        json={
            "reviewer": "API Reviewer",
            "rationale": "Reviewed the cited source.",
            "decisions": [
                {
                    "subject_type": "finding",
                    "subject_id": finding_id,
                    "action": "approve_finding",
                    "rationale": "Evidence supports the candidate finding.",
                }
            ],
        },
    )
    assert review.status_code == 200
    assert review.json()["review_action_count"] == 1
    status = client.get("/diligence/runs/api-fixture")
    assert status.status_code == 200
    report = client.get("/diligence/runs/api-fixture/report")
    assert report.status_code == 200
    assert report.json()["report"]["sections"]
    assert client.get("/diligence/runs/unknown").status_code == 404


def test_final_evaluation_has_fourteen_separate_passing_scenarios() -> None:
    result = run_final_evaluation()
    assert result.total == 14
    assert result.passed == result.total
    assert len({item.dimension for item in result.scenarios}) >= 8
