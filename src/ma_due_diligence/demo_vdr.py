"""Reproducible offline M1/2 VDR ingestion and retrieval demonstration."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from ma_due_diligence.retrieval import (
    DeterministicHashEmbedder,
    HybridDiligenceRetriever,
    InMemoryDiligenceIndex,
    RagContextBuilder,
    RetrievalFilters,
)
from ma_due_diligence.retrieval.evaluation import evaluate_retrieval
from ma_due_diligence.retrieval.models import DiligenceEvidenceResult
from ma_due_diligence.vdr.ingestion import VdrIngestionPipeline, manifest_from_json
from ma_due_diligence.vdr.models import IngestionRequest
from ma_due_diligence.vdr_fixtures import create_fixture_vdr

_QUERIES = (
    "What do the documents say about FY2025 revenue?",
    "Which customers represent more than 10% of revenue?",
    "Are there change of control clauses?",
    "What debt instruments and covenants are outstanding?",
    "What EBITDA adjustments does management propose?",
)


def run_demo() -> dict[str, object]:
    """Create, ingest, index, query, and evaluate the fictitious VDR entirely offline."""

    with tempfile.TemporaryDirectory(prefix="madd-vdr-") as directory:
        root = Path(directory)
        manifest_path = create_fixture_vdr(root)
        manifest = manifest_from_json(manifest_path)
        corpus = VdrIngestionPipeline().ingest(
            IngestionRequest(manifest.engagement_id, manifest=manifest)
        )
        index = InMemoryDiligenceIndex(DeterministicHashEmbedder())
        indexing = index.index(corpus.chunks, rebuild=True)
        retriever = HybridDiligenceRetriever(index, ingestion_issues=corpus.issues)
        filters = RetrievalFilters(corpus.engagement_id)
        queries = {}
        for query in _QUERIES:
            response = retriever.retrieve(query, filters=filters, top_k=5)
            queries[query] = [
                {
                    "source": Path(result.source_path).name,
                    "location": _location(result),
                    "fused_score": round(result.fused_score, 4),
                    "text": result.text,
                }
                for result in response.results
            ]
        revenue = retriever.retrieve_grouped(
            "What does each document say about FY2025 revenue?",
            filters=filters,
            top_k=20,
        )
        context = RagContextBuilder(retriever, max_characters=1800).build(
            "management EBITDA adjustment",
            filters=filters,
        )
        insufficient = retriever.retrieve(
            "What environmental permits expire in 2026?",
            filters=RetrievalFilters(corpus.engagement_id, document_ids=("not-provided",)),
        )
        dataset_path = Path(__file__).parents[2] / "evaluation" / "retrieval_cases.json"
        evaluation = evaluate_retrieval(
            retriever,
            engagement_id=corpus.engagement_id,
            dataset_path=dataset_path,
        )
        return {
            "engagement_id": corpus.engagement_id,
            "documents_ingested": len(corpus.documents),
            "chunks_indexed": indexing.chunks_indexed,
            "duplicates": len(corpus.duplicates),
            "versions": len(corpus.versions),
            "ingestion_issues": [issue.code.value for issue in corpus.issues],
            "queries": queries,
            "revenue_evidence_by_source": {
                Path(group.results[0].source_path).name: [result.text for result in group.results]
                for group in revenue.groups
            },
            "revenue_warnings": [warning.code.value for warning in revenue.warnings],
            "rag_context": context.text,
            "insufficient_evidence": {
                "result_count": len(insufficient.results),
                "warnings": [warning.code.value for warning in insufficient.warnings],
            },
            "evaluation": asdict(evaluation),
        }


def _location(result: DiligenceEvidenceResult) -> str:
    evidence = result.evidence
    if evidence.sheet_name:
        return f"sheet {evidence.sheet_name} {evidence.cell_range or ''}".strip()
    if evidence.page_numbers:
        return "page " + ",".join(map(str, evidence.page_numbers))
    return evidence.section or evidence.cell_range or "document"


def main() -> None:
    print(json.dumps(run_demo(), indent=2, default=str))


if __name__ == "__main__":
    main()
