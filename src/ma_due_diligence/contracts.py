"""Minimal provider and analyzer interfaces reserved for later milestones."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ma_due_diligence.domain import (
    DiligenceEngagement,
    DiligenceFact,
    DiligenceFinding,
    DiligenceWorkstream,
    DocumentType,
    EvidenceReference,
    FactConflict,
    VdrDocument,
)
from ma_due_diligence.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class DocumentClassification:
    document_id: str
    document_type: DocumentType
    workstreams: tuple[DiligenceWorkstream, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not self.document_id.strip() or not self.rationale.strip():
            raise DomainValidationError("classification requires document ID and rationale")
        if not self.workstreams or len(set(self.workstreams)) != len(self.workstreams):
            raise DomainValidationError("classification workstreams must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class EvidenceQuery:
    engagement_id: str
    query: str
    workstreams: tuple[DiligenceWorkstream, ...] = ()
    document_types: tuple[DocumentType, ...] = ()
    document_ids: tuple[str, ...] = ()
    limit: int = 10

    def __post_init__(self) -> None:
        if not self.engagement_id.strip() or not self.query.strip():
            raise DomainValidationError("evidence query requires engagement ID and query text")
        if self.limit < 1:
            raise DomainValidationError("evidence query limit must be positive")


@dataclass(frozen=True, slots=True)
class TableExtractionCandidate:
    document_id: str
    page_number: int
    table_label: str | None
    evidence: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise DomainValidationError("table candidate requires document ID")
        if self.page_number < 1:
            raise DomainValidationError("table candidate page number must be positive")
        if self.table_label is not None and not self.table_label.strip():
            raise DomainValidationError("table label must not be blank")


class DocumentIngestionProvider(Protocol):
    """Future boundary that registers one source as a VDR document."""

    def ingest(self, engagement: DiligenceEngagement, source_reference: str) -> VdrDocument: ...


class DocumentClassifier(Protocol):
    """Future AI-assisted document classification boundary."""

    def classify(self, document: VdrDocument) -> DocumentClassification: ...


class EvidenceRetriever(Protocol):
    """Future retrieval boundary with metadata filters."""

    def search(self, query: EvidenceQuery) -> tuple[EvidenceReference, ...]: ...


class TableExtractionAdapter(Protocol):
    """Future provider-neutral table extraction boundary."""

    def extract(self, document: VdrDocument) -> tuple[TableExtractionCandidate, ...]: ...


class SpecialistDiligenceAnalyzer(Protocol):
    """Common contract for later financial, commercial, legal, and operational analyzers."""

    @property
    def workstream(self) -> DiligenceWorkstream: ...

    def analyze(
        self,
        engagement: DiligenceEngagement,
        facts: tuple[DiligenceFact, ...],
        evidence: tuple[EvidenceReference, ...],
    ) -> tuple[DiligenceFinding, ...]: ...


class CrossDocumentVerifier(Protocol):
    """Future semantic and deterministic cross-document comparison boundary."""

    def compare(self, facts: tuple[DiligenceFact, ...]) -> tuple[FactConflict, ...]: ...
