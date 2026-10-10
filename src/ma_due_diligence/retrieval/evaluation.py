"""Small transparent offline retrieval benchmark."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ma_due_diligence.domain import DiligenceWorkstream, DocumentType
from ma_due_diligence.errors import DomainValidationError
from ma_due_diligence.retrieval.models import RetrievalFilters
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationCase:
    case_id: str
    category: str
    query: str
    expected_sources: tuple[str, ...]
    document_types: tuple[DocumentType, ...] = ()
    workstreams: tuple[DiligenceWorkstream, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    hit: bool
    recall: float
    reciprocal_rank: float
    top_source_correct: bool
    metadata_filter_correct: bool


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationReport:
    dataset: str
    case_count: int
    top_k: int
    hit_at_k: float
    recall_at_k: float
    mean_reciprocal_rank: float
    source_correctness: float
    metadata_filter_correctness: float
    narrative_hit_at_k: float
    table_hit_at_k: float
    cases: tuple[CaseResult, ...]


def load_cases(path: Path) -> tuple[str, tuple[RetrievalEvaluationCase, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise DomainValidationError("evaluation dataset requires cases")
    dataset = str(payload.get("dataset", "unnamed"))
    cases = []
    for raw_value in cast(list[object], payload["cases"]):
        if not isinstance(raw_value, dict):
            raise DomainValidationError("evaluation case must be an object")
        raw = cast(dict[str, object], raw_value)
        expected = _string_tuple(raw.get("expected_sources"), "expected_sources")
        cases.append(
            RetrievalEvaluationCase(
                str(raw["case_id"]),
                str(raw["category"]),
                str(raw["query"]),
                expected,
                tuple(
                    DocumentType(value)
                    for value in _string_tuple(raw.get("document_types", []), "document_types")
                ),
                tuple(
                    DiligenceWorkstream(value)
                    for value in _string_tuple(raw.get("workstreams", []), "workstreams")
                ),
            )
        )
    return dataset, tuple(cases)


def evaluate_retrieval(
    retriever: HybridDiligenceRetriever,
    *,
    engagement_id: str,
    dataset_path: Path,
    top_k: int = 5,
) -> RetrievalEvaluationReport:
    dataset, cases = load_cases(dataset_path)
    results: list[CaseResult] = []
    categories: dict[str, list[bool]] = {}
    for case in cases:
        filters = RetrievalFilters(
            engagement_id,
            document_types=case.document_types,
            workstreams=case.workstreams,
        )
        response = retriever.retrieve(case.query, filters=filters, top_k=top_k)
        sources = [Path(result.source_path).name for result in response.results]
        expected = set(case.expected_sources)
        relevant_ranks = [
            rank for rank, source in enumerate(sources, start=1) if source in expected
        ]
        found = expected & set(sources)
        hit = bool(found)
        metadata_correct = all(
            (not case.document_types or result.document_type in case.document_types)
            and (not case.workstreams or bool(set(result.workstreams) & set(case.workstreams)))
            for result in response.results
        )
        results.append(
            CaseResult(
                case.case_id,
                hit,
                len(found) / len(expected),
                0.0 if not relevant_ranks else 1.0 / min(relevant_ranks),
                bool(sources and sources[0] in expected),
                metadata_correct,
            )
        )
        categories.setdefault(case.category, []).append(hit)
    count = len(results)
    if count == 0:
        raise DomainValidationError("evaluation dataset must not be empty")
    return RetrievalEvaluationReport(
        dataset,
        count,
        top_k,
        sum(item.hit for item in results) / count,
        sum(item.recall for item in results) / count,
        sum(item.reciprocal_rank for item in results) / count,
        sum(item.top_source_correct for item in results) / count,
        sum(item.metadata_filter_correct for item in results) / count,
        _rate(categories.get("narrative", [])),
        _rate(categories.get("table", [])),
        tuple(results),
    )


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DomainValidationError(f"{name} must be a list of strings")
    return tuple(cast(list[str], value))


def _rate(values: list[bool]) -> float:
    return 0.0 if not values else sum(values) / len(values)
