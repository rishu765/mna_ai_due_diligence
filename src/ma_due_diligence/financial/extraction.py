"""Evidence-bound deterministic and optional provider-based financial extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

from ma_due_diligence.domain import DocumentType, FinancialPeriod, SupportStatus
from ma_due_diligence.financial.models import (
    FinancialMetric,
    FinancialObservation,
    FinancialUnit,
    MetricBasis,
    ReportingStatus,
)
from ma_due_diligence.retrieval.models import RagContext

_NUMBER = r"[-+]?\(?\d+(?:,\d{3})*(?:\.\d+)?\)?"
_PATTERN = re.compile(
    rf"(?P<metric>adjusted\s+ebitda|ebitda|gross\s+profit|revenue|net\s+income|cash|debt|"
    rf"accounts?\s+receivable|inventory|accounts?\s+payable|accruals?|deferred\s+revenue|capex)"
    rf"(?:\s*\|?\s*(?:FY\s*\d{{4}}[AE]?|20\d{{2}}))?"
    rf"[^\n\d£$]{{0,50}}(?:(?P<currency>GBP|USD|EUR|£|\$)\s*)?"
    rf"(?P<value>{_NUMBER})\s*(?P<unit>billion|bn|million|mn|m|thousand|k)?",
    re.IGNORECASE,
)

_METRICS = {
    "revenue": FinancialMetric.REVENUE,
    "gross profit": FinancialMetric.GROSS_PROFIT,
    "ebitda": FinancialMetric.EBITDA,
    "adjusted ebitda": FinancialMetric.ADJUSTED_EBITDA,
    "net income": FinancialMetric.NET_INCOME,
    "cash": FinancialMetric.CASH,
    "debt": FinancialMetric.DEBT,
    "account receivable": FinancialMetric.ACCOUNTS_RECEIVABLE,
    "accounts receivable": FinancialMetric.ACCOUNTS_RECEIVABLE,
    "inventory": FinancialMetric.INVENTORY,
    "account payable": FinancialMetric.ACCOUNTS_PAYABLE,
    "accounts payable": FinancialMetric.ACCOUNTS_PAYABLE,
    "accrual": FinancialMetric.ACCRUALS,
    "accruals": FinancialMetric.ACCRUALS,
    "deferred revenue": FinancialMetric.DEFERRED_REVENUE,
    "capex": FinancialMetric.CAPEX,
}
_UNITS = {
    "billion": FinancialUnit.BILLION,
    "bn": FinancialUnit.BILLION,
    "million": FinancialUnit.MILLION,
    "mn": FinancialUnit.MILLION,
    "m": FinancialUnit.MILLION,
    "thousand": FinancialUnit.THOUSAND,
    "k": FinancialUnit.THOUSAND,
}
_CURRENCIES = {"£": "GBP", "$": "USD"}


@dataclass(frozen=True, slots=True)
class ExtractionCandidate:
    metric: FinancialMetric
    value: Decimal | None
    currency: str | None
    unit: FinancialUnit
    period: FinancialPeriod
    reporting_status: ReportingStatus
    basis: MetricBasis
    evidence_id: str
    rationale: str


class FinancialExtractionProvider(Protocol):
    """Optional LLM boundary; implementations return candidates, never calculations."""

    def extract(self, context: RagContext) -> tuple[ExtractionCandidate, ...]: ...


class FinancialExtractionService:
    def __init__(self, provider: FinancialExtractionProvider | None = None) -> None:
        self._provider = provider

    def extract(
        self,
        context: RagContext,
        *,
        engagement_id: str,
        default_period: FinancialPeriod,
        default_currency: str,
    ) -> tuple[FinancialObservation, ...]:
        if self._provider is not None:
            return self._from_candidates(
                self._provider.extract(context), context, engagement_id, "ai_assisted"
            )
        candidates: list[ExtractionCandidate] = []
        for result in context.results:
            for match in _PATTERN.finditer(result.text):
                raw = match.group("value").replace(",", "")
                negative = raw.startswith("(") and raw.endswith(")")
                raw = raw.strip("()")
                try:
                    value = Decimal(raw)
                except InvalidOperation:
                    continue
                if (
                    Decimal("1900") <= value <= Decimal("2100")
                    and match.group("currency") is None
                    and match.group("unit") is None
                ):
                    # A fiscal/calendar year is context, never a financial value.
                    continue
                if negative:
                    value = -value
                metric = _METRICS[" ".join(match.group("metric").casefold().split())]
                unit_text = match.group("unit")
                currency_text = match.group("currency")
                candidates.append(
                    ExtractionCandidate(
                        metric,
                        value,
                        _CURRENCIES.get(currency_text, currency_text or default_currency),
                        _UNITS.get((unit_text or "").casefold(), FinancialUnit.UNITS),
                        result.evidence.period or default_period,
                        ReportingStatus.FORECAST
                        if result.document_type in {DocumentType.BUDGET, DocumentType.FORECAST}
                        else ReportingStatus.ACTUAL,
                        MetricBasis.MANAGEMENT_ADJUSTED
                        if metric is FinancialMetric.ADJUSTED_EBITDA
                        else MetricBasis.REPORTED,
                        result.evidence.evidence_id,
                        "Matched an explicit metric and numeric value in retrieved evidence.",
                    )
                )
        return self._from_candidates(tuple(candidates), context, engagement_id, "deterministic")

    @staticmethod
    def _from_candidates(
        candidates: tuple[ExtractionCandidate, ...],
        context: RagContext,
        engagement_id: str,
        method: str,
    ) -> tuple[FinancialObservation, ...]:
        evidence = {item.evidence_id: item for item in context.evidence}
        result_by_evidence = {item.evidence.evidence_id: item for item in context.results}
        observations: list[FinancialObservation] = []
        for index, candidate in enumerate(candidates, start=1):
            source = evidence.get(candidate.evidence_id)
            result = result_by_evidence.get(candidate.evidence_id)
            if source is None or result is None:
                continue
            observations.append(
                FinancialObservation(
                    observation_id=f"fin-{method}-{index}",
                    engagement_id=engagement_id,
                    metric=candidate.metric,
                    value=candidate.value,
                    currency=candidate.currency,
                    unit=candidate.unit,
                    period=candidate.period,
                    reporting_status=candidate.reporting_status,
                    basis=candidate.basis,
                    source_document_type=result.document_type,
                    source_label=result.source_path,
                    evidence=(source,),
                    support_status=(
                        SupportStatus.UNVERIFIED
                        if candidate.value is None
                        else SupportStatus.SINGLE_SOURCE
                    ),
                    extraction_method=method,
                )
            )
        return tuple(observations)
