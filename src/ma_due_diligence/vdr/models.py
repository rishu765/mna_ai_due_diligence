"""VDR parsing, chunking, corpus, and ingestion contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ma_due_diligence.contracts import DocumentClassification
from ma_due_diligence.domain import (
    DiligenceWorkstream,
    DocumentType,
    EntityReference,
    FinancialPeriod,
    VdrDocument,
)
from ma_due_diligence.errors import DomainValidationError


class DocumentFormat(StrEnum):
    PDF = "pdf"
    TEXT = "text"
    MARKDOWN = "markdown"
    CSV = "csv"
    XLSX = "xlsx"
    HTML = "html"


class ElementKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CLAUSE = "clause"
    TABLE_ROW = "table_row"
    SHEET_ROW = "sheet_row"


class IngestionIssueCode(StrEnum):
    DUPLICATE_DOCUMENT = "duplicate_document"
    PARSE_FAILED = "parse_failed"
    PARTIAL_PARSE = "partial_parse"
    UNSUPPORTED_FORMAT = "unsupported_format"
    EMPTY_DOCUMENT = "empty_document"
    MANIFEST_ERROR = "manifest_error"


@dataclass(frozen=True, slots=True)
class ParsedElement:
    element_id: str
    kind: ElementKind
    text: str
    page_number: int | None = None
    physical_page_index: int | None = None
    section: str | None = None
    clause_number: str | None = None
    table_id: str | None = None
    sheet_name: str | None = None
    row_number: int | None = None
    cell_range: str | None = None
    nearby_context: str | None = None

    def __post_init__(self) -> None:
        if not self.element_id.strip() or not self.text.strip():
            raise DomainValidationError("parsed element requires ID and text")
        if (self.page_number is None) != (self.physical_page_index is None):
            raise DomainValidationError("page number and physical index must appear together")
        if self.page_number is not None and (
            self.page_number < 1 or self.physical_page_index != self.page_number - 1
        ):
            raise DomainValidationError("page numbering must be positive and index-aligned")
        if self.row_number is not None and self.row_number < 1:
            raise DomainValidationError("row number must be positive")
        if self.cell_range is not None and self.row_number is None:
            raise DomainValidationError("cell range requires row provenance")


@dataclass(frozen=True, slots=True)
class ParsedVdrDocument:
    document: VdrDocument
    document_format: DocumentFormat
    elements: tuple[ParsedElement, ...]
    page_count: int | None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.elements:
            raise DomainValidationError("parsed document requires at least one element")
        if self.page_count is not None and self.page_count < 1:
            raise DomainValidationError("page count must be positive")
        ids = [element.element_id for element in self.elements]
        if len(ids) != len(set(ids)):
            raise DomainValidationError("parsed element IDs must be unique")


@dataclass(frozen=True, slots=True)
class DiligenceChunk:
    chunk_id: str
    engagement_id: str
    document_id: str
    chunk_index: int
    text: str
    document_type: DocumentType
    workstreams: tuple[DiligenceWorkstream, ...]
    source_path: str
    page_numbers: tuple[int, ...] = ()
    physical_page_indexes: tuple[int, ...] = ()
    section: str | None = None
    clause_number: str | None = None
    table_id: str | None = None
    sheet_name: str | None = None
    row_numbers: tuple[int, ...] = ()
    cell_range: str | None = None
    period: FinancialPeriod | None = None
    entity: EntityReference | None = None
    content_fingerprint: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.chunk_id, "chunk_id"),
            (self.engagement_id, "engagement_id"),
            (self.document_id, "document_id"),
            (self.text, "text"),
            (self.source_path, "source_path"),
            (self.content_fingerprint, "content_fingerprint"),
        ):
            if not value.strip():
                raise DomainValidationError(f"{name} must not be blank")
        if self.chunk_index < 0:
            raise DomainValidationError("chunk index must be non-negative")
        if not self.workstreams or len(set(self.workstreams)) != len(self.workstreams):
            raise DomainValidationError("chunk workstreams must be non-empty and unique")
        if len(self.page_numbers) != len(self.physical_page_indexes):
            raise DomainValidationError("page numbers and indexes must align")
        if any(
            index != page - 1
            for page, index in zip(self.page_numbers, self.physical_page_indexes, strict=True)
        ):
            raise DomainValidationError("chunk page indexes must be zero based")


@dataclass(frozen=True, slots=True)
class DuplicateDocument:
    checksum_sha256: str
    retained_document_id: str
    duplicate_source_path: str


@dataclass(frozen=True, slots=True)
class DocumentVersionSet:
    logical_name: str
    document_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.document_ids) < 2:
            raise DomainValidationError("version set requires at least two documents")


@dataclass(frozen=True, slots=True)
class IngestionIssue:
    code: IngestionIssueCode
    source_path: str
    message: str
    recoverable: bool = True

    def __post_init__(self) -> None:
        if not self.source_path.strip() or not self.message.strip():
            raise DomainValidationError("ingestion issue requires source and message")


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    source_path: str
    document_type: DocumentType | None = None
    workstreams: tuple[DiligenceWorkstream, ...] = ()
    title: str | None = None
    entity: EntityReference | None = None
    period: FinancialPeriod | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.source_path.strip():
            raise DomainValidationError("manifest source path must not be blank")


@dataclass(frozen=True, slots=True)
class VdrManifest:
    engagement_id: str
    entries: tuple[ManifestEntry, ...]

    def __post_init__(self) -> None:
        if not self.engagement_id.strip() or not self.entries:
            raise DomainValidationError("manifest requires engagement ID and entries")


@dataclass(frozen=True, slots=True)
class IngestionRequest:
    engagement_id: str
    folder: Path | None = None
    files: tuple[Path, ...] = ()
    manifest: VdrManifest | None = None

    def __post_init__(self) -> None:
        if not self.engagement_id.strip():
            raise DomainValidationError("ingestion request requires engagement ID")
        modes = sum(value is not None for value in (self.folder, self.manifest)) + bool(self.files)
        if modes != 1:
            raise DomainValidationError("provide exactly one folder, file list, or manifest")
        if self.manifest is not None and self.manifest.engagement_id != self.engagement_id:
            raise DomainValidationError("manifest and request engagement IDs must match")


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    document: VdrDocument
    classification: DocumentClassification
    parsed: ParsedVdrDocument
    chunks: tuple[DiligenceChunk, ...]


@dataclass(frozen=True, slots=True)
class VdrCorpus:
    engagement_id: str
    documents: tuple[IngestedDocument, ...]
    duplicates: tuple[DuplicateDocument, ...] = ()
    versions: tuple[DocumentVersionSet, ...] = ()
    issues: tuple[IngestionIssue, ...] = ()

    @property
    def chunks(self) -> tuple[DiligenceChunk, ...]:
        return tuple(chunk for document in self.documents for chunk in document.chunks)
