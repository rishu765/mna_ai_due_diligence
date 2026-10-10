"""Deterministic offline M4/5 specialist and cross-document investigation demo."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ma_due_diligence.retrieval.embedding import DeterministicHashEmbedder
from ma_due_diligence.retrieval.index import InMemoryDiligenceIndex
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever
from ma_due_diligence.specialists.coordinator import SpecialistCoordinator
from ma_due_diligence.specialists.evaluation import evaluate_specialist_result
from ma_due_diligence.specialists.fixtures import (
    build_m3_financial_findings,
    build_specialist_engagement,
    create_specialist_fixture_vdr,
)
from ma_due_diligence.vdr.ingestion import VdrIngestionPipeline, manifest_from_json
from ma_due_diligence.vdr.models import IngestionRequest


def run_demo(root: Path | None = None) -> dict[str, object]:
    workspace = root or Path(tempfile.mkdtemp(prefix="madd-specialists-"))
    engagement = build_specialist_engagement()
    manifest = manifest_from_json(create_specialist_fixture_vdr(workspace))
    corpus = VdrIngestionPipeline().ingest(
        IngestionRequest(engagement.engagement_id, manifest=manifest)
    )
    index = InMemoryDiligenceIndex(DeterministicHashEmbedder())
    index.index(corpus.chunks, rebuild=True)
    result = SpecialistCoordinator(
        HybridDiligenceRetriever(index, ingestion_issues=corpus.issues)
    ).run(
        engagement=engagement,
        documents=tuple(item.document for item in corpus.documents),
        financial_findings=build_m3_financial_findings(),
    )
    evaluation = evaluate_specialist_result(result)
    return {
        "documents": len(corpus.documents),
        "specialists_completed": tuple(item.agent_id.value for item in result.specialist_results),
        "specialist_errors": tuple(
            f"{item.agent_id.value}: {item.error_type}" for item in result.errors
        ),
        "contradictions": tuple(item.topic for item in result.investigation.conflicts),
        "superseded_claims": result.investigation.superseded_claim_ids,
        "consolidated_findings": tuple(item.finding.title for item in result.findings),
        "compound_risks": tuple(
            item.finding.title
            for item in result.findings
            if item.finding.category == "compound_customer_retention"
        ),
        "information_requests": tuple(item.question for item in result.requests),
        "evaluation": f"{evaluation.passed}/{len(evaluation.checks)}",
    }


def main() -> None:
    for key, value in run_demo().items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
