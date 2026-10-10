"""Adapter that assembles existing deterministic M3 services for the final workflow."""

from ma_due_diligence.financial.analytics import (
    analyze_nwc_trend,
    calculate_nwc_peg,
    customer_concentration,
)
from ma_due_diligence.financial.findings import FinancialFindingService
from ma_due_diligence.financial.fixtures import build_financial_fixture_case
from ma_due_diligence.financial.models import FinancialMetric, NwcPegMethod
from ma_due_diligence.financial.net_debt import calculate_adjusted_net_debt
from ma_due_diligence.financial.qoe import AdjustmentAssessmentService, build_ebitda_bridge
from ma_due_diligence.financial.reconciliation import FinancialReconciliationService
from ma_due_diligence.workflow_final.models import FinancialDiligenceSnapshot


def run_fixture_financial_diligence(engagement_id: str) -> FinancialDiligenceSnapshot:
    """Run M3 services; orchestration owns no financial arithmetic."""

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
    bridge = build_ebitda_bridge(reported, AdjustmentAssessmentService().assess(case.adjustments))
    concentration = customer_concentration(case.customers)
    working_capital = analyze_nwc_trend(case.working_capital)
    peg = calculate_nwc_peg(working_capital, NwcPegMethod.TRAILING_AVERAGE)
    net_debt = calculate_adjusted_net_debt(case.net_debt_items)
    findings = FinancialFindingService().generate(
        engagement_id=engagement_id,
        reconciliations=(reconciliation,),
        concentration=concentration,
        bridge=bridge,
        nwc_trend=working_capital,
        net_debt=net_debt,
    )
    return FinancialDiligenceSnapshot(
        reconciliation,
        bridge,
        concentration,
        working_capital,
        peg,
        net_debt,
        findings,
    )
