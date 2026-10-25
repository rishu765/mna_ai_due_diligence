from __future__ import annotations

from typing import Any, cast

from ma_due_diligence.api.pilot_runs import run_payload
from ma_due_diligence.financial.methodology import (
    default_financial_methodology,
    engagement_methodology_payload,
)
from ma_due_diligence.workflow_final.financial import run_fixture_financial_diligence
from ma_due_diligence.workflow_final.models import WorkflowState, WorkflowStatus


def test_default_methodology_is_versioned_stable_and_reviewable() -> None:
    first = default_financial_methodology().payload()
    second = default_financial_methodology().payload()

    assert first == second
    assert first["version"] == "1.0.0"
    assert len(str(first["fingerprint_sha256"])) == 64
    source_priority = cast(list[str], first["source_priority"])
    thresholds = cast(dict[str, object], first["thresholds"])
    rules = cast(list[dict[str, object]], first["rules"])
    assert source_priority[0] == "financial_statements"
    assert thresholds["material_variance_percent"] == "5"
    assert {item["code"] for item in rules} >= {
        "BASIS-001",
        "QOE-001",
        "NWC-001",
        "NETDEBT-001",
        "CONC-001",
    }


def test_engagement_methodology_discloses_assumptions_without_implicit_conversion() -> None:
    payload = engagement_methodology_payload(
        reporting_currency="GBP",
        unit="million",
        as_of_date="2026-06-30",
        materiality_threshold="GBP 1m",
    )
    assumptions = cast(dict[str, object], payload["engagement_assumptions"])

    assert assumptions["reporting_currency"] == "GBP"
    assert assumptions["materiality_threshold"] == "GBP 1m"
    assert assumptions["fx_conversion"] == "none_without_explicit_policy"
    assert assumptions["period_conversion"] == "none_without_explicit_policy"


def test_released_financial_outputs_include_reconciling_calculation_trace() -> None:
    financial = run_fixture_financial_diligence("eng-methodology")
    state: WorkflowState = {
        "financial": financial,
        "status": WorkflowStatus.REVIEW_REQUIRED,
    }

    payload = run_payload("run-methodology", state)
    financial_payload = payload["financial"]
    assert isinstance(financial_payload, dict)
    trace = cast(dict[str, Any], financial_payload["calculation_trace"])

    assert trace["ebitda_bridge"]["reconciles"] is True
    assert trace["ebitda_bridge"]["result"] == "15"
    assert trace["net_debt"]["reconciles"] is True
    assert trace["customer_concentration"]["customers"]
    known_working_capital = [
        item for item in trace["working_capital"] if item["result"] is not None
    ]
    assert all(item["reconciles"] for item in known_working_capital)
    methodology = cast(dict[str, object], financial_payload["methodology"])
    assert methodology["version"] == "1.0.0"
