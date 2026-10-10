"""Small, category-specific M3 evaluation suite for the synthetic case."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ma_due_diligence.financial.analytics import (
    analyze_nwc_trend,
    calculate_margin,
    calculate_nwc_peg,
    customer_concentration,
)
from ma_due_diligence.financial.findings import FinancialFindingService
from ma_due_diligence.financial.fixtures import ENGAGEMENT_ID, build_financial_fixture_case
from ma_due_diligence.financial.models import FinancialMetric, NwcPegMethod
from ma_due_diligence.financial.net_debt import calculate_adjusted_net_debt
from ma_due_diligence.financial.qoe import AdjustmentAssessmentService, build_ebitda_bridge
from ma_due_diligence.financial.reconciliation import FinancialReconciliationService


@dataclass(frozen=True, slots=True)
class EvaluationCheck:
    category: str
    passed: bool
    expected: str
    actual: str


@dataclass(frozen=True, slots=True)
class FinancialEvaluationReport:
    checks: tuple[EvaluationCheck, ...]

    @property
    def passed(self) -> int:
        return sum(item.passed for item in self.checks)


def evaluate_financial_fixture() -> FinancialEvaluationReport:
    case = build_financial_fixture_case()
    revenue = tuple(
        item
        for item in case.observations
        if item.metric is FinancialMetric.REVENUE and item.period.label == "FY2025"
    )
    reconciliation = FinancialReconciliationService().reconcile(FinancialMetric.REVENUE, revenue)
    reported = next(
        item for item in case.observations if item.observation_id == "ebitda-audited-25"
    )
    assessments = AdjustmentAssessmentService().assess(case.adjustments)
    bridge = build_ebitda_bridge(reported, assessments)
    concentration = customer_concentration(case.customers)
    trend = analyze_nwc_trend(case.working_capital)
    peg = calculate_nwc_peg(trend, NwcPegMethod.TRAILING_AVERAGE)
    net_debt = calculate_adjusted_net_debt(case.net_debt_items)
    gross_profit = next(
        item for item in case.observations if item.observation_id == "gp-audited-25"
    )
    audited_revenue = next(
        item for item in case.observations if item.observation_id == "rev-audited-25"
    )
    margin = calculate_margin(gross_profit, audited_revenue, FinancialMetric.GROSS_MARGIN)
    findings = FinancialFindingService().generate(
        engagement_id=ENGAGEMENT_ID,
        reconciliations=(reconciliation,),
        concentration=concentration,
        bridge=bridge,
        nwc_trend=trend,
        net_debt=net_debt,
    )
    evidence_linked = all(
        output.finding.evidence or output.finding.support_status.value in {"derived", "unverified"}
        for output in findings
    )
    checks = (
        EvaluationCheck(
            "financial_extraction_accuracy",
            len(case.observations) == 11,
            "11 fixture observations",
            str(len(case.observations)),
        ),
        EvaluationCheck(
            "numeric_normalization",
            margin.percentage == Decimal("36.00"),
            "36.00",
            str(margin.percentage),
        ),
        EvaluationCheck(
            "reconciliation_correctness",
            reconciliation.absolute_variance == Decimal("8"),
            "8",
            str(reconciliation.absolute_variance),
        ),
        EvaluationCheck(
            "adjustment_classification",
            sum(item.accepted_for_bridge for item in assessments) == 1,
            "1 accepted",
            str(sum(item.accepted_for_bridge for item in assessments)),
        ),
        EvaluationCheck(
            "ebitda_bridge_correctness",
            bridge.final_adjusted_ebitda == Decimal("15"),
            "15",
            str(bridge.final_adjusted_ebitda),
        ),
        EvaluationCheck(
            "customer_concentration",
            concentration.largest_customer_percent == Decimal("42.00"),
            "42.00",
            str(concentration.largest_customer_percent),
        ),
        EvaluationCheck(
            "nwc_calculation",
            trend.results[-1].net_working_capital == Decimal("12.5"),
            "12.5",
            str(trend.results[-1].net_working_capital),
        ),
        EvaluationCheck(
            "normalized_nwc_peg",
            peg.normalized_nwc is not None,
            "available",
            str(peg.normalized_nwc),
        ),
        EvaluationCheck(
            "net_debt_bridge",
            net_debt.adjusted_net_debt == Decimal("20.0"),
            "20.0",
            str(net_debt.adjusted_net_debt),
        ),
        EvaluationCheck("finding_generation", len(findings) >= 4, ">=4", str(len(findings))),
        EvaluationCheck(
            "evidence_linkage",
            evidence_linked,
            "all linked or explicitly derived",
            str(evidence_linked),
        ),
    )
    return FinancialEvaluationReport(checks)
