from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from ma_due_diligence.domain import AnalystDecision, Money, ProposalStatus
from ma_due_diligence.financial.analytics import (
    analyze_nwc_trend,
    calculate_margin,
    calculate_nwc,
    calculate_nwc_peg,
    customer_concentration,
    revenue_growth,
)
from ma_due_diligence.financial.findings import (
    FinancialFindingService,
    follow_up_questions,
    materiality_for_amount,
)
from ma_due_diligence.financial.fixtures import ENGAGEMENT_ID, build_financial_fixture_case
from ma_due_diligence.financial.models import (
    CalculationWarningCode,
    FinancialMetric,
    MarginResult,
    NwcPegMethod,
)
from ma_due_diligence.financial.net_debt import calculate_adjusted_net_debt
from ma_due_diligence.financial.qoe import AdjustmentAssessmentService, build_ebitda_bridge
from ma_due_diligence.financial.reconciliation import FinancialReconciliationService


def test_repeated_adjustments_are_not_automatically_accepted() -> None:
    case = build_financial_fixture_case()
    assessments = AdjustmentAssessmentService().assess(case.adjustments)
    assert "repeated_one_time_item" in assessments[0].rule_codes
    assert "repeated_one_time_item" in assessments[1].rule_codes
    assert assessments[2].accepted_for_bridge


def test_duplicate_adjustment_is_detected() -> None:
    adjustment = build_financial_fixture_case().adjustments[2]
    assessments = AdjustmentAssessmentService().assess((adjustment, adjustment))
    assert "duplicate_adjustment" in assessments[1].rule_codes
    assert not assessments[1].accepted_for_bridge


def test_ebitda_bridge_uses_only_accepted_adjustments() -> None:
    case = build_financial_fixture_case()
    reported = next(
        item for item in case.observations if item.observation_id == "ebitda-audited-25"
    )
    bridge = build_ebitda_bridge(reported, AdjustmentAssessmentService().assess(case.adjustments))
    assert bridge.final_adjusted_ebitda == Decimal("15")
    assert bridge.total_adjustment == Decimal("1")
    assert bridge.uplift_percent == Decimal("1") / Decimal("14") * Decimal("100")
    assert len(bridge.rejected_adjustments) == 2
    assert all(line.evidence for line in bridge.lines)


def test_unaccepted_adjustment_stays_out_of_bridge() -> None:
    case = build_financial_fixture_case()
    adjustment = replace(
        case.adjustments[2],
        proposal_status=ProposalStatus.PROPOSED,
        analyst_decision=AnalystDecision.PENDING,
    )
    bridge = build_ebitda_bridge(
        case.observations[6], AdjustmentAssessmentService().assess((adjustment,))
    )
    assert bridge.final_adjusted_ebitda == Decimal("14")


def test_ebitda_bridge_normalizes_adjustment_units() -> None:
    case = build_financial_fixture_case()
    adjustment = replace(
        case.adjustments[2],
        amount=Money(Decimal("1000"), "GBP"),
        unit="thousand",
    )
    bridge = build_ebitda_bridge(
        case.observations[6], AdjustmentAssessmentService().assess((adjustment,))
    )
    assert bridge.final_adjusted_ebitda == Decimal("15")


def test_revenue_growth_and_margins() -> None:
    case = build_financial_fixture_case()
    growth = revenue_growth(case.observations[0], case.observations[2])
    assert growth.percentage == Decimal("7.5")
    margin = calculate_margin(
        case.observations[5], case.observations[4], FinancialMetric.GROSS_MARGIN
    )
    assert margin.percentage == Decimal("36.00")
    ebitda_margin = calculate_margin(
        case.observations[6], case.observations[4], FinancialMetric.EBITDA_MARGIN
    )
    assert ebitda_margin.percentage == Decimal("14") / Decimal("92") * Decimal("100")


def test_zero_denominator_returns_warning() -> None:
    case = build_financial_fixture_case()
    zero_revenue = replace(case.observations[4], value=Decimal("0"))
    result = calculate_margin(case.observations[5], zero_revenue, FinancialMetric.GROSS_MARGIN)
    assert result.percentage is None
    assert result.warnings[0].code is CalculationWarningCode.ZERO_DENOMINATOR


def test_customer_concentration_calculates_top_bands() -> None:
    result = customer_concentration(build_financial_fixture_case().customers)
    assert result.customer_count == 5
    assert result.largest_customer_percent == Decimal("42.00")
    assert result.top_five_percent == Decimal("100")
    assert result.top_ten_percent == Decimal("100")
    assert result.concentrated


def test_customer_concentration_handles_zero_total() -> None:
    customers = build_financial_fixture_case().customers
    zero = tuple(replace(item, revenue=Decimal("0")) for item in customers)
    result = customer_concentration(zero)
    assert result.largest_customer_percent is None
    assert result.warnings[0].code is CalculationWarningCode.ZERO_DENOMINATOR


