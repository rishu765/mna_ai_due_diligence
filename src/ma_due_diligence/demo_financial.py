"""Deterministic M3 demonstration from VDR retrieval through financial findings."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ma_due_diligence.financial.analytics import (
    analyze_nwc_trend,
    calculate_margin,
    calculate_nwc_peg,
    customer_concentration,
)
from ma_due_diligence.financial.evaluation import evaluate_financial_fixture
from ma_due_diligence.financial.extraction import FinancialExtractionService
from ma_due_diligence.financial.findings import FinancialFindingService, follow_up_questions
from ma_due_diligence.financial.fixtures import (
    ENGAGEMENT_ID,
    build_financial_fixture_case,
    create_financial_fixture_vdr,
)
from ma_due_diligence.financial.models import FinancialMetric, NwcPegMethod
from ma_due_diligence.financial.net_debt import calculate_adjusted_net_debt
from ma_due_diligence.financial.qoe import AdjustmentAssessmentService, build_ebitda_bridge
from ma_due_diligence.financial.reconciliation import FinancialReconciliationService
from ma_due_diligence.retrieval.context import RagContextBuilder
from ma_due_diligence.retrieval.embedding import DeterministicHashEmbedder
from ma_due_diligence.retrieval.index import InMemoryDiligenceIndex
from ma_due_diligence.retrieval.models import RetrievalFilters
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever
from ma_due_diligence.vdr.ingestion import VdrIngestionPipeline, manifest_from_json
from ma_due_diligence.vdr.models import IngestionRequest


def run_demo(root: Path | None = None) -> dict[str, object]:
    workspace = root or Path(tempfile.mkdtemp(prefix="madd-financial-"))
    manifest = manifest_from_json(create_financial_fixture_vdr(workspace))
    corpus = VdrIngestionPipeline().ingest(IngestionRequest(ENGAGEMENT_ID, manifest=manifest))
    index = InMemoryDiligenceIndex(DeterministicHashEmbedder())
    index.index(corpus.chunks, rebuild=True)
    retriever = HybridDiligenceRetriever(index, ingestion_issues=corpus.issues)
    context = RagContextBuilder(retriever, max_characters=12000).build(
        "FY2025 revenue EBITDA gross profit debt cash working capital",
        filters=RetrievalFilters(ENGAGEMENT_ID),
        top_k=20,
    )
    extracted = FinancialExtractionService().extract(
        context,
        engagement_id=ENGAGEMENT_ID,
        default_period=build_financial_fixture_case().observations[4].period,
        default_currency="GBP",
    )
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
    trend = analyze_nwc_trend(case.working_capital)
    peg = calculate_nwc_peg(trend, NwcPegMethod.TRAILING_AVERAGE)
    net_debt = calculate_adjusted_net_debt(case.net_debt_items)
    gross_profit = next(
        item for item in case.observations if item.metric is FinancialMetric.GROSS_PROFIT
    )
    audited_revenue = next(
        item for item in case.observations if item.observation_id == "rev-audited-25"
    )
    gross_margin = calculate_margin(gross_profit, audited_revenue, FinancialMetric.GROSS_MARGIN)
    findings = FinancialFindingService().generate(
        engagement_id=ENGAGEMENT_ID,
        reconciliations=(reconciliation,),
        concentration=concentration,
        bridge=bridge,
        nwc_trend=trend,
        net_debt=net_debt,
    )
    questions = follow_up_questions(ENGAGEMENT_ID, findings)
    evaluation = evaluate_financial_fixture()
    return {
        "documents": len(corpus.documents),
        "retrieved_evidence": len(context.evidence),
        "extracted_observations": len(extracted),
        "revenue_variance": reconciliation.absolute_variance,
        "adjusted_ebitda": bridge.final_adjusted_ebitda,
        "gross_margin": gross_margin.percentage,
        "largest_customer_percent": concentration.largest_customer_percent,
        "current_nwc": trend.results[-1].net_working_capital,
        "normalized_nwc": peg.normalized_nwc,
        "adjusted_net_debt": net_debt.adjusted_net_debt,
        "findings": tuple(item.finding.title for item in findings),
        "follow_up_questions": tuple(item.question for item in questions),
        "evaluation": f"{evaluation.passed}/{len(evaluation.checks)}",
    }


def main() -> None:
    for key, value in run_demo().items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
