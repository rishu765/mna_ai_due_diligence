"""Transparent weighted hybrid retrieval and cross-document grouping."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from ma_due_diligence.errors import RetrievalError
from ma_due_diligence.retrieval.index import InMemoryDiligenceIndex
from ma_due_diligence.retrieval.models import (
    CrossDocumentResponse,
    DiligenceEvidenceResult,
    RetrievalFilters,
    RetrievalResponse,
    RetrievalWarning,
    RetrievalWarningCode,
    SourceEvidenceGroup,
    evidence_from_chunk,
)
from ma_due_diligence.vdr.models import DiligenceChunk, IngestionIssue, IngestionIssueCode

_VALUE_PATTERN = re.compile(
    r"(?:(?:GBP|USD|EUR|£|\$)\s*)?([0-9]+(?:\.[0-9]+)?)\s*(million|mn|m|%)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class HybridRetrievalConfig:
    semantic_weight: float = 0.55
    lexical_weight: float = 0.45
    minimum_fused_score: float = 0.08
    weak_match_threshold: float = 0.22

    def __post_init__(self) -> None:
        if abs(self.semantic_weight + self.lexical_weight - 1.0) > 1e-9:
            raise ValueError("hybrid weights must sum to one")
        if min(self.semantic_weight, self.lexical_weight, self.minimum_fused_score) < 0:
            raise ValueError("retrieval weights and thresholds must be non-negative")


class HybridDiligenceRetriever:
    def __init__(
        self,
        index: InMemoryDiligenceIndex,
        *,
        config: HybridRetrievalConfig | None = None,
        ingestion_issues: tuple[IngestionIssue, ...] = (),
    ) -> None:
        self._index = index
        self._config = config or HybridRetrievalConfig()
        self._ingestion_issues = ingestion_issues

    def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        top_k: int = 5,
    ) -> RetrievalResponse:
        if not query.strip():
            raise RetrievalError("query must not be blank")
        if top_k < 1:
            raise RetrievalError("top_k must be positive")
        semantic = self._index.semantic_search(query, filters)
        lexical = self._index.lexical_search(query, filters)
        semantic_scores = {item.chunk.chunk_id: max(0.0, item.score) for item in semantic}
        lexical_scores = {item.chunk.chunk_id: max(0.0, item.score) for item in lexical}
        chunks = {item.chunk.chunk_id: item.chunk for item in (*semantic, *lexical)}
        max_lexical = max(lexical_scores.values(), default=0.0)
        ranked: list[tuple[float, float, float, DiligenceChunk]] = []
        for chunk_id, chunk in chunks.items():
            semantic_score = semantic_scores.get(chunk_id, 0.0)
            lexical_score = lexical_scores.get(chunk_id, 0.0)
            normalized_lexical = lexical_score / max_lexical if max_lexical else 0.0
            fused = (
                self._config.semantic_weight * semantic_score
                + self._config.lexical_weight * normalized_lexical
            )
            if fused >= self._config.minimum_fused_score:
                ranked.append((fused, semantic_score, lexical_score, chunk))
        ranked.sort(key=lambda item: (-item[0], item[3].chunk_id))

        unique_ranked = []
        fingerprints: set[str] = set()
        duplicate_removed = False
        for item in ranked:
            chunk = item[3]
            fingerprint = chunk.content_fingerprint
            if fingerprint in fingerprints:
                duplicate_removed = True
                continue
            fingerprints.add(fingerprint)
            unique_ranked.append(item)
        results = tuple(
            DiligenceEvidenceResult(
                query,
                rank,
                chunk.engagement_id,
                chunk.document_id,
                chunk.source_path,
                chunk.document_type,
                chunk.workstreams,
                chunk.chunk_id,
                semantic_score,
                lexical_score,
                fused,
                chunk.text,
                evidence_from_chunk(chunk),
            )
            for rank, (fused, semantic_score, lexical_score, chunk) in enumerate(
                unique_ranked[:top_k], start=1
            )
        )
        warnings = self._warnings(query, results, filters, duplicate_removed)
        return RetrievalResponse(query, filters.engagement_id, results, warnings)

    def retrieve_grouped(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        top_k: int = 10,
    ) -> CrossDocumentResponse:
        response = self.retrieve(query, filters=filters, top_k=top_k)
        grouped: dict[str, list[DiligenceEvidenceResult]] = defaultdict(list)
        for result in response.results:
            grouped[result.document_id].append(result)
        groups = tuple(
            SourceEvidenceGroup(document_id, values[0].document_type, tuple(values))
            for document_id, values in grouped.items()
        )
        return CrossDocumentResponse(query, groups, response.warnings)

    def _warnings(
        self,
        query: str,
        results: tuple[DiligenceEvidenceResult, ...],
        filters: RetrievalFilters,
        duplicate_removed: bool,
    ) -> tuple[RetrievalWarning, ...]:
        warnings: list[RetrievalWarning] = []
        if not results:
            warnings.append(
                RetrievalWarning(
                    RetrievalWarningCode.NO_EVIDENCE, "No evidence met the retrieval threshold."
                )
            )
            broad = RetrievalFilters(filters.engagement_id)
            broad_semantic = self._index.semantic_search(query, broad)
            if broad_semantic and filters.workstreams:
                warnings.append(
                    RetrievalWarning(
                        RetrievalWarningCode.WRONG_WORKSTREAM,
                        "Potential matches exist outside the requested workstream.",
                    )
                )
            if broad_semantic and filters.period_labels:
                warnings.append(
                    RetrievalWarning(
                        RetrievalWarningCode.STALE_PERIOD,
                        "Potential matches exist outside the requested period.",
                    )
                )
        elif results[0].fused_score < self._config.weak_match_threshold:
            warnings.append(
                RetrievalWarning(
                    RetrievalWarningCode.WEAK_MATCHES, "Only weak evidence matches were found."
                )
            )
        if results and len({result.document_id for result in results}) == 1:
            warnings.append(
                RetrievalWarning(
                    RetrievalWarningCode.SINGLE_SOURCE,
                    "Retrieved evidence comes from only one source document.",
                )
            )
        if _conflicting_contexts(query, results):
            warnings.append(
                RetrievalWarning(
                    RetrievalWarningCode.CONFLICTING_CONTEXTS,
                    "Retrieved source contexts contain different relevant values; "
                    "no value was resolved.",
                )
            )
        if duplicate_removed:
            warnings.append(
                RetrievalWarning(
                    RetrievalWarningCode.DUPLICATE_EVIDENCE,
                    "Near-identical chunk evidence was deduplicated.",
                )
            )
        parse_codes = {
            IngestionIssueCode.PARSE_FAILED,
            IngestionIssueCode.EMPTY_DOCUMENT,
            IngestionIssueCode.UNSUPPORTED_FORMAT,
        }
        if any(issue.code in parse_codes for issue in self._ingestion_issues):
            warnings.append(
                RetrievalWarning(
                    RetrievalWarningCode.PARSE_FAILURES_PRESENT,
                    "Some VDR documents could not be parsed or were unsupported.",
                )
            )
        return tuple(warnings)


def _conflicting_contexts(query: str, results: tuple[DiligenceEvidenceResult, ...]) -> bool:
    if len({result.document_id for result in results}) < 2:
        return False
    query_terms = query.casefold()
    if not any(term in query_terms for term in ("revenue", "ebitda", "debt", "concentration")):
        return False
    values = {
        (value, unit.casefold())
        for result in results
        for value, unit in _VALUE_PATTERN.findall(result.text)
    }
    return len(values) > 1
