"""Synthetic Northstar financial diligence case with explicit evidence lineage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from ma_due_diligence.domain import (
    AdjustmentDirection,
    AdjustmentType,
    AnalystDecision,
    DocumentType,
    EvidenceReference,
    EvidenceSourceType,
    FinancialAdjustment,
    FinancialPeriod,
    Money,
    PeriodKind,
    ProposalStatus,
    Recurrence,
    SupportStatus,
)
from ma_due_diligence.financial.models import (
    ClassificationStatus,
    CustomerRevenue,
    FinancialMetric,
    FinancialObservation,
    FinancialUnit,
    MetricBasis,
    NetDebtCategory,
    NetDebtItem,
    ReportingStatus,
    WorkingCapitalPeriod,
)
from ma_due_diligence.vdr_fixtures import create_fixture_vdr

ENGAGEMENT_ID = "eng-northstar-vdr"


@dataclass(frozen=True, slots=True)
class FinancialFixtureCase:
    observations: tuple[FinancialObservation, ...]
    adjustments: tuple[FinancialAdjustment, ...]
    customers: tuple[CustomerRevenue, ...]
    working_capital: tuple[WorkingCapitalPeriod, ...]
    net_debt_items: tuple[NetDebtItem, ...]


def create_financial_fixture_vdr(root: Path) -> Path:
    manifest_path = create_fixture_vdr(root)
    (root / "11_audited_financial_history_FY2023_FY2025.csv").write_text(
        "Metric,FY2023,FY2024,FY2025\n"
        "Revenue GBP m,80.0,86.0,92.0\n"
        "Gross Profit GBP m,30.0,,33.12\n"
        "EBITDA GBP m,11.0,12.0,14.0\n",
        encoding="utf-8",
    )
    (root / "12_management_ebitda_bridge.csv").write_text(
        "Period,Adjustment,Amount GBP m,Management treatment\n"
        "FY2024,Legal and professional fees,2.0,One-time add-back\n"
        "FY2025,Legal and professional fees,2.0,One-time add-back\n"
        "FY2025,ERP implementation costs,1.0,One-time add-back\n",
        encoding="utf-8",
    )
    wc_rows = [
        "Period,Accounts Receivable GBP m,Inventory GBP m,Accounts Payable GBP m",
        "2025-01,10.0,6.0,8.0",
        "2025-02,10.5,6.1,8.2",
        "2025-03,10.8,6.2,8.3",
        "2025-04,11.0,6.3,8.5",
        "2025-05,11.2,6.4,8.6",
        "2025-06,11.4,6.5,8.7",
        "2025-07,11.5,6.6,8.8",
        "2025-08,11.6,6.7,8.9",
        "2025-09,11.7,,9.0",
        "2025-10,11.8,6.8,9.1",
        "2025-11,11.9,6.9,9.2",
        "2025-12,14.5,7.0,9.0",
    ]
    (root / "13_working_capital_history_FY2025.csv").write_text(
        "\n".join(wc_rows) + "\n", encoding="utf-8"
    )
    (root / "14_bank_cash_balances_FY2025.csv").write_text(
        "Account,Balance GBP m,Availability\n"
        "Operating account,6.0,Unrestricted\n"
        "Debt service reserve,2.0,Restricted\n"
        "Treasury deposit,0.5,Short-term liquid\n",
        encoding="utf-8",
    )
    (root / "15_debt_like_items_FY2025.csv").write_text(
        "Item,Amount GBP m,Management classification\n"
        "Accrued transaction fees,1.5,Excluded from net debt\n",
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    known = {item["path"] for item in manifest["documents"]}
    for path in sorted(root.iterdir()):
        if path.name != manifest_path.name and path.name not in known:
            manifest["documents"].append({"path": path.name})
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def build_financial_fixture_case() -> FinancialFixtureCase:
    fy2023 = FinancialPeriod(PeriodKind.FISCAL_YEAR, "FY2023", date(2023, 1, 1), date(2023, 12, 31))
    fy2024 = FinancialPeriod(PeriodKind.FISCAL_YEAR, "FY2024", date(2024, 1, 1), date(2024, 12, 31))
    fy2025 = FinancialPeriod(PeriodKind.FISCAL_YEAR, "FY2025", date(2025, 1, 1), date(2025, 12, 31))
    audited = _evidence("ev-audited", "doc-audited", fy2025, "Audited financial statements")
    management = _evidence("ev-management", "doc-management", fy2025, "Management accounts")
    deck = _evidence("ev-deck", "doc-deck", fy2025, "Management presentation")
    sales = _evidence("ev-sales", "doc-sales", fy2025, "Sales by customer")
    bridge = _evidence("ev-bridge", "doc-bridge", fy2025, "Management EBITDA bridge")
    wc_evidence = _evidence("ev-wc", "doc-wc", fy2025, "Working capital history")
    debt_evidence = _evidence("ev-debt", "doc-debt", fy2025, "Debt schedule")
    cash_evidence = _evidence("ev-cash", "doc-cash", fy2025, "Bank cash schedule")
    debt_like_evidence = _evidence("ev-debt-like", "doc-debt-like", fy2025, "Debt-like schedule")
    observations = (
        _observation(
            "rev-23",
            FinancialMetric.REVENUE,
            "80",
            fy2023,
            DocumentType.FINANCIAL_STATEMENTS,
            audited,
        ),
        _observation(
            "ebitda-23",
            FinancialMetric.EBITDA,
            "11",
            fy2023,
            DocumentType.FINANCIAL_STATEMENTS,
            audited,
        ),
        _observation(
            "rev-24",
            FinancialMetric.REVENUE,
            "86",
            fy2024,
            DocumentType.FINANCIAL_STATEMENTS,
            audited,
        ),
        _observation(
            "ebitda-24",
            FinancialMetric.EBITDA,
            "12",
            fy2024,
            DocumentType.FINANCIAL_STATEMENTS,
            audited,
        ),
        _observation(
            "rev-audited-25",
            FinancialMetric.REVENUE,
            "92",
            fy2025,
            DocumentType.FINANCIAL_STATEMENTS,
            audited,
        ),
        _observation(
            "gp-audited-25",
            FinancialMetric.GROSS_PROFIT,
            "33.12",
            fy2025,
            DocumentType.FINANCIAL_STATEMENTS,
            audited,
        ),
        _observation(
            "ebitda-audited-25",
            FinancialMetric.EBITDA,
            "14",
            fy2025,
            DocumentType.FINANCIAL_STATEMENTS,
            audited,
        ),
        _observation(
            "rev-management-25",
            FinancialMetric.REVENUE,
            "95",
            fy2025,
            DocumentType.MANAGEMENT_ACCOUNTS,
            management,
        ),
        _observation(
            "rev-sales-25", FinancialMetric.REVENUE, "95", fy2025, DocumentType.SALES_REPORT, sales
        ),
        _observation(
            "rev-deck-25",
            FinancialMetric.REVENUE,
            "100",
            fy2025,
            DocumentType.MANAGEMENT_PRESENTATION,
            deck,
        ),
        _observation(
            "ebitda-management-25",
            FinancialMetric.EBITDA,
            "14",
            fy2025,
            DocumentType.MANAGEMENT_ACCOUNTS,
            management,
        ),
    )
    adjustments = (
        _adjustment(
            "adj-legal-24",
            "2",
            fy2024,
            "Recurring legal and professional fees",
            bridge,
            ProposalStatus.PROPOSED,
            AnalystDecision.PENDING,
        ),
        _adjustment(
            "adj-legal-25",
            "2",
            fy2025,
            "Recurring legal and professional fees",
            bridge,
            ProposalStatus.PROPOSED,
            AnalystDecision.PENDING,
        ),
        _adjustment(
            "adj-erp-25",
            "1",
            fy2025,
            "Completed ERP implementation costs",
            bridge,
            ProposalStatus.ACCEPTED,
            AnalystDecision.ACCEPT,
        ),
    )
    customers = tuple(
        CustomerRevenue(name, Decimal(value), "GBP", FinancialUnit.MILLION, fy2025, (sales,))
        for name, value in (
            ("Apex", "39.9"),
            ("Beacon", "18.1"),
            ("Cedar", "14.2"),
            ("Delta", "12.0"),
            ("Other", "10.8"),
        )
    )
    wc_values: tuple[tuple[str, str, str | None, str], ...] = (
        ("2025-01", "10.0", "6.0", "8.0"),
        ("2025-02", "10.5", "6.1", "8.2"),
        ("2025-03", "10.8", "6.2", "8.3"),
        ("2025-04", "11.0", "6.3", "8.5"),
        ("2025-05", "11.2", "6.4", "8.6"),
        ("2025-06", "11.4", "6.5", "8.7"),
        ("2025-07", "11.5", "6.6", "8.8"),
        ("2025-08", "11.6", "6.7", "8.9"),
        ("2025-09", "11.7", None, "9.0"),
        ("2025-10", "11.8", "6.8", "9.1"),
        ("2025-11", "11.9", "6.9", "9.2"),
        ("2025-12", "14.5", "7.0", "9.0"),
    )
    working_capital = tuple(
        WorkingCapitalPeriod(
            FinancialPeriod(PeriodKind.MONTH, label),
            Decimal(ar),
            None if inv is None else Decimal(inv),
            Decimal(ap),
            evidence=(wc_evidence,),
        )
        for label, ar, inv, ap in wc_values
    )
    net_debt_items = (
        NetDebtItem(
            "debt",
            "Reported bank debt",
            NetDebtCategory.REPORTED_DEBT,
            Decimal("25"),
            "GBP",
            FinancialUnit.MILLION,
            date(2025, 12, 31),
            ClassificationStatus.ACCEPTED,
            "Debt schedule balance.",
            (debt_evidence,),
        ),
        NetDebtItem(
            "fees",
            "Accrued transaction fees",
            NetDebtCategory.DEBT_LIKE,
            Decimal("1.5"),
            "GBP",
            FinancialUnit.MILLION,
            date(2025, 12, 31),
            ClassificationStatus.ACCEPTED,
            "Transaction-related liability.",
            (debt_like_evidence,),
        ),
        NetDebtItem(
            "cash",
            "Unrestricted operating cash",
            NetDebtCategory.CASH,
            Decimal("6"),
            "GBP",
            FinancialUnit.MILLION,
            date(2025, 12, 31),
            ClassificationStatus.ACCEPTED,
            "Freely available cash.",
            (cash_evidence,),
        ),
        NetDebtItem(
            "restricted",
            "Debt service reserve",
            NetDebtCategory.CASH,
            Decimal("2"),
            "GBP",
            FinancialUnit.MILLION,
            date(2025, 12, 31),
            ClassificationStatus.ACCEPTED,
            "Restricted and unavailable.",
            (cash_evidence,),
            restricted=True,
        ),
        NetDebtItem(
            "deposit",
            "Short-term liquid deposit",
            NetDebtCategory.CASH_LIKE,
            Decimal("0.5"),
            "GBP",
            FinancialUnit.MILLION,
            date(2025, 12, 31),
            ClassificationStatus.ACCEPTED,
            "Liquid deposit available at closing.",
            (cash_evidence,),
        ),
    )
    return FinancialFixtureCase(
        observations, adjustments, customers, working_capital, net_debt_items
    )


def _evidence(
    evidence_id: str, document_id: str, period: FinancialPeriod, text: str
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id,
        EvidenceSourceType.VDR_DOCUMENT,
        document_id=document_id,
        source_text=text,
        period=period,
    )


def _observation(
    observation_id: str,
    metric: FinancialMetric,
    value: str,
    period: FinancialPeriod,
    document_type: DocumentType,
    evidence: EvidenceReference,
) -> FinancialObservation:
    return FinancialObservation(
        observation_id,
        ENGAGEMENT_ID,
        metric,
        Decimal(value),
        "GBP",
        FinancialUnit.MILLION,
        period,
        ReportingStatus.ACTUAL,
        MetricBasis.REPORTED,
        document_type,
        evidence.source_text or document_type.value,
        (evidence,),
        SupportStatus.SOURCE_BACKED,
        "fixture_import",
    )


def _adjustment(
    adjustment_id: str,
    amount: str,
    period: FinancialPeriod,
    rationale: str,
    evidence: EvidenceReference,
    proposal_status: ProposalStatus,
    decision: AnalystDecision,
) -> FinancialAdjustment:
    return FinancialAdjustment(
        adjustment_id,
        ENGAGEMENT_ID,
        AdjustmentType.ONE_TIME_EXPENSE,
        "EBITDA",
        Money(Decimal(amount), "GBP"),
        period,
        AdjustmentDirection.INCREASE,
        Recurrence.NONRECURRING,
        proposal_status,
        rationale,
        (evidence,),
        SupportStatus.VERIFIED,
        decision,
        unit="million",
    )
