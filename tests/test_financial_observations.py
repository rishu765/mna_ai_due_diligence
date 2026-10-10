from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from ma_due_diligence.domain import DocumentType, SupportStatus
from ma_due_diligence.errors import DomainValidationError
from ma_due_diligence.financial.extraction import (
    ExtractionCandidate,
    FinancialExtractionService,
)
from ma_due_diligence.financial.fixtures import ENGAGEMENT_ID, build_financial_fixture_case
from ma_due_diligence.financial.models import (
    FinancialMetric,
    FinancialUnit,
    MetricBasis,
    ReconciliationStatus,
    ReportingStatus,
)
from ma_due_diligence.financial.normalization import normalize_unit, parse_period
from ma_due_diligence.financial.reconciliation import (
    FinancialReconciliationService,
    SourcePriorityPolicy,
)
from ma_due_diligence.retrieval.models import DiligenceEvidenceResult, RagContext


def test_financial_observation_preserves_unknown_instead_of_zero() -> None:
    known = build_financial_fixture_case().observations[0]
    missing = replace(
        known,
        observation_id="missing",
        value=None,
        currency=None,
        support_status=SupportStatus.MISSING,
        evidence=(),
    )
    assert missing.value is None
    with pytest.raises(DomainValidationError):
        replace(missing, value=Decimal("0"))


def test_unit_and_period_normalization_are_explicit() -> None:
    observation = build_financial_fixture_case().observations[0]
    in_units = normalize_unit(observation, FinancialUnit.UNITS)
    assert in_units.value == Decimal("80000000")
    assert parse_period("FY2025A").label == "FY2025A"
    assert parse_period("2025-09").label == "2025-09"
    with pytest.raises(DomainValidationError):
        parse_period("LTM")


def test_source_reconciliation_retains_values_and_prefers_audited() -> None:
    case = build_financial_fixture_case()
    revenue = tuple(
        item
        for item in case.observations
        if item.metric is FinancialMetric.REVENUE and item.period.label == "FY2025"
    )
    result = FinancialReconciliationService().reconcile(FinancialMetric.REVENUE, revenue)
    assert len(result.observations) == 4
    assert result.preferred_observation_id == "rev-audited-25"
    assert result.absolute_variance == Decimal("8")
    assert result.percent_variance == Decimal("8") / Decimal("92") * Decimal("100")
    assert result.status is ReconciliationStatus.CONFLICTING
    assert result.unresolved_conflict


def test_source_priority_can_be_overridden_by_metric() -> None:
    case = build_financial_fixture_case()
    revenue = tuple(item for item in case.observations if item.metric is FinancialMetric.REVENUE)
    policy = SourcePriorityPolicy(
        metric_overrides={
            FinancialMetric.REVENUE: (
                DocumentType.SALES_REPORT,
                DocumentType.FINANCIAL_STATEMENTS,
            )
        }
    )
    result = FinancialReconciliationService(policy).reconcile(
        FinancialMetric.REVENUE,
        tuple(item for item in revenue if item.period.label == "FY2025"),
    )
    assert result.preferred_observation_id == "rev-sales-25"


def test_reconciliation_rejects_mixed_currency_and_period() -> None:
    base = build_financial_fixture_case().observations[4]
    service = FinancialReconciliationService()
    currency = service.reconcile(
        FinancialMetric.REVENUE,
        (base, replace(base, observation_id="usd", currency="USD")),
    )
    assert currency.status is ReconciliationStatus.CURRENCY_MISMATCH
    period = service.reconcile(
        FinancialMetric.REVENUE,
        (base, replace(base, observation_id="old", period=parse_period("FY2024"))),
    )
    assert period.status is ReconciliationStatus.PERIOD_MISMATCH


def _context() -> RagContext:
    source = build_financial_fixture_case().observations[4].evidence[0]
    result = DiligenceEvidenceResult(
        "revenue",
        1,
        ENGAGEMENT_ID,
        source.document_id or "doc",
        "audited.pdf",
        DocumentType.FINANCIAL_STATEMENTS,
        (),
        "chunk-1",
        1.0,
        1.0,
        1.0,
        "Revenue GBP 92.0 million",
        source,
    )
    return RagContext("revenue", result.text, (source,), (result,), (), False)


def test_deterministic_extraction_consumes_bounded_evidence() -> None:
    period = parse_period("FY2025")
    observations = FinancialExtractionService().extract(
        _context(), engagement_id=ENGAGEMENT_ID, default_period=period, default_currency="GBP"
    )
    assert len(observations) == 1
    assert observations[0].metric is FinancialMetric.REVENUE
    assert observations[0].value == Decimal("92.0")
    assert observations[0].evidence[0].evidence_id == "ev-audited"


def test_mocked_llm_path_validates_candidates_and_preserves_null() -> None:
    period = parse_period("FY2025")

    class MockProvider:
        def extract(self, context: RagContext) -> tuple[ExtractionCandidate, ...]:
            return (
                ExtractionCandidate(
                    FinancialMetric.EBITDA,
                    None,
                    None,
                    FinancialUnit.MILLION,
                    period,
                    ReportingStatus.ACTUAL,
                    MetricBasis.REPORTED,
                    context.evidence[0].evidence_id,
                    "Evidence did not state EBITDA.",
                ),
            )

    observation = FinancialExtractionService(MockProvider()).extract(
        _context(), engagement_id=ENGAGEMENT_ID, default_period=period, default_currency="GBP"
    )[0]
    assert observation.value is None
    assert observation.support_status is SupportStatus.UNVERIFIED
    assert observation.extraction_method == "ai_assisted"
