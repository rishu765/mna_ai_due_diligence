"""Validated, scanned, encrypted, and recoverable pilot document processing."""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final
from urllib.parse import unquote
from uuid import uuid4

from ma_due_diligence.persistence import (
    PilotAuditEvent,
    PilotDatabase,
    PilotDocumentService,
    StoredDocumentRecord,
    StoredDocumentStatus,
)
from ma_due_diligence.vdr import IngestionRequest, VdrIngestionPipeline
from ma_due_diligence.vdr.models import ElementKind
from ma_due_diligence.vdr.parsing import VdrDocumentParser

_SUPPORTED: Final = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/plain", "application/octet-stream"},
    ".csv": {"text/csv", "application/vnd.ms-excel", "application/octet-stream"},
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/octet-stream",
    },
    ".html": {"text/html", "application/xhtml+xml", "application/octet-stream"},
    ".htm": {"text/html", "application/xhtml+xml", "application/octet-stream"},
}
_DANGEROUS_ARCHIVE_SUFFIXES: Final = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".js",
    ".ps1",
    ".scr",
    ".vbs",
}
_BATCH_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
_EICAR: Final = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"


class UploadRejectedError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    maximum_file_bytes: int = 50 * 1024 * 1024
    maximum_archive_entries: int = 20_000
    maximum_uncompressed_bytes: int = 250 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ScanResult:
    engine: str
    clean: bool
    findings: tuple[str, ...] = ()


class LocalContentScanner:
    """Fail-closed pilot screen for known test malware and disguised active content."""

    def __init__(self, policy: UploadPolicy) -> None:
        self._policy = policy

    def scan(self, filename: str, content: bytes) -> ScanResult:
        findings: list[str] = []
        if _EICAR in content:
            findings.append("eicar_test_signature")
        if content.startswith(b"MZ"):
            findings.append("windows_executable_header")
        if Path(filename).suffix.casefold() == ".xlsx":
            findings.extend(self._xlsx_findings(content))
        return ScanResult("madd-local-content-screen-v1", not findings, tuple(findings))

    def _xlsx_findings(self, content: bytes) -> list[str]:
        findings: list[str] = []
        try:
            from io import BytesIO

            with zipfile.ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > self._policy.maximum_archive_entries:
                    findings.append("archive_entry_limit_exceeded")
                expanded = sum(item.file_size for item in entries)
                if expanded > self._policy.maximum_uncompressed_bytes:
                    findings.append("archive_expansion_limit_exceeded")
                for item in entries:
                    path = Path(item.filename.casefold())
                    if path.name == "vbaproject.bin":
                        findings.append("office_macro_content")
                    if path.suffix in _DANGEROUS_ARCHIVE_SUFFIXES:
                        findings.append(f"active_archive_content:{path.suffix}")
        except (OSError, zipfile.BadZipFile):
            findings.append("invalid_xlsx_container")
        return findings


