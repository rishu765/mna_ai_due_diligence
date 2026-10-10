from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ma_due_diligence.domain import DiligenceWorkstream, DocumentType, EntityReference, ParseStatus
from ma_due_diligence.vdr.ingestion import VdrIngestionPipeline, manifest_from_json
from ma_due_diligence.vdr.models import (
    DocumentFormat,
    ElementKind,
    IngestionIssueCode,
    IngestionRequest,
    ManifestEntry,
    VdrCorpus,
    VdrManifest,
)
from ma_due_diligence.vdr_fixtures import create_fixture_vdr


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    create_fixture_vdr(tmp_path)
    return tmp_path


@pytest.fixture
def vdr_corpus(fixture_root: Path) -> VdrCorpus:
    manifest = manifest_from_json(fixture_root / "manifest.json")
    return VdrIngestionPipeline().ingest(
        IngestionRequest(manifest.engagement_id, manifest=manifest)
    )


def test_manifest_ingestion_is_partial_failure_tolerant(vdr_corpus: VdrCorpus) -> None:
    assert len(vdr_corpus.documents) == 10
    assert len(vdr_corpus.duplicates) == 1
    assert any(issue.code is IngestionIssueCode.UNSUPPORTED_FORMAT for issue in vdr_corpus.issues)
    assert all(item.document.parse_status is ParseStatus.PARSED for item in vdr_corpus.documents)


def test_folder_and_explicit_list_ingestion(fixture_root: Path) -> None:
    pipeline = VdrIngestionPipeline()
    folder = pipeline.ingest(IngestionRequest("eng-folder", folder=fixture_root))
    explicit = pipeline.ingest(
        IngestionRequest(
            "eng-list",
            files=(fixture_root / "01_audited_financial_statements_FY2025.pdf",),
        )
    )
    assert len(folder.documents) == 10
    assert len(explicit.documents) == 1
    assert explicit.documents[0].document.engagement_id == "eng-list"


def test_document_and_workstream_classification(vdr_corpus: VdrCorpus) -> None:
    types = {item.document.filename: item.classification for item in vdr_corpus.documents}
    assert (
        types["01_audited_financial_statements_FY2025.pdf"].document_type
        is DocumentType.FINANCIAL_STATEMENTS
    )
    debt = types["06_debt_schedule_FY2025.csv"]
    assert debt.primary_workstream is DiligenceWorkstream.FINANCIAL
    assert DiligenceWorkstream.LEGAL_CONTRACTUAL in debt.workstreams
    contract = types["04_apex_customer_contract.txt"]
    assert contract.primary_workstream is DiligenceWorkstream.LEGAL_CONTRACTUAL
    assert DiligenceWorkstream.COMMERCIAL in contract.workstreams


def test_manifest_can_override_classification(fixture_root: Path) -> None:
    path = fixture_root / "09_board_memo.html"
    manifest = VdrManifest(
        "eng-override",
        (
            ManifestEntry(
                str(path),
                DocumentType.POLICY,
                (DiligenceWorkstream.REGULATORY,),
                entity=EntityReference("entity-northstar", "Northstar Components Ltd"),
            ),
        ),
    )
    corpus = VdrIngestionPipeline().ingest(IngestionRequest("eng-override", manifest=manifest))
    item = corpus.documents[0]
    assert item.document.document_type is DocumentType.POLICY
    assert item.document.entity is not None
    assert item.chunks[0].entity == item.document.entity


def test_pdf_preserves_physical_pages(vdr_corpus: VdrCorpus) -> None:
    item = next(
        value
        for value in vdr_corpus.documents
        if value.parsed.document_format is DocumentFormat.PDF
    )
    assert item.parsed.page_count == 3
    page_two = next(element for element in item.parsed.elements if element.page_number == 2)
    assert page_two.physical_page_index == 1
    assert any(chunk.page_numbers == (2,) for chunk in item.chunks)