def test_nwc_calculation_trend_and_peg_methods() -> None:
    case = build_financial_fixture_case()
    december = calculate_nwc(case.working_capital[-1])
    assert december.net_working_capital == Decimal("12.5")
    trend = analyze_nwc_trend(case.working_capital)
    assert trend.average is not None
    assert trend.median is not None
    assert trend.recent_variance_from_average is not None
    assert trend.warnings[0].code is CalculationWarningCode.INCOMPLETE_HISTORY
    average = calculate_nwc_peg(trend, NwcPegMethod.TRAILING_AVERAGE)
    midpoint = calculate_nwc_peg(trend, NwcPegMethod.MEDIAN)
    seasonal = calculate_nwc_peg(
        trend, NwcPegMethod.SELECTED_SEASONAL_PERIOD, selected_period_label="2025-12"
    )
    assert average.normalized_nwc == trend.average
    assert midpoint.normalized_nwc == trend.median
    assert seasonal.normalized_nwc == Decimal("12.5")
    assert average.current_nwc is not None
    assert average.normalized_nwc is not None
    assert average.surplus_or_shortfall == average.current_nwc - average.normalized_nwc


def test_missing_nwc_component_remains_unknown() -> None:
    result = calculate_nwc(build_financial_fixture_case().working_capital[8])
    assert result.net_working_capital is None
    assert result.warnings[0].code is CalculationWarningCode.MISSING_INPUT


def test_adjusted_net_debt_excludes_restricted_cash() -> None:
    bridge = calculate_adjusted_net_debt(build_financial_fixture_case().net_debt_items)
    assert bridge.adjusted_net_debt == Decimal("20.0")
    assert all(line.label != "Debt service reserve" for line in bridge.lines)
    assert any(w.code is CalculationWarningCode.UNSUPPORTED_CLASSIFICATION for w in bridge.warnings)


def test_net_debt_returns_partial_warning_for_missing_amount() -> None:
    item = replace(
        build_financial_fixture_case().net_debt_items[1],
        amount=None,
        status=build_financial_fixture_case().net_debt_items[1].status.PROPOSED,
    )
    bridge = calculate_adjusted_net_debt((item,))
    assert bridge.adjusted_net_debt is None
    assert any(w.code is CalculationWarningCode.MISSING_INPUT for w in bridge.warnings)


def test_materiality_findings_and_follow_up_questions() -> None:
    case = build_financial_fixture_case()
    revenue = tuple(
        item
        for item in case.observations
        if item.metric is FinancialMetric.REVENUE and item.period.label == "FY2025"
    )
    reconciliation = FinancialReconciliationService().reconcile(FinancialMetric.REVENUE, revenue)
    bridge = build_ebitda_bridge(
        case.observations[6], AdjustmentAssessmentService().assess(case.adjustments)
    )
    trend = analyze_nwc_trend(case.working_capital)
    net_debt = calculate_adjusted_net_debt(case.net_debt_items)
    findings = FinancialFindingService().generate(
        engagement_id=ENGAGEMENT_ID,
        reconciliations=(reconciliation,),
        concentration=customer_concentration(case.customers),
        bridge=bridge,
        nwc_trend=trend,
        net_debt=net_debt,
    )
    assert {item.finding.finding_id for item in findings} >= {
        "fin-conflict-revenue",
        "fin-customer-concentration",
        "fin-recurring-addback",
        "fin-restricted-cash",
    }
    assert len(follow_up_questions(ENGAGEMENT_ID, findings)) == len(findings)
    assessment = materiality_for_amount(Decimal("8"), case.observations[4], rationale="test")
    assert assessment.percentage == Decimal("8") / Decimal("92") * Decimal("100")


def test_revenue_growth_and_margin_red_flags_use_configured_thresholds() -> None:
    case = build_financial_fixture_case()
    high_growth = revenue_growth(
        case.observations[0], replace(case.observations[4], value=Decimal("100"))
    )
    prior_margin = MarginResult(
        FinancialMetric.GROSS_MARGIN,
        case.observations[2].period,
        Decimal("40"),
        ("gp-24", "rev-24"),
    )
    current_margin = MarginResult(
        FinancialMetric.GROSS_MARGIN,
        case.observations[4].period,
        Decimal("36"),
        ("gp-audited-25", "rev-audited-25"),
    )
    findings = FinancialFindingService().generate(
        engagement_id=ENGAGEMENT_ID,
        revenue_growth_results=(high_growth,),
        margin_results=(prior_margin, current_margin),
    )
    assert {item.finding.title for item in findings} == {
        "Unusually high revenue growth",
        "Declining margin trend",
    }
    assert all(item.finding.support_status.value == "derived" for item in findings)
