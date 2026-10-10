from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ma_due_diligence.domain import DiligenceWorkstream, DocumentType, EntityReference
from ma_due_diligence.retrieval import (
    DeterministicHashEmbedder,
    HybridDiligenceRetriever,
    InMemoryDiligenceIndex,
    RagContextBuilder,
    RetrievalFilters,
)
from ma_due_diligence.retrieval.evaluation import evaluate_retrieval
from ma_due_diligence.retrieval.models import RetrievalWarningCode
from ma_due_diligence.vdr.ingestion import VdrIngestionPipeline, manifest_from_json
from ma_due_diligence.vdr.models import DiligenceChunk, IngestionRequest, VdrCorpus
from ma_due_diligence.vdr_fixtures import create_fixture_vdr


@pytest.fixture
def retrieval_stack(
    tmp_path: Path,
) -> tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever]:
    manifest_path = create_fixture_vdr(tmp_path)
    manifest = manifest_from_json(manifest_path)
    corpus = VdrIngestionPipeline().ingest(
        IngestionRequest(manifest.engagement_id, manifest=manifest)
    )
    index = InMemoryDiligenceIndex(DeterministicHashEmbedder())
    index.index(corpus.chunks, rebuild=True)
    return corpus, index, HybridDiligenceRetriever(index, ingestion_issues=corpus.issues)