def test_csv_preserves_table_row_and_cell_provenance(vdr_corpus: VdrCorpus) -> None:
    item = next(
        value
        for value in vdr_corpus.documents
        if value.document.document_type is DocumentType.SALES_REPORT
    )
    apex = next(element for element in item.parsed.elements if "Apex Retail" in element.text)
    assert apex.kind is ElementKind.TABLE_ROW
    assert apex.row_number == 2
    assert apex.cell_range == "A2:C2"
    chunk = next(value for value in item.chunks if "Apex Retail" in value.text)
    assert chunk.table_id is not None
    assert chunk.row_numbers == (2,)


def test_xlsx_preserves_sheet_header_and_range(vdr_corpus: VdrCorpus) -> None:
    item = next(
        value
        for value in vdr_corpus.documents
        if value.document.document_type is DocumentType.MANAGEMENT_ACCOUNTS
    )
    total = next(element for element in item.parsed.elements if "FY2025 total" in element.text)
    assert total.kind is ElementKind.SHEET_ROW
    assert total.sheet_name == "Monthly P&L"
    assert total.cell_range == "A14:C14"
    chunk = next(value for value in item.chunks if "FY2025 total" in value.text)
    assert "Headers: Month | Revenue GBP m" in chunk.text


def test_contract_clause_is_not_split_from_clause_number(vdr_corpus: VdrCorpus) -> None:
    item = next(
        value
        for value in vdr_corpus.documents
        if value.document.document_type is DocumentType.CUSTOMER_CONTRACT
    )
    clause = next(chunk for chunk in item.chunks if "Change of Control" in chunk.text)
    assert clause.clause_number == "8"
    assert "Customer may terminate" in clause.text


def test_financial_table_keeps_header_with_numeric_row(vdr_corpus: VdrCorpus) -> None:
    item = next(
        value
        for value in vdr_corpus.documents
        if value.document.document_type is DocumentType.MANAGEMENT_ACCOUNTS
    )
    december = next(chunk for chunk in item.chunks if "Dec |" in chunk.text)
    assert "Revenue GBP m" in december.text
    assert december.period is not None and december.period.label == "FY2025"


def test_exact_duplicates_and_revisions_are_separate(vdr_corpus: VdrCorpus) -> None:
    assert vdr_corpus.duplicates[0].duplicate_source_path.endswith("supplier_contract_copy.md")
    version_set = next(
        value for value in vdr_corpus.versions if "management_presentation" in value.logical_name
    )
    assert len(version_set.document_ids) == 2
    versions = {
        item.document.version
        for item in vdr_corpus.documents
        if item.document.document_id in version_set.document_ids
    }
    assert versions == {"v1", "v2"}


def test_corrupt_pdf_and_empty_document_do_not_abort_corpus(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    empty = tmp_path / "empty.txt"
    good = tmp_path / "customer_sales_report.txt"
    corrupt.write_bytes(b"not a pdf")
    empty.write_text("", encoding="utf-8")
    good.write_text("Revenue by customer: Apex 42%", encoding="utf-8")
    corpus = VdrIngestionPipeline().ingest(
        IngestionRequest("eng-partial", files=(corrupt, empty, good))
    )
    assert len(corpus.documents) == 1
    assert {issue.code for issue in corpus.issues} == {
        IngestionIssueCode.PARSE_FAILED,
        IngestionIssueCode.EMPTY_DOCUMENT,
    }


def test_malformed_csv_is_reported_without_aborting(tmp_path: Path) -> None:
    malformed = tmp_path / "sales_report.csv"
    good = tmp_path / "board_memo.txt"
    malformed.write_text('Customer,Revenue\n"Apex,42\n', encoding="utf-8")
    good.write_text("Board memo discusses operations.", encoding="utf-8")
    corpus = VdrIngestionPipeline().ingest(IngestionRequest("eng-csv", files=(malformed, good)))
    assert len(corpus.documents) == 1
    assert corpus.issues[0].code is IngestionIssueCode.PARSE_FAILED
    assert "malformed CSV" in corpus.issues[0].message


def test_manifest_loader_resolves_paths(fixture_root: Path) -> None:
    manifest = manifest_from_json(fixture_root / "manifest.json")
    assert manifest.engagement_id == "eng-northstar-vdr"
    assert Path(manifest.entries[0].source_path).is_absolute()
    assert replace(manifest.entries[0], version="final").version == "final"
