"""Deterministic claim extraction from bounded specialist retrieval evidence."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ma_due_diligence.domain import DiligenceWorkstream, DocumentType, VdrDocument
from ma_due_diligence.retrieval.models import DiligenceEvidenceResult
from ma_due_diligence.specialists.models import (
    ClaimValueKind,
    InvestigationClaim,
    SourceAuthority,
)

_PERCENT = re.compile(r"(?:largest|top)\s+customer[^\n]{0,45}?(\d+(?:\.\d+)?)\s*%", re.I)
_SUPPLIER_PERCENT = re.compile(r"orion[^\n]{0,55}?(\d+(?:\.\d+)?)\s*%", re.I)
_GROWTH = re.compile(r"(forecast|actual)[^\n]{0,35}?growth[^\n]{0,20}?(\d+(?:\.\d+)?)\s*%", re.I)
_EXPIRY = re.compile(
    r"(?:expires?|expiration)[^\n]{0,30}?(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})", re.I
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def extract_claims(
    results: tuple[DiligenceEvidenceResult, ...],
    documents: tuple[VdrDocument, ...],
) -> tuple[InvestigationClaim, ...]:
    document_map = {item.document_id: item for item in documents}
    claims: list[InvestigationClaim] = []
    seen: set[tuple[str, str, str]] = set()
    for result in results:
        document = document_map.get(result.document_id)
        text = result.text
        lowered = text.casefold()
        specs: list[tuple[str, ClaimValueKind, str | Decimal | bool | date, str | None, str]] = []
        match = _PERCENT.search(text)
        if match:
            percentage = Decimal(match.group(1))
            specs.extend(
                (
                    (
                        "customer_concentration_percent",
                        ClaimValueKind.NUMBER,
                        percentage,
                        "%",
                        "Customer A",
                    ),
                    (
                        "customer_concentration_present",
                        ClaimValueKind.BOOLEAN,
                        True,
                        None,
                        "Customer A",
                    ),
                )
            )
        if (
            "no customer concentration" in lowered
            or "no customer contributes more than 20%" in lowered
        ):
            specs.append(
                (
                    "customer_concentration_present",
                    ClaimValueKind.BOOLEAN,
                    False,
                    None,
                    "Customer A",
                )
            )
        supplier_match = _SUPPLIER_PERCENT.search(text)
        if supplier_match:
            specs.extend(
                (
                    (
                        "supplier_concentration_percent",
                        ClaimValueKind.NUMBER,
                        Decimal(supplier_match.group(1)),
                        "%",
                        "Orion Metals",
                    ),
                    ("supplier_diversified", ClaimValueKind.BOOLEAN, False, None, "Orion Metals"),
                )
            )
        if "supplier diversification" in lowered and any(
            word in lowered for word in ("complete", "completed")
        ):
            specs.append(
                ("supplier_diversified", ClaimValueKind.BOOLEAN, True, None, "Orion Metals")
            )
        if "sole-source" in lowered or "single-source" in lowered:
            specs.append(
                ("single_source_supplier", ClaimValueKind.BOOLEAN, True, None, "Orion Metals")
            )
        if "change of control" in lowered and any(
            word in lowered for word in ("consent", "terminate", "termination")
        ):
            specs.append(
                ("change_of_control_consent", ClaimValueKind.BOOLEAN, True, None, "Customer A")
            )
        if "termination for convenience" in lowered:
            specs.append(
                ("termination_for_convenience", ClaimValueKind.BOOLEAN, True, None, "Customer A")
            )
        if "assignment" in lowered and any(
            word in lowered for word in ("consent", "prohibited", "may not assign")
        ):
            specs.append(
                ("assignment_restriction", ClaimValueKind.BOOLEAN, True, None, "Customer A")
            )
        expiry = _EXPIRY.search(text)
        if expiry:
            month = _MONTHS[expiry.group(2).casefold()]
            specs.append(
                (
                    "contract_expiry",
                    ClaimValueKind.DATE,
                    date(int(expiry.group(3)), month, int(expiry.group(1))),
                    None,
                    "Customer A",
                )
            )
        for growth in _GROWTH.finditer(text):
            specs.append(
                (
                    f"{growth.group(1).casefold()}_revenue_growth",
                    ClaimValueKind.NUMBER,
                    Decimal(growth.group(2)),
                    "%",
                    "Target",
                )
            )
        if "capacity utilization" in lowered:
            value_match = re.search(
                r"capacity utilization[^\n]{0,20}?(\d+(?:\.\d+)?)\s*%", text, re.I
            )
            if value_match:
                specs.append(
                    (
                        "capacity_utilization",
                        ClaimValueKind.NUMBER,
                        Decimal(value_match.group(1)),
                        "%",
                        "Target",
                    )
                )

        for topic, kind, value, unit, subject in specs:
            key = (result.chunk_id, topic, str(value))
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                _claim(
                    len(claims) + 1,
                    result,
                    document,
                    topic,
                    kind,
                    value,
                    unit,
                    _document_subject(document, subject),
                )
            )
    return tuple(claims)


def _claim(
    sequence: int,
    result: DiligenceEvidenceResult,
    document: VdrDocument | None,
    topic: str,
    kind: ClaimValueKind,
    value: str | Decimal | bool | date,
    unit: str | None,
    subject: str,
) -> InvestigationClaim:
    return InvestigationClaim(
        claim_id=f"claim-{sequence:03d}-{result.chunk_id}",
        subject=subject,
        topic=topic,
        value_kind=kind,
        statement=result.text,
        evidence=result.evidence,
        document_type=result.document_type,
        workstream=_primary_workstream(result),
        authority=_authority(result.document_type),
        unit=unit,
        period=result.evidence.period,
        entity_id=None
        if document is None or document.entity is None
        else document.entity.entity_id,
        version=None if document is None else document.version,
        effective_date=_effective_date(result.text),
        logical_document_key=None if document is None else _logical_key(document.filename),
        text_value=value if kind is ClaimValueKind.TEXT and isinstance(value, str) else None,
        numeric_value=(
            value if kind is ClaimValueKind.NUMBER and isinstance(value, Decimal) else None
        ),
        boolean_value=(
            value if kind is ClaimValueKind.BOOLEAN and isinstance(value, bool) else None
        ),
        date_value=value if kind is ClaimValueKind.DATE and isinstance(value, date) else None,
    )


def _primary_workstream(result: DiligenceEvidenceResult) -> DiligenceWorkstream:
    if result.workstreams:
        return result.workstreams[0]
    if result.document_type in {
        DocumentType.CUSTOMER_CONTRACT,
        DocumentType.SUPPLIER_CONTRACT,
        DocumentType.LEGAL_AGREEMENT,
    }:
        return DiligenceWorkstream.LEGAL_CONTRACTUAL
    return DiligenceWorkstream.OPERATIONAL


def _authority(document_type: DocumentType) -> SourceAuthority:
    if document_type in {
        DocumentType.CUSTOMER_CONTRACT,
        DocumentType.SUPPLIER_CONTRACT,
        DocumentType.LEGAL_AGREEMENT,
    }:
        return SourceAuthority.SIGNED_CONTRACT
    if document_type is DocumentType.FINANCIAL_STATEMENTS:
        return SourceAuthority.AUDITED
    if document_type in {
        DocumentType.SALES_REPORT,
        DocumentType.CUSTOMER_COHORT_REPORT,
        DocumentType.DEBT_SCHEDULE,
        DocumentType.BANK_STATEMENT,
    }:
        return SourceAuthority.DIRECT_SCHEDULE
    if document_type is DocumentType.BOARD_MATERIAL:
        return SourceAuthority.BOARD_REPORT
    if document_type is DocumentType.MANAGEMENT_ACCOUNTS:
        return SourceAuthority.MANAGEMENT_ACCOUNTS
    if document_type is DocumentType.MANAGEMENT_PRESENTATION:
        return SourceAuthority.MANAGEMENT_NARRATIVE
    return SourceAuthority.OTHER


def _logical_key(filename: str) -> str:
    stem = filename.casefold().rsplit(".", 1)[0]
    return re.sub(r"(?:[_-](?:v\d+(?:\.\d+)?|revised|draft|final))+$", "", stem)


def _document_subject(document: VdrDocument | None, fallback: str) -> str:
    if document is None:
        return fallback
    name = document.filename.casefold()
    for token, subject in (
        ("apex", "Customer A"),
        ("beacon", "Customer B"),
        ("orion", "Orion Metals"),
    ):
        if token in name:
            return subject
    return fallback


def _effective_date(text: str) -> date | None:
    match = re.search(r"effective(?:\s+date)?[: ]+(\d{4})-(\d{2})-(\d{2})", text, re.I)
    return None if match is None else date(*map(int, match.groups()))