class PilotDocumentProcessingService:
    def __init__(
        self,
        database: PilotDatabase,
        documents: PilotDocumentService,
        *,
        policy: UploadPolicy | None = None,
        scanner: LocalContentScanner | None = None,
        ingestion: VdrIngestionPipeline | None = None,
    ) -> None:
        self._database = database
        self._documents = documents
        self._policy = policy or UploadPolicy()
        self._scanner = scanner or LocalContentScanner(self._policy)
        self._ingestion = ingestion or VdrIngestionPipeline(
            parser=VdrDocumentParser(ocr_enabled=True, pdf_table_extraction=True)
        )

    @property
    def maximum_file_bytes(self) -> int:
        return self._policy.maximum_file_bytes

    def process_upload(
        self,
        *,
        deal_id: str,
        encoded_filename: str,
        content_type: str,
        content: bytes,
        actor_id: str,
        batch_id: str,
    ) -> StoredDocumentRecord:
        try:
            filename = _validate_upload(
                encoded_filename,
                content_type,
                content,
                batch_id,
                self._policy,
            )
        except UploadRejectedError as error:
            self._audit_rejection(
                deal_id=deal_id,
                actor_id=actor_id,
                filename=encoded_filename[:240] or "<missing>",
                batch_id=batch_id,
                code=error.code,
                detail=error.detail,
            )
            raise
        checksum = hashlib.sha256(content).hexdigest()
        duplicate = self._database.list_documents_by_checksum(deal_id, checksum)
        if duplicate:
            duplicate_error = UploadRejectedError(
                "duplicate_document",
                f"Exact duplicate of {duplicate[0].original_filename} was not stored.",
            )
            self._audit_rejection(
                deal_id=deal_id,
                actor_id=actor_id,
                filename=filename,
                batch_id=batch_id,
                code=duplicate_error.code,
                detail=duplicate_error.detail,
            )
            raise duplicate_error
        scan = self._scanner.scan(filename, content)
        if not scan.clean:
            self._audit_rejection(
                deal_id=deal_id,
                actor_id=actor_id,
                filename=filename,
                batch_id=batch_id,
                code="content_screen_failed",
                detail=", ".join(scan.findings),
            )
            raise UploadRejectedError(
                "content_screen_failed",
                "The file failed the local malware and active-content screen.",
            )

        document_id = f"doc-{uuid4().hex}"
        metadata: dict[str, object] = {
            "batch_id": batch_id,
            "validation": "accepted",
            "scan_engine": scan.engine,
            "scan_status": "clean",
            "processing_stage": "stored",
        }
        record = self._documents.store_document(
            deal_id=deal_id,
            document_id=document_id,
            original_filename=filename,
            content=content,
            content_type=content_type,
            actor_id=actor_id,
            metadata=metadata,
        )
        return self._parse_and_record(record, content, actor_id)

    def list_documents(self, deal_id: str) -> tuple[StoredDocumentRecord, ...]:
        return self._database.list_documents(deal_id)

    def batch_payload(self, deal_id: str, batch_id: str) -> dict[str, object]:
        _validate_batch_id(batch_id)
        documents = tuple(
            item
            for item in self._database.list_documents(deal_id)
            if item.metadata.get("batch_id") == batch_id
        )
        counts = {status.value: 0 for status in StoredDocumentStatus}
        for item in documents:
            counts[item.status.value] += 1
        rejections = [
            {
                "filename": str(event.detail.get("filename", "<unknown>")),
                "code": str(event.detail.get("code", "upload_rejected")),
                "message": str(event.detail.get("detail", "Upload rejected.")),
            }
            for event in self._database.list_audit_events(deal_id)
            if event.action == "document_upload_rejected"
            and event.detail.get("batch_id") == batch_id
        ]
        return {
            "batch_id": batch_id,
            "document_count": len(documents),
            "rejection_count": len(rejections),
            "status_counts": counts,
            "complete": bool(documents or rejections)
            and all(
                item.status
                in {
                    StoredDocumentStatus.INDEXED,
                    StoredDocumentStatus.PARTIAL,
                    StoredDocumentStatus.FAILED,
                }
                for item in documents
            ),
            "documents": [document_payload(item) for item in documents],
            "rejections": rejections,
        }

    def _parse_and_record(
        self,
        record: StoredDocumentRecord,
        content: bytes,
        actor_id: str,
    ) -> StoredDocumentRecord:
        temporary_path: Path | None = None
        metadata = dict(record.metadata)
        chunks: tuple[dict[str, object], ...] = ()
        try:
            with NamedTemporaryFile(
                mode="wb",
                prefix=f"{Path(record.original_filename).stem}-",
                suffix=Path(record.original_filename).suffix,
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            corpus = self._ingestion.ingest(
                IngestionRequest(record.deal_id, files=(temporary_path,))
            )
            issues = [
                {
                    "code": item.code.value,
                    "message": _safe_processing_message(
                        item.message,
                        temporary_path,
                        record.original_filename,
                    ),
                }
                for item in corpus.issues
            ]
            if not corpus.documents:
                status = StoredDocumentStatus.FAILED
                metadata.update(
                    {
                        "processing_stage": "failed",
                        "issues": issues
                        or [{"code": "parse_failed", "message": "No document output produced."}],
                    }
                )
            else:
                ingested = corpus.documents[0]
                table_rows = sum(
                    item.kind in {ElementKind.TABLE_ROW, ElementKind.SHEET_ROW}
                    for item in ingested.parsed.elements
                )
                status = (
                    StoredDocumentStatus.PARTIAL
                    if issues or ingested.parsed.warnings
                    else StoredDocumentStatus.INDEXED
                )
                metadata.update(
                    {
                        "processing_stage": "complete",
                        "document_type": ingested.document.document_type.value,
                        "workstreams": [item.value for item in ingested.document.workstreams],
                        "classification_rationale": ingested.classification.rationale,
                        "page_count": ingested.parsed.page_count,
                        "element_count": len(ingested.parsed.elements),
                        "table_row_count": table_rows,
                        "chunk_count": len(ingested.chunks),
                        "warnings": list(ingested.parsed.warnings),
                        "issues": issues,
                    }
                )
                chunks = tuple(
                    {
                        "chunk_index": item.chunk_index,
                        "text": item.text,
                        "document_type": item.document_type.value,
                        "workstreams": [value.value for value in item.workstreams],
                        "page_numbers": list(item.page_numbers),
                        "physical_page_indexes": list(item.physical_page_indexes),
                        "section": item.section,
                        "clause_number": item.clause_number,
                        "table_id": item.table_id,
                        "sheet_name": item.sheet_name,
                        "row_numbers": list(item.row_numbers),
                        "cell_range": item.cell_range,
                        "content_fingerprint": item.content_fingerprint,
                        "source_filename": record.original_filename,
                    }
                    for item in ingested.chunks
                )
        except Exception as error:
            status = StoredDocumentStatus.FAILED
            metadata.update(
                {
                    "processing_stage": "failed",
                    "issues": [
                        {
                            "code": "processing_error",
                            "message": _safe_processing_message(
                                str(error),
                                temporary_path,
                                record.original_filename,
                            ),
                        }
                    ],
                }
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        updated = replace(record, status=status, metadata=metadata)
        event = PilotAuditEvent(
            event_id=f"audit-{uuid4().hex}",
            deal_id=record.deal_id,
            actor_id=actor_id,
            action="document_processing_completed",
            object_type="document",
            object_id=record.document_id,
            detail={"status": status.value, "issues": metadata.get("issues", [])},
            occurred_at=datetime.now(UTC),
        )
        self._database.update_document_processing(updated, event, chunks)
        return updated

    def _audit_rejection(
        self,
        *,
        deal_id: str,
        actor_id: str,
        filename: str,
        batch_id: str,
        code: str,
        detail: str,
    ) -> None:
        self._database.append_audit_event(
            PilotAuditEvent(
                event_id=f"audit-{uuid4().hex}",
                deal_id=deal_id,
                actor_id=actor_id,
                action="document_upload_rejected",
                object_type="upload",
                object_id=f"upload-{uuid4().hex}",
                detail={
                    "filename": filename,
                    "batch_id": batch_id,
                    "code": code,
                    "detail": detail,
                },
                occurred_at=datetime.now(UTC),
            )
        )


def document_payload(record: StoredDocumentRecord) -> dict[str, object]:
    return {
        "document_id": record.document_id,
        "filename": record.original_filename,
        "content_type": record.content_type,
        "size_bytes": record.plaintext_size_bytes,
        "sha256": record.plaintext_sha256,
        "status": record.status.value,
        "batch_id": record.metadata.get("batch_id"),
        "processing_stage": record.metadata.get("processing_stage"),
        "document_type": record.metadata.get("document_type"),
        "workstreams": record.metadata.get("workstreams", []),
        "page_count": record.metadata.get("page_count"),
        "element_count": record.metadata.get("element_count"),
        "table_row_count": record.metadata.get("table_row_count"),
        "chunk_count": record.metadata.get("chunk_count"),
        "warnings": record.metadata.get("warnings", []),
        "issues": record.metadata.get("issues", []),
        "created_at": record.created_at,
    }


def _validate_upload(
    encoded_filename: str,
    content_type: str,
    content: bytes,
    batch_id: str,
    policy: UploadPolicy,
) -> str:
    _validate_batch_id(batch_id)
    try:
        filename = unquote(encoded_filename, errors="strict")
    except UnicodeDecodeError as error:
        raise UploadRejectedError("invalid_filename", "Filename encoding is invalid.") from error
    if (
        not filename
        or len(filename) > 240
        or filename != Path(filename).name
        or any(ord(character) < 32 for character in filename)
    ):
        raise UploadRejectedError("invalid_filename", "Filename is unsafe or invalid.")
    if not content:
        raise UploadRejectedError("empty_file", "Empty files are not accepted.")
    if len(content) > policy.maximum_file_bytes:
        raise UploadRejectedError(
            "file_too_large",
            f"File exceeds the {policy.maximum_file_bytes} byte upload limit.",
        )
    suffix = Path(filename).suffix.casefold()
    allowed_types = _SUPPORTED.get(suffix)
    normalized_type = content_type.partition(";")[0].strip().casefold()
    if allowed_types is None:
        raise UploadRejectedError(
            "unsupported_format", f"Unsupported file type: {suffix or '<none>'}."
        )
    if normalized_type not in allowed_types:
        raise UploadRejectedError(
            "content_type_mismatch",
            f"Content type {normalized_type or '<none>'} is not allowed for {suffix}.",
        )
    _validate_magic(suffix, content)
    return filename


def _validate_magic(suffix: str, content: bytes) -> None:
    if suffix == ".pdf" and not content.lstrip().startswith(b"%PDF-"):
        raise UploadRejectedError("signature_mismatch", "File contents are not a PDF.")
    if suffix == ".xlsx":
        if not content.startswith(b"PK"):
            raise UploadRejectedError(
                "signature_mismatch", "File contents are not an XLSX archive."
            )
        try:
            from io import BytesIO

            with zipfile.ZipFile(BytesIO(content)) as archive:
                names = {name.casefold() for name in archive.namelist()}
            if "[content_types].xml" not in names or not any(
                name.startswith("xl/") for name in names
            ):
                raise UploadRejectedError(
                    "signature_mismatch", "Archive does not contain an XLSX workbook."
                )
        except zipfile.BadZipFile as error:
            raise UploadRejectedError("signature_mismatch", "XLSX archive is invalid.") from error
    if suffix not in {".pdf", ".xlsx"}:
        if b"\x00" in content[:8192]:
            raise UploadRejectedError("binary_text_file", "Text document contains binary data.")
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise UploadRejectedError(
                "invalid_text_encoding", "Text documents must use UTF-8 encoding."
            ) from error


def _validate_batch_id(batch_id: str) -> None:
    if not _BATCH_PATTERN.fullmatch(batch_id):
        raise UploadRejectedError("invalid_batch_id", "Upload batch identifier is invalid.")


def _safe_processing_message(
    message: str,
    temporary_path: Path | None,
    original_filename: str,
) -> str:
    if temporary_path is None:
        return message
    variants = {
        str(temporary_path),
        str(temporary_path.resolve()),
        temporary_path.as_posix(),
        temporary_path.resolve().as_posix(),
    }
    sanitized = message
    for value in variants:
        sanitized = sanitized.replace(value, original_filename)
    path_pattern = rf"(?:[A-Za-z]:)?(?:\\+|/)[^'\"\n]*{re.escape(temporary_path.name)}"
    sanitized = re.sub(path_pattern, original_filename, sanitized)
    return sanitized.replace(temporary_path.name, original_filename)
