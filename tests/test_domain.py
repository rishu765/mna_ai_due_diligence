from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ma_due_diligence.domain import (
    AdjustmentDirection,
    AdjustmentType,
    AnalystDecision,
    BalanceSheetItem,
    BalanceSheetItemType,
    ConflictStatus,
    DealType,
    DiligenceEngagement,
    DiligenceFixtureSet,
    DiligenceScope,
    DiligenceWorkstream,
    DocumentType,
    EntityReference,
    EvidenceReference,
    EvidenceSourceType,
    FactValue,
    FinancialAdjustment,
    FinancialPeriod,
    FindingType,
    HumanReviewAction,
    InclusionTreatment,
    MaterialityAssessment,
    MissingInformationStatus,
    Money,
    PeriodKind,
    Priority,
    ProposalStatus,
    ProvenanceChain,
    QualitativeMateriality,
    QuestionStatus,
    Recurrence,
    ReviewActionType,
    Severity,
    StateField,
    SupportStatus,
    TransactionContext,
)
from ma_due_diligence.errors import DomainValidationError
from ma_due_diligence.serialization import model_from_json, model_to_json


def test_engagement_model_preserves_scope_and_optional_buyer(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    engagement = diligence_fixture.engagement
    assert engagement.target.legal_name == "Northstar Components Ltd"
    assert engagement.reporting_currency == "GBP"
    assert DiligenceWorkstream.FINANCIAL in engagement.scope.workstreams
    assert replace(engagement, buyer=None).buyer is None


def test_engagement_rejects_duplicate_entity() -> None:
    entity = EntityReference("same", "Same Company")
    with pytest.raises(DomainValidationError, match="different entities"):
        DiligenceEngagement(
            "eng-1",
            entity,
            entity,
            TransactionContext(DealType.ACQUISITION),
            DiligenceScope((DiligenceWorkstream.FINANCIAL,)),
            date(2026, 1, 1),
            "USD",
        )


def test_vdr_document_retains_classification_and_period(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    document = diligence_fixture.documents[0]
    assert document.document_type is DocumentType.FINANCIAL_STATEMENTS
    assert document.period is not None and document.period.label == "FY2025"
    assert document.source_reference == "vdr://1.01"


def test_evidence_reference_supports_precise_source_locations(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    evidence = diligence_fixture.evidence[0]
    assert evidence.document_id == "doc-audited-fs"
    assert evidence.page_numbers == (42,)
    assert evidence.table == "Segment revenue"
    assert evidence.row == "Total revenue"


def test_evidence_reference_requires_an_identifiable_source() -> None:
    with pytest.raises(DomainValidationError, match="identify"):
        EvidenceReference("ev-1", EvidenceSourceType.EXTERNAL_SOURCE)


def test_fact_handles_numeric_and_text_values(diligence_fixture: DiligenceFixtureSet) -> None:
    revenue = diligence_fixture.facts[0]
    clause = diligence_fixture.facts[4]
    assert revenue.value is not None and revenue.value.numeric_value == Decimal("95.0")
    assert clause.value is not None and clause.value.normalized_text == "termination_right"
    assert revenue.evidence[0].document_id == "doc-audited-fs"


def test_unknown_is_not_zero(diligence_fixture: DiligenceFixtureSet) -> None:
    missing = diligence_fixture.facts[5]
    assert missing.status is SupportStatus.MISSING
    assert missing.value is None
    with pytest.raises(DomainValidationError, match="cannot have a value"):
        replace(missing, value=FactValue("0", numeric_value=Decimal("0")))


def test_source_backed_fact_requires_evidence(diligence_fixture: DiligenceFixtureSet) -> None:
    fact = diligence_fixture.facts[0]
    with pytest.raises(DomainValidationError, match="require evidence"):
        replace(fact, evidence=())


def test_finding_keeps_severity_separate_from_materiality(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    finding = diligence_fixture.findings[0]
    revised = replace(
        finding,
        severity=Severity.CRITICAL,
        materiality=MaterialityAssessment(QualitativeMateriality.LOW),
    )
    assert revised.severity is Severity.CRITICAL
    assert revised.materiality.qualitative is QualitativeMateriality.LOW


def test_risk_finding_requires_risk_assessment(diligence_fixture: DiligenceFixtureSet) -> None:
    finding = diligence_fixture.findings[0]
    assert finding.finding_type is FindingType.RISK
    with pytest.raises(DomainValidationError, match="risk assessment"):
        replace(finding, risk=None)


def test_materiality_percentage_has_range_and_benchmark() -> None:
    with pytest.raises(DomainValidationError, match="between 0 and 100"):
        MaterialityAssessment(percentage=Decimal("101"), benchmark="Revenue")
    with pytest.raises(DomainValidationError, match="benchmark"):
        MaterialityAssessment(percentage=Decimal("10"))


def test_financial_adjustment_is_proposal_not_calculation(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    adjustment = diligence_fixture.adjustments[0]
    assert adjustment.adjustment_type is AdjustmentType.NONRECURRING_LEGAL_EXPENSE
    assert adjustment.direction is AdjustmentDirection.INCREASE
    assert adjustment.proposal_status is ProposalStatus.PROPOSED
    assert adjustment.analyst_decision is AnalystDecision.PENDING


def test_accepted_adjustment_requires_analyst_acceptance(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    adjustment = diligence_fixture.adjustments[0]
    with pytest.raises(DomainValidationError, match="analyst acceptance"):
        replace(adjustment, proposal_status=ProposalStatus.ACCEPTED)


def test_debt_like_and_working_capital_items_are_distinct(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    debt_like, working_capital = diligence_fixture.balance_sheet_items
    assert debt_like.item_type is BalanceSheetItemType.DEBT_LIKE
    assert debt_like.treatment is InclusionTreatment.INCLUDE
    assert working_capital.item_type is BalanceSheetItemType.WORKING_CAPITAL
    assert working_capital.treatment is InclusionTreatment.UNASSESSED


def test_balance_sheet_unknown_amount_stays_none(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    example = diligence_fixture.balance_sheet_items[0]
    unknown = BalanceSheetItem(
        "item-unknown",
        example.engagement_id,
        BalanceSheetItemType.OFF_BALANCE_SHEET_OBLIGATION,
        "Unknown lease obligation",
        None,
        None,
        InclusionTreatment.UNASSESSED,
        "Documents have not been provided.",
        (),
        SupportStatus.MISSING,
    )
    assert unknown.amount is None


def test_conflict_retains_both_observations(diligence_fixture: DiligenceFixtureSet) -> None:
    conflict = diligence_fixture.conflicts[0]
    assert conflict.status is ConflictStatus.OPEN
    assert conflict.observation_fact_ids == (
        "fact-revenue-audited",
        "fact-revenue-management",
    )
    assert conflict.preferred_fact_id is None


def test_resolved_conflict_requires_resolution_metadata(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    conflict = diligence_fixture.conflicts[0]
    with pytest.raises(DomainValidationError, match="resolution metadata"):
        replace(conflict, status=ConflictStatus.RESOLVED)
    resolved = replace(
        conflict,
        status=ConflictStatus.RESOLVED,
        preferred_fact_id="fact-revenue-audited",
        resolution_rationale="Audited statements are authoritative for reported revenue.",
        resolved_by_review_action_id="review-revenue-001",
        review_required=False,
    )
    assert resolved.preferred_fact_id == "fact-revenue-audited"


def test_missing_information_and_follow_up_are_structured(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    missing = diligence_fixture.missing_information[0]
    question = diligence_fixture.questions[0]
    assert missing.status is MissingInformationStatus.REQUESTED
    assert missing.blocking is True
    assert question.priority is Priority.URGENT
    assert question.requested_document_or_data == "Debt schedule and covenant documents"


def test_answered_question_requires_response(diligence_fixture: DiligenceFixtureSet) -> None:
    question = diligence_fixture.questions[0]
    with pytest.raises(DomainValidationError, match="require a response"):
        replace(question, status=QuestionStatus.ANSWERED)


def test_human_review_preserves_prior_and_resulting_state(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    action = diligence_fixture.review_actions[0]
    assert action.action is ReviewActionType.APPROVE_FINDING
    assert action.prior_state[0].value == "awaiting_review"
    assert action.resulting_state[0].value == "reviewed"
    assert action.occurred_at.tzinfo is not None


def test_review_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        HumanReviewAction(
            "review-1",
            "eng-1",
            "finding",
            "finding-1",
            ReviewActionType.REJECT_FINDING,
            "Analyst",
            "Evidence is insufficient.",
            datetime(2026, 1, 1),
            (),
            (StateField("status", "rejected"),),
        )


def test_provenance_chain_reaches_document(diligence_fixture: DiligenceFixtureSet) -> None:
    chain = diligence_fixture.provenance[0]
    fact = next(item for item in diligence_fixture.facts if item.fact_id == chain.fact_ids[0])
    evidence = next(
        item for item in diligence_fixture.evidence if item.evidence_id == chain.evidence_ids[0]
    )
    document = next(
        item for item in diligence_fixture.documents if item.document_id == chain.document_ids[0]
    )
    assert fact.evidence[0].evidence_id == evidence.evidence_id
    assert evidence.document_id == document.document_id


def test_provenance_identifies_exactly_one_output() -> None:
    with pytest.raises(DomainValidationError, match="exactly one"):
        ProvenanceChain(
            "chain-1",
            "eng-1",
            "finding-1",
            "adjustment-1",
            ("fact-1",),
            ("evidence-1",),
            ("document-1",),
        )


def test_serialization_round_trip_preserves_enums_decimals_and_dates(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    payload = model_to_json(diligence_fixture)
    restored = model_from_json(payload, DiligenceFixtureSet)
    assert restored == diligence_fixture
    assert restored.adjustments[0].amount.amount == Decimal("1.2")
    assert restored.documents[0].document_type is DocumentType.FINANCIAL_STATEMENTS
    assert restored.engagement.as_of_date == date(2026, 2, 15)
    assert payload == model_to_json(diligence_fixture)


def test_fixture_catalog_contains_ten_scenarios() -> None:
    path = Path(__file__).parents[1] / "data" / "fixtures" / "m0_scenarios.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["fictitious"] is True
    assert len(data["scenarios"]) == 10


def test_currency_and_percentage_validation() -> None:
    with pytest.raises(DomainValidationError, match="three-letter"):
        Money(Decimal("1"), "dollars")
    with pytest.raises(DomainValidationError, match="only one normalized"):
        FactValue("yes", normalized_text="yes", boolean_value=True)


def test_period_validation() -> None:
    with pytest.raises(DomainValidationError, match="supplied together"):
        FinancialPeriod(PeriodKind.FISCAL_YEAR, "FY2025", start_date=date(2025, 1, 1))


def test_adjustment_direction_is_mandatory() -> None:
    period = FinancialPeriod(PeriodKind.FISCAL_YEAR, "FY2025")
    evidence = EvidenceReference("ev-1", EvidenceSourceType.VDR_DOCUMENT, document_id="doc-1")
    adjustment = FinancialAdjustment(
        "adj-1",
        "eng-1",
        AdjustmentType.ADD_BACK,
        "EBITDA",
        Money(Decimal("1"), "USD"),
        period,
        AdjustmentDirection.INCREASE,
        Recurrence.NONRECURRING,
        ProposalStatus.PROPOSED,
        "One-time expense.",
        (evidence,),
        SupportStatus.SINGLE_SOURCE,
    )
    assert adjustment.direction is AdjustmentDirection.INCREASE
