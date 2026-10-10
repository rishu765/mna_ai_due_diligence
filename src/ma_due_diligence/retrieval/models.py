"""Metadata filters, evidence results, warnings, and context contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from ma_due_diligence.domain import (
    DiligenceWorkstream,
    DocumentType,
    EvidenceReference,
    EvidenceSourceType,
)
from ma_due_diligence.errors import DomainValidationError
from ma_due_diligence.vdr.models import DiligenceChunk


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    engagement_id: str
    document_ids: tuple[str, ...] = ()
    document_types: tuple[DocumentType, ...] = ()
    workstreams: tuple[DiligenceWorkstream, ...] = ()
    period_labels: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    page_numbers: tuple[int, ...] = ()
    sheet_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.engagement_id.strip():
            raise DomainValidationError("retrieval filters require engagement_id")

    def matches(self, chunk: DiligenceChunk) -> bool:
        period_label = None if chunk.period is None else chunk.period.label.casefold()
        entity_id = None if chunk.entity is None else chunk.entity.entity_id
        return (
            chunk.engagement_id == self.engagement_id
            and (not self.document_ids or chunk.document_id in self.document_ids)
            and (not self.document_types or chunk.document_type in self.document_types)
            and (not self.workstreams or bool(set(chunk.workstreams) & set(self.workstreams)))
            and (
                not self.period_labels
                or period_label in {value.casefold() for value in self.period_labels}
            )
            and (not self.entity_ids or entity_id in self.entity_ids)
            and (not self.page_numbers or bool(set(chunk.page_numbers) & set(self.page_numbers)))
            and (
                not self.sheet_names
                or (
                    chunk.sheet_name is not None
                    and chunk.sheet_name.casefold()
                    in {value.casefold() for value in self.sheet_names}
                )
            )
        )


class RetrievalWarningCode(StrEnum):
    NO_EVIDENCE = "no_evidence"
    WEAK_MATCHES = "weak_matches"
    SINGLE_SOURCE = "single_source"
    CONFLICTING_CONTEXTS = "conflicting_contexts"
    STALE_PERIOD = "stale_period"
    WRONG_WORKSTREAM = "wrong_workstream"
    DUPLICATE_EVIDENCE = "duplicate_evidence"
    PARSE_FAILURES_PRESENT = "parse_failures_present"


@dataclass(frozen=True, slots=True)
class RetrievalWarning:
    code: RetrievalWarningCode
    message: str


@dataclass(frozen=True, slots=True)
class ChannelMatch:
    chunk: DiligenceChunk
    score: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.score):
            raise DomainValidationError("retrieval score must be finite")


@dataclass(frozen=True, slots=True)
class DiligenceEvidenceResult:
    query: str
    rank: int
    engagement_id: str
    document_id: str
    source_path: str
    document_type: DocumentType
    workstreams: tuple[DiligenceWorkstream, ...]
    chunk_id: str
    semantic_score: float
    lexical_score: float
    fused_score: float
    text: str
    evidence: EvidenceReference

    def __post_init__(self) -> None:
        if not self.query.strip() or not self.text.strip():
            raise DomainValidationError("evidence result requires query and text")
        if self.rank < 1:
            raise DomainValidationError("evidence result rank must be positive")
        if any(
            not math.isfinite(value)
            for value in (self.semantic_score, self.lexical_score, self.fused_score)
        ):
            raise DomainValidationError("evidence scores must be finite")


@dataclass(frozen=True, slots=True)
class RetrievalResponse:
    query: str
    engagement_id: str
    results: tuple[DiligenceEvidenceResult, ...]
    warnings: tuple[RetrievalWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceEvidenceGroup:
    document_id: str
    document_type: DocumentType
    results: tuple[DiligenceEvidenceResult, ...]


@dataclass(frozen=True, slots=True)
class CrossDocumentResponse:
    query: str
    groups: tuple[SourceEvidenceGroup, ...]
    warnings: tuple[RetrievalWarning, ...]


@dataclass(frozen=True, slots=True)
class RagContext:
    query: str
    text: str | None
    evidence: tuple[EvidenceReference, ...]
    results: tuple[DiligenceEvidenceResult, ...]
    warnings: tuple[RetrievalWarning, ...]
    truncated: bool


def evidence_from_chunk(chunk: DiligenceChunk) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"retrieval:{chunk.chunk_id}",
        source_type=EvidenceSourceType.VDR_DOCUMENT,
        document_id=chunk.document_id,
        page_numbers=chunk.page_numbers,
        section=chunk.section,
        table=chunk.table_id,
        row=None if not chunk.row_numbers else ",".join(map(str, chunk.row_numbers)),
        chunk_id=chunk.chunk_id,
        source_text=chunk.text,
        period=chunk.period,
        retrieval_context="hybrid VDR retrieval",
        sheet_name=chunk.sheet_name,
        cell_range=chunk.cell_range,
    )
