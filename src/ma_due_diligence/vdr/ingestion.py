"""Partial-failure VDR ingestion from folders, manifests, or explicit files."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ma_due_diligence.contracts import DocumentClassification
from ma_due_diligence.domain import (
    Confidentiality,
    DiligenceWorkstream,
    DocumentType,
    FinancialPeriod,
    ParseStatus,
    PeriodKind,
    VdrDocument,
)
from ma_due_diligence.errors import DocumentParseError, VdrIngestionError
from ma_due_diligence.vdr.chunking import DiligenceChunker
from ma_due_diligence.vdr.classification import RuleBasedDocumentClassifier, title_from_path
from ma_due_diligence.vdr.models import (
    DocumentVersionSet,
    DuplicateDocument,
    IngestedDocument,
    IngestionIssue,
    IngestionIssueCode,
    IngestionRequest,
    ManifestEntry,
    VdrCorpus,
    VdrManifest,
)
from ma_due_diligence.vdr.parsing import VdrDocumentParser

_SUPPORTED = {".pdf", ".txt", ".md", ".markdown", ".csv", ".xlsx", ".html", ".htm"}
_VERSION_PATTERN = re.compile(r"(?:^|[_\s-])(v\d+(?:\.\d+)?|revised|draft|final)(?:$|[_\s-])", re.I)
_PERIOD_PATTERN = re.compile(r"(?:^|[^a-z0-9])(FY\s*20\d{2}|20\d{2})(?:$|[^a-z0-9])", re.I)


class VdrIngestionPipeline:
    """Parse each document independently so one bad file does not discard the corpus."""

    def __init__(
        self,
        *,
        parser: VdrDocumentParser | None = None,
        classifier: RuleBasedDocumentClassifier | None = None,
        chunker: DiligenceChunker | None = None,
    ) -> None:
        self._parser = parser or VdrDocumentParser()
        self._classifier = classifier or RuleBasedDocumentClassifier()
        self._chunker = chunker or DiligenceChunker()

    def ingest(self, request: IngestionRequest) -> VdrCorpus:
        sources = self._sources(request)
        documents: list[IngestedDocument] = []
        duplicates: list[DuplicateDocument] = []
        issues: list[IngestionIssue] = []
        checksum_catalog: dict[str, str] = {}
        logical_versions: dict[str, list[str]] = {}

        for path, entry in sources:
            source_name = str(path)
            if path.suffix.casefold() not in _SUPPORTED:
                issues.append(
                    IngestionIssue(
                        IngestionIssueCode.UNSUPPORTED_FORMAT,
                        source_name,
                        f"Unsupported file type {path.suffix or '<none>'}; document skipped.",
                    )
                )
                continue
            if not path.is_file():
                issues.append(
                    IngestionIssue(
                        IngestionIssueCode.PARSE_FAILED,
                        source_name,
                        "Source path is not a readable file.",
                    )
                )
                continue
            try:
                checksum = _sha256(path)
            except OSError as error:
                issues.append(
                    IngestionIssue(IngestionIssueCode.PARSE_FAILED, source_name, str(error))
                )
                continue
            retained = checksum_catalog.get(checksum)
            if retained is not None:
                duplicates.append(DuplicateDocument(checksum, retained, source_name))
                issues.append(
                    IngestionIssue(
                        IngestionIssueCode.DUPLICATE_DOCUMENT,
                        source_name,
                        f"Exact duplicate of {retained}; duplicate was not indexed.",
                    )
                )
                continue

            document = self._provisional_document(request.engagement_id, path, checksum, entry)
            try:
                parsed = self._parser.parse(path, document)
            except DocumentParseError as error:
                error_text = str(error)
                code = (
                    IngestionIssueCode.EMPTY_DOCUMENT
                    if error_text.casefold()
                    in {"document is empty", "pdf is empty", "csv is empty"}
                    else IngestionIssueCode.PARSE_FAILED
                )
                issues.append(IngestionIssue(code, source_name, error_text))
                continue
            sample = "\n".join(element.text for element in parsed.elements[:20])
            classification = self._classification(document, sample, entry)
            parse_status = ParseStatus.PARTIAL if parsed.warnings else ParseStatus.PARSED
            document = replace(
                document,
                document_type=classification.document_type,
                workstreams=classification.workstreams,
                parse_status=parse_status,
            )
            parsed = replace(parsed, document=document)
            chunks = self._chunker.chunk(parsed)
            documents.append(IngestedDocument(document, classification, parsed, chunks))
            checksum_catalog[checksum] = document.document_id
            logical_versions.setdefault(_logical_name(path), []).append(document.document_id)
            if parsed.warnings:
                issues.append(
                    IngestionIssue(
                        IngestionIssueCode.PARTIAL_PARSE,
                        source_name,
                        "; ".join(parsed.warnings),
                    )
                )

        versions = tuple(
            DocumentVersionSet(name, tuple(ids))
            for name, ids in sorted(logical_versions.items())
            if len(ids) > 1
        )
        return VdrCorpus(
            request.engagement_id,
            tuple(documents),
            tuple(duplicates),
            versions,
            tuple(issues),
        )

    @staticmethod
    def _sources(request: IngestionRequest) -> tuple[tuple[Path, ManifestEntry | None], ...]:
        if request.folder is not None:
            folder = request.folder.resolve()
            if not folder.is_dir():
                raise VdrIngestionError(f"VDR folder does not exist: {folder}")
            return tuple((path, None) for path in sorted(folder.rglob("*")) if path.is_file())
        if request.files:
            return tuple((path.resolve(), None) for path in request.files)
        assert request.manifest is not None
        return tuple(
            (Path(entry.source_path).resolve(), entry) for entry in request.manifest.entries
        )

    @staticmethod
    def _provisional_document(
        engagement_id: str,
        path: Path,
        checksum: str,
        entry: ManifestEntry | None,
    ) -> VdrDocument:
        version = entry.version if entry is not None else None
        version = version or _version(path)
        period = entry.period if entry is not None else None
        period = period or _period(path)
        return VdrDocument(
            document_id=f"doc:{checksum[:24]}",
            engagement_id=engagement_id,
            filename=path.name,
            document_type=DocumentType.OTHER,
            workstreams=(DiligenceWorkstream.OPERATIONAL,),
            source_reference=str(path),
            title=entry.title if entry and entry.title else title_from_path(path),
            entity=entry.entity if entry else None,
            period=period,
            version=version,
            retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            confidentiality=Confidentiality.CONFIDENTIAL,
            parse_status=ParseStatus.NOT_STARTED,
            checksum_sha256=checksum,
            source_metadata=(("format", path.suffix.casefold().lstrip(".")),),
        )

    def _classification(
        self,
        document: VdrDocument,
        sample: str,
        entry: ManifestEntry | None,
    ) -> DocumentClassification:
        inferred = self._classifier.classify(document, sample)
        if entry is None or (entry.document_type is None and not entry.workstreams):
            return inferred
        document_type = entry.document_type or inferred.document_type
        workstreams = entry.workstreams or inferred.workstreams
        return DocumentClassification(
            document.document_id,
            document_type,
            workstreams,
            "Manifest metadata overrides deterministic classification where supplied. "
            + inferred.rationale,
            workstreams[0],
            inferred.ambiguous and entry.document_type is None,
        )


def manifest_from_json(path: Path, engagement_id: str | None = None) -> VdrManifest:
    """Load the supported small manifest schema, resolving paths beside the manifest."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VdrIngestionError(f"invalid VDR manifest: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
        raise VdrIngestionError("manifest must contain a documents list")
    resolved_engagement = engagement_id or payload.get("engagement_id")
    if not isinstance(resolved_engagement, str):
        raise VdrIngestionError("manifest requires engagement_id")
    entries: list[ManifestEntry] = []
    for raw in cast(list[object], payload["documents"]):
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise VdrIngestionError("each manifest document requires a path")
        raw_type = raw.get("document_type")
        raw_streams = raw.get("workstreams", [])
        if not isinstance(raw_streams, list) or any(
            not isinstance(item, str) for item in raw_streams
        ):
            raise VdrIngestionError("manifest workstreams must be a list of strings")
        source = (path.parent / cast(str, raw["path"])).resolve()
        entries.append(
            ManifestEntry(
                str(source),
                None if raw_type is None else DocumentType(str(raw_type)),
                tuple(DiligenceWorkstream(str(item)) for item in raw_streams),
                cast(str | None, raw.get("title")),
                version=cast(str | None, raw.get("version")),
            )
        )
    return VdrManifest(resolved_engagement, tuple(entries))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _version(path: Path) -> str | None:
    match = _VERSION_PATTERN.search(path.stem)
    return None if match is None else match.group(1).lower()


def _period(path: Path) -> FinancialPeriod | None:
    match = _PERIOD_PATTERN.search(path.stem)
    if match is None:
        return None
    label = match.group(1).upper().replace(" ", "")
    return FinancialPeriod(PeriodKind.FISCAL_YEAR, label)


def _logical_name(path: Path) -> str:
    name = path.stem.casefold()
    previous = ""
    while previous != name:
        previous = name
        name = _VERSION_PATTERN.sub("_", name)
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_")
