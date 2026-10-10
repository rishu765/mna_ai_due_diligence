"""Expanded fictitious VDR and deterministic M3 inputs for M4/5."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ma_due_diligence.domain import (
    DealType,
    DiligenceEngagement,
    DiligenceScope,
    DiligenceWorkstream,
    EntityReference,
    TransactionContext,
)
from ma_due_diligence.financial.analytics import analyze_nwc_trend, customer_concentration
from ma_due_diligence.financial.findings import FinancialFindingService
from ma_due_diligence.financial.fixtures import (
    ENGAGEMENT_ID,
    build_financial_fixture_case,
    create_financial_fixture_vdr,
)
from ma_due_diligence.financial.models import FinancialFindingOutput, FinancialMetric
from ma_due_diligence.financial.net_debt import calculate_adjusted_net_debt
from ma_due_diligence.financial.qoe import AdjustmentAssessmentService, build_ebitda_bridge
from ma_due_diligence.financial.reconciliation import FinancialReconciliationService


def create_specialist_fixture_vdr(root: Path) -> Path:
    """Create the M3 corpus plus deliberately connected M4/5 risk signals."""

    manifest_path = create_financial_fixture_vdr(root)
    documents: dict[str, str] = {
        "apex_customer_contract_v1.txt": (
            "Customer Agreement - Apex Retail\n"
            "Effective date: 2024-01-01\nVersion 1\n"
            "Section 7 Change of Control. Apex consent is required before a change of control.\n"
            "Section 8 Assignment. The supplier may not assign this agreement without consent.\n"
            "The agreement expires 31 December 2026.\n"
        ),
        "apex_customer_contract_v2.txt": (
            "Customer Agreement - Apex Retail\n"
            "Effective date: 2025-07-01\nVersion 2 revised\n"
            "Section 7 Change of Control. Apex consent is required before a change of control; "
            "Apex may terminate following an unapproved change of control.\n"
            "Section 8 Assignment. The supplier may not assign this agreement without consent.\n"
            "Section 9 Termination for convenience. Apex may terminate on 90 days notice.\n"
            "The agreement expires 31 December 2027.\n"
        ),
        "beacon_customer_contract.txt": (
            "Customer Agreement - Beacon Foods\nEffective date: 2025-01-01\n"
            "The agreement expires 31 December 2029. Assignment is permitted to an affiliate.\n"
        ),
        "orion_supplier_contract.txt": (
            "Supplier Agreement - Orion Metals\nEffective date: 2025-03-01\n"
            "Orion supplies the sole-source alloy component. The agreement expires 31 March 2028.\n"
        ),
        "supplier_concentration_schedule_FY2025.csv": (
            "Supplier,Share of critical materials\nOrion Metals,70%\nOther suppliers,30%\n"
        ),
        "operations_headcount_report.txt": (
            "Operations and Headcount Report\n"
            "Capacity utilization is 95%. The alloy component remains single-source from Orion Metals.\n"
            "The plant manager is the only employee certified for the legacy production line.\n"
        ),
        "board_memo_supplier_diversification.txt": (
            "Board Memo - Operations\nEffective date: 2025-11-30\n"
            "Management reports that supplier diversification is completed and supply risk is resolved.\n"
        ),
        "commercial_forecast_FY2026.txt": (
            "Commercial Forecast FY2026\nForecast revenue growth is 30%.\n"
            "The forecast assumes Apex renewal and continued current pricing.\n"
        ),
        "commercial_actual_trend_FY2025.txt": (
            "Customer Sales Report FY2025\nActual revenue growth is 2%.\n"
            "Largest customer Apex represents 42% of revenue.\n"
        ),
        "commercial_actual_trend_FY2024.txt": (
            "Customer Sales Report FY2024\nActual revenue growth is 6%.\n"
            "Largest customer Apex represents 35% of revenue.\n"
        ),
    }
    for filename, content in documents.items():
        (root / filename).write_text(content, encoding="utf-8")

    overrides: dict[str, tuple[str, tuple[str, ...], str | None]] = {
        "apex_customer_contract_v1.txt": (
            "customer_contract",
            ("legal_contractual", "commercial"),
            "v1",
        ),
        "apex_customer_contract_v2.txt": (
            "customer_contract",
            ("legal_contractual", "commercial"),
            "v2",
        ),
        "beacon_customer_contract.txt": (
            "customer_contract",
            ("legal_contractual", "commercial"),
            None,
        ),
        "orion_supplier_contract.txt": (
            "supplier_contract",
            ("legal_contractual", "operational"),
            None,
        ),
        "supplier_concentration_schedule_FY2025.csv": (
            "supplier_contract",
            ("operational",),
            None,
        ),
        "operations_headcount_report.txt": ("hr_report", ("operational", "hr"), None),
        "board_memo_supplier_diversification.txt": (
            "board_material",
            ("operational", "commercial"),
            None,
        ),
        "commercial_forecast_FY2026.txt": (
            "forecast",
            ("commercial", "financial"),
            None,
        ),
        "commercial_actual_trend_FY2025.txt": (
            "sales_report",
            ("commercial", "financial"),
            None,
        ),
        "commercial_actual_trend_FY2024.txt": (
            "sales_report",
            ("commercial", "financial"),
            None,
        ),
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    known = {entry["path"] for entry in manifest["documents"]}
    for filename, (document_type, workstreams, version) in overrides.items():
        if filename in known:
            manifest["documents"] = [
                entry for entry in manifest["documents"] if entry["path"] != filename
            ]
        entry: dict[str, object] = {
            "path": filename,
            "document_type": document_type,
            "workstreams": list(workstreams),
        }
        if version is not None:
            entry["version"] = version
        manifest["documents"].append(entry)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def build_specialist_engagement() -> DiligenceEngagement:
    return DiligenceEngagement(
        ENGAGEMENT_ID,
        EntityReference("target-northstar", "Northstar Components Ltd", jurisdiction="England"),
        EntityReference("buyer-bluehaven", "Bluehaven Holdings plc", jurisdiction="England"),
        TransactionContext(DealType.ACQUISITION, "Proposed acquisition of Northstar Components"),
        DiligenceScope(
            (
                DiligenceWorkstream.FINANCIAL,
                DiligenceWorkstream.COMMERCIAL,
                DiligenceWorkstream.LEGAL_CONTRACTUAL,
                DiligenceWorkstream.OPERATIONAL,
            )
        ),
        date(2026, 6, 30),
        "GBP",
        "England and Wales",
        ("Materiality remains subject to transaction-team review.",),
    )


def build_m3_financial_findings() -> tuple[FinancialFindingOutput, ...]:
    """Build authoritative M3 outputs consumed, but never recalculated, by the specialist."""

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
    return FinancialFindingService().generate(
        engagement_id=ENGAGEMENT_ID,
        reconciliations=(reconciliation,),
        concentration=customer_concentration(case.customers),
        bridge=bridge,
        nwc_trend=analyze_nwc_trend(case.working_capital),
        net_debt=calculate_adjusted_net_debt(case.net_debt_items),
    )
