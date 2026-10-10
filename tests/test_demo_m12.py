from __future__ import annotations

from ma_due_diligence.demo_vdr import run_demo


def test_offline_demo_runs_end_to_end() -> None:
    result = run_demo()
    assert result["documents_ingested"] == 10
    assert result["duplicates"] == 1
    assert result["versions"] == 1
    revenue_warnings = result["revenue_warnings"]
    assert isinstance(revenue_warnings, list)
    assert "conflicting_contexts" in revenue_warnings
    insufficient = result["insufficient_evidence"]
    assert isinstance(insufficient, dict)
    assert insufficient["result_count"] == 0
    evaluation = result["evaluation"]
    assert isinstance(evaluation, dict)
    assert evaluation["hit_at_k"] == 1.0
