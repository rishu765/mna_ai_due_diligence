"""Deterministic, explainable VDR document classification."""

from __future__ import annotations

import re
from pathlib import Path

from ma_due_diligence.contracts import DocumentClassification
from ma_due_diligence.domain import DiligenceWorkstream, DocumentType, VdrDocument

_TYPE_RULES: tuple[tuple[DocumentType, tuple[str, ...]], ...] = (
    (DocumentType.DEBT_SCHEDULE, ("debt schedule", "borrowings", "loan schedule", "covenant")),
    (DocumentType.BANK_STATEMENT, ("bank statement",)),
    (DocumentType.CAP_TABLE, ("cap table", "capitalization table", "share register")),
    (DocumentType.CUSTOMER_COHORT_REPORT, ("customer cohort", "cohort report")),
    (DocumentType.CUSTOMER_CONTRACT, ("customer agreement", "customer contract", "msa customer")),
    (
        DocumentType.SUPPLIER_CONTRACT,
        ("supplier agreement", "supplier contract", "vendor agreement"),
    ),
    (DocumentType.GENERAL_LEDGER_EXPORT, ("general ledger", "gl export", "trial balance")),
    (DocumentType.MANAGEMENT_ACCOUNTS, ("management accounts", "monthly accounts")),
    (
        DocumentType.FINANCIAL_STATEMENTS,
        ("audited financial", "financial statements", "annual report"),
    ),
    (DocumentType.SALES_REPORT, ("sales report", "customer sales", "revenue by customer")),
    (DocumentType.FORECAST, ("forecast", "projection")),
    (DocumentType.BUDGET, ("budget",)),
    (DocumentType.BOARD_MATERIAL, ("board memo", "board material", "board pack")),
    (
        DocumentType.MANAGEMENT_PRESENTATION,
        ("management presentation", "management deck", "investor deck"),
    ),
    (DocumentType.HR_REPORT, ("hr report", "employee report", "headcount")),
    (DocumentType.TAX_DOCUMENT, ("tax return", "tax document")),
    (DocumentType.POLICY, ("policy",)),
    (DocumentType.LEGAL_AGREEMENT, ("agreement", "litigation", "legal")),
)

_WORKSTREAMS: dict[DocumentType, tuple[DiligenceWorkstream, ...]] = {
    DocumentType.FINANCIAL_STATEMENTS: (DiligenceWorkstream.FINANCIAL,),
    DocumentType.MANAGEMENT_ACCOUNTS: (
        DiligenceWorkstream.FINANCIAL,
        DiligenceWorkstream.OPERATIONAL,
    ),
    DocumentType.GENERAL_LEDGER_EXPORT: (DiligenceWorkstream.FINANCIAL,),
    DocumentType.CUSTOMER_CONTRACT: (
        DiligenceWorkstream.LEGAL_CONTRACTUAL,
        DiligenceWorkstream.COMMERCIAL,
    ),
    DocumentType.SUPPLIER_CONTRACT: (
        DiligenceWorkstream.LEGAL_CONTRACTUAL,
        DiligenceWorkstream.OPERATIONAL,
    ),
    DocumentType.SALES_REPORT: (DiligenceWorkstream.COMMERCIAL, DiligenceWorkstream.FINANCIAL),
    DocumentType.CUSTOMER_COHORT_REPORT: (DiligenceWorkstream.COMMERCIAL,),
    DocumentType.BUDGET: (DiligenceWorkstream.FINANCIAL, DiligenceWorkstream.COMMERCIAL),
    DocumentType.FORECAST: (DiligenceWorkstream.FINANCIAL, DiligenceWorkstream.COMMERCIAL),
    DocumentType.BANK_STATEMENT: (DiligenceWorkstream.FINANCIAL,),
    DocumentType.DEBT_SCHEDULE: (
        DiligenceWorkstream.FINANCIAL,
        DiligenceWorkstream.LEGAL_CONTRACTUAL,
    ),
    DocumentType.CAP_TABLE: (DiligenceWorkstream.LEGAL_CONTRACTUAL, DiligenceWorkstream.FINANCIAL),
    DocumentType.TAX_DOCUMENT: (DiligenceWorkstream.TAX, DiligenceWorkstream.FINANCIAL),
    DocumentType.BOARD_MATERIAL: (DiligenceWorkstream.OPERATIONAL, DiligenceWorkstream.COMMERCIAL),
    DocumentType.MANAGEMENT_PRESENTATION: (
        DiligenceWorkstream.COMMERCIAL,
        DiligenceWorkstream.FINANCIAL,
    ),
    DocumentType.HR_REPORT: (DiligenceWorkstream.HR, DiligenceWorkstream.OPERATIONAL),
    DocumentType.POLICY: (DiligenceWorkstream.OPERATIONAL,),
    DocumentType.LEGAL_AGREEMENT: (DiligenceWorkstream.LEGAL_CONTRACTUAL,),
    DocumentType.OTHER: (DiligenceWorkstream.OPERATIONAL,),
}


class RuleBasedDocumentClassifier:
    """Classify from filename and a bounded text sample with visible rules."""

    def classify(self, document: VdrDocument, content_sample: str = "") -> DocumentClassification:
        haystack = _searchable(
            f"{document.filename} {document.title or ''} {content_sample[:4000]}"
        )
        matched: list[tuple[DocumentType, str]] = []
        for document_type, phrases in _TYPE_RULES:
            phrase = next((value for value in phrases if value in haystack), None)
            if phrase is not None:
                matched.append((document_type, phrase))
        if matched:
            document_type, phrase = matched[0]
            ambiguous = len({item[0] for item in matched}) > 1
            rationale = f"Matched deterministic phrase {phrase!r} in filename/title/content."
        else:
            document_type = DocumentType.OTHER
            ambiguous = True
            rationale = "No deterministic document-type rule matched; retained as other."
        workstreams = _WORKSTREAMS[document_type]
        return DocumentClassification(
            document.document_id,
            document_type,
            workstreams,
            rationale,
            workstreams[0],
            ambiguous,
        )


def title_from_path(path: Path) -> str:
    return re.sub(r"[_-]+", " ", path.stem).strip()


def _searchable(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())
