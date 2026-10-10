from __future__ import annotations

from decimal import Decimal

from ma_due_diligence.demo_financial import run_demo
from ma_due_diligence.financial.evaluation import evaluate_financial_fixture
from ma_due_diligence.financial.extraction import FinancialExtractionService
from ma_due_diligence.financial.fixtures import ENGAGEMENT_ID, create_financial_fixture_vdr
from ma_due_diligence.financial.models import FinancialMetric
from ma_due_diligence.retrieval.context import RagContextBuilder
from ma_due_diligence.retrieval.embedding import DeterministicHashEmbedder
from ma_due_diligence.retrieval.index import InMemoryDiligenceIndex
from ma_due_diligence.retrieval.models import RetrievalFilters
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever
from ma_due_diligence.vdr.ingestion import VdrIngestionPipeline, manifest_from_json
from ma_due_diligence.vdr.models import IngestionRequest


def test_m1_m2_to_m3_retrieval_and_extraction(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = manifest_from_json(create_financial_fixture_vdr(tmp_path))
    corpus = VdrIngestionPipeline().ingest(IngestionRequest(ENGAGEMENT_ID, manifest=manifest))
    index = InMemoryDiligenceIndex(DeterministicHashEmbedder())
    index.index(corpus.chunks, rebuild=True)
    context = RagContextBuilder(HybridDiligenceRetriever(index), max_characters=12000).build(
        "audited FY2025 revenue",
        filters=RetrievalFilters(ENGAGEMENT_ID),
        top_k=10,
    )
    observations = FinancialExtractionService().extract(
        context,
        engagement_id=ENGAGEMENT_ID,
        default_period=manifest.entries[0].period or corpus.documents[0].document.period,  # type: ignore[arg-type]
        default_currency="GBP",
    )
    assert any(item.metric is FinancialMetric.REVENUE for item in observations)
    assert all(item.evidence for item in observations)
    assert any(item.evidence[0].chunk_id is not None for item in observations)


def test_financial_evaluation_reports_categories_separately() -> None:
    report = evaluate_financial_fixture()
    assert report.passed == 11
    assert {item.category for item in report.checks} == {
        "financial_extraction_accuracy",
        "numeric_normalization",
        "reconciliation_correctness",
        "adjustment_classification",
        "ebitda_bridge_correctness",
        "customer_concentration",
        "nwc_calculation",
        "normalized_nwc_peg",
        "net_debt_bridge",
        "finding_generation",
        "evidence_linkage",
    }


def test_offline_financial_demo(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = run_demo(tmp_path)
    assert result["documents"] == 15
    assert result["adjusted_ebitda"] == Decimal("15")
    assert result["largest_customer_percent"] == Decimal("42.00")
    assert result["adjusted_net_debt"] == Decimal("20.0")
    assert result["evaluation"] == "11/11"