def test_index_lifecycle_is_idempotent_and_rebuildable(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, index, _ = retrieval_stack
    duplicate = index.index(corpus.chunks)
    rebuilt = index.index(corpus.chunks, rebuild=True)
    assert duplicate.chunks_indexed == 0
    assert duplicate.duplicate_chunks == len(corpus.chunks)
    assert rebuilt.rebuilt is True
    assert index.count == len(corpus.chunks)


def test_lexical_retrieval_finds_exact_clause(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, index, _ = retrieval_stack
    matches = index.lexical_search(
        "change of control termination",
        RetrievalFilters(corpus.engagement_id),
    )
    assert "Change of Control" in matches[0].chunk.text


def test_semantic_retrieval_uses_offline_synonym_normalization(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, index, _ = retrieval_stack
    matches = index.semantic_search(
        "FY2025 turnover",
        RetrievalFilters(corpus.engagement_id),
    )
    assert any("Revenue" in match.chunk.text for match in matches[:5])


def test_hybrid_retrieval_returns_scored_evidence_and_lineage(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, _, retriever = retrieval_stack
    response = retriever.retrieve(
        "Which customers represent more than 10% of revenue?",
        filters=RetrievalFilters(corpus.engagement_id),
        top_k=5,
    )
    apex = next(result for result in response.results if "Apex Retail" in result.text)
    assert apex.semantic_score >= 0
    assert apex.lexical_score > 0
    assert apex.fused_score > 0
    assert apex.evidence.document_id == apex.document_id
    assert apex.evidence.chunk_id == apex.chunk_id
    assert apex.evidence.row == "2"
    assert apex.evidence.cell_range == "A2:C2"


def test_metadata_filters_cover_type_workstream_period_sheet_and_document(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, _, retriever = retrieval_stack
    management = next(
        item
        for item in corpus.documents
        if item.document.document_type is DocumentType.MANAGEMENT_ACCOUNTS
    )
    filters = RetrievalFilters(
        corpus.engagement_id,
        document_ids=(management.document.document_id,),
        document_types=(DocumentType.MANAGEMENT_ACCOUNTS,),
        workstreams=(DiligenceWorkstream.FINANCIAL,),
        period_labels=("FY2025",),
        sheet_names=("Monthly P&L",),
    )
    response = retriever.retrieve("December revenue", filters=filters, top_k=10)
    assert response.results
    assert all(result.document_id == management.document.document_id for result in response.results)
    assert all(result.evidence.sheet_name == "Monthly P&L" for result in response.results)


def test_entity_filter_is_enforced() -> None:
    from ma_due_diligence.retrieval.index import InMemoryDiligenceIndex

    embedder = DeterministicHashEmbedder()
    index = InMemoryDiligenceIndex(embedder)
    fixture_chunk = _minimal_chunk()
    target = EntityReference("target-1", "Target One")
    index.index((replace(fixture_chunk, entity=target),))
    assert index.semantic_search("revenue", RetrievalFilters("eng-1", entity_ids=("target-1",)))
    assert not index.semantic_search("revenue", RetrievalFilters("eng-1", entity_ids=("other",)))


def test_page_filter_is_enforced(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, _, retriever = retrieval_stack
    audited = next(
        item
        for item in corpus.documents
        if item.document.document_type is DocumentType.FINANCIAL_STATEMENTS
    )
    response = retriever.retrieve(
        "revenue",
        filters=RetrievalFilters(
            corpus.engagement_id,
            document_ids=(audited.document.document_id,),
            page_numbers=(2,),
        ),
    )
    assert response.results
    assert all(result.evidence.page_numbers == (2,) for result in response.results)


def test_cross_document_retrieval_groups_sources_and_surfaces_conflict(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, _, retriever = retrieval_stack
    response = retriever.retrieve_grouped(
        "What does each document say about FY2025 revenue?",
        filters=RetrievalFilters(corpus.engagement_id),
        top_k=20,
    )
    filenames = {Path(group.results[0].source_path).name for group in response.groups}
    assert "01_audited_financial_statements_FY2025.pdf" in filenames
    assert "03_customer_sales_report_FY2025.csv" in filenames
    assert len(response.groups) >= 3
    assert RetrievalWarningCode.CONFLICTING_CONTEXTS in {
        warning.code for warning in response.warnings
    }


def test_no_evidence_and_parse_failure_signals(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, _, retriever = retrieval_stack
    response = retriever.retrieve(
        "orbital satellite insurance",
        filters=RetrievalFilters(corpus.engagement_id, document_ids=("missing",)),
    )
    codes = {warning.code for warning in response.warnings}
    assert not response.results
    assert RetrievalWarningCode.NO_EVIDENCE in codes
    assert RetrievalWarningCode.PARSE_FAILURES_PRESENT in codes


def test_context_builder_is_bounded_and_preserves_citations(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, _, retriever = retrieval_stack
    context = RagContextBuilder(retriever, max_characters=700).build(
        "management EBITDA adjustment",
        filters=RetrievalFilters(corpus.engagement_id),
        top_k=10,
    )
    assert context.text is not None and len(context.text) <= 700
    assert context.evidence
    assert len(context.evidence) == len(context.results)
    assert "[1]" in context.text


def test_retrieval_benchmark(
    retrieval_stack: tuple[VdrCorpus, InMemoryDiligenceIndex, HybridDiligenceRetriever],
) -> None:
    corpus, _, retriever = retrieval_stack
    dataset = Path(__file__).parents[1] / "evaluation" / "retrieval_cases.json"
    report = evaluate_retrieval(
        retriever,
        engagement_id=corpus.engagement_id,
        dataset_path=dataset,
        top_k=5,
    )
    assert report.case_count == 7
    assert report.hit_at_k == 1.0
    assert report.recall_at_k >= 0.85
    assert report.mean_reciprocal_rank >= 0.75
    assert report.metadata_filter_correctness == 1.0
    assert report.narrative_hit_at_k == 1.0
    assert report.table_hit_at_k == 1.0


def _minimal_chunk() -> DiligenceChunk:
    return DiligenceChunk(
        "chunk-1",
        "eng-1",
        "doc-1",
        0,
        "Revenue was GBP 10 million.",
        DocumentType.FINANCIAL_STATEMENTS,
        (DiligenceWorkstream.FINANCIAL,),
        "fixture.txt",
        content_fingerprint="abc",
    )
