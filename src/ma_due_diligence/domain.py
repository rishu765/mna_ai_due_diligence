"""Provider-neutral domain contracts for an evidence-first diligence workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from ma_due_diligence.errors import DomainValidationError

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")


def _text(value: str, name: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainValidationError(f"{name} must not be blank")
    return normalized


def _optional_text(value: str | None, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _currency(value: str) -> str:
    normalized = _text(value, "currency").upper()
    if not _CURRENCY_PATTERN.fullmatch(normalized):
        raise DomainValidationError("currency must be a three-letter uppercase code")
    return normalized


def _decimal(value: Decimal | int | str, name: str) -> Decimal:
    try:
        normalized = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise DomainValidationError(f"{name} must be a decimal value") from error
    if not normalized.is_finite():
        raise DomainValidationError(f"{name} must be finite")
    return normalized


def _unique(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    normalized = tuple(_text(value, name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise DomainValidationError(f"{name} must not contain duplicates")
    return normalized


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{name} must be timezone-aware")
    return value


class DiligenceWorkstream(StrEnum):
    FINANCIAL = "financial"
    COMMERCIAL = "commercial"
    LEGAL_CONTRACTUAL = "legal_contractual"
    OPERATIONAL = "operational"
    TAX = "tax"
    HR = "hr"
    TECHNOLOGY = "technology"
    CYBER = "cyber"
    REGULATORY = "regulatory"
    ESG = "esg"


class DealType(StrEnum):
    ACQUISITION = "acquisition"
    MERGER = "merger"
    DIVESTITURE = "divestiture"
    MINORITY_INVESTMENT = "minority_investment"
    OTHER = "other"


class ReviewStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    AWAITING_REVIEW = "awaiting_review"
    REVIEWED = "reviewed"
    COMPLETE = "complete"


class PeriodKind(StrEnum):
    FISCAL_YEAR = "fiscal_year"
    CALENDAR_YEAR = "calendar_year"
    MONTH = "month"
    QUARTER = "quarter"
    LTM = "ltm"
    NTM = "ntm"
    AS_OF = "as_of"
    OTHER = "other"


class DocumentType(StrEnum):
    FINANCIAL_STATEMENTS = "financial_statements"
    MANAGEMENT_ACCOUNTS = "management_accounts"
    GENERAL_LEDGER_EXPORT = "general_ledger_export"
    CUSTOMER_CONTRACT = "customer_contract"
    SUPPLIER_CONTRACT = "supplier_contract"
    SALES_REPORT = "sales_report"
    CUSTOMER_COHORT_REPORT = "customer_cohort_report"
    BUDGET = "budget"
    FORECAST = "forecast"
    BANK_STATEMENT = "bank_statement"
    DEBT_SCHEDULE = "debt_schedule"
    CAP_TABLE = "cap_table"
    TAX_DOCUMENT = "tax_document"
    BOARD_MATERIAL = "board_material"
    MANAGEMENT_PRESENTATION = "management_presentation"
    HR_REPORT = "hr_report"
    POLICY = "policy"
    LEGAL_AGREEMENT = "legal_agreement"
    OTHER = "other"


class Confidentiality(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"
    HIGHLY_CONFIDENTIAL = "highly_confidential"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class ParseStatus(StrEnum):
    NOT_STARTED = "not_started"
    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"


class EvidenceSourceType(StrEnum):
    VDR_DOCUMENT = "vdr_document"
    MANAGEMENT_RESPONSE = "management_response"
    EXTERNAL_SOURCE = "external_source"
    DETERMINISTIC_CALCULATION = "deterministic_calculation"


class ExtractionMethod(StrEnum):
    MANUAL = "manual"
    AI_ASSISTED = "ai_assisted"
    DETERMINISTIC = "deterministic"
    IMPORTED = "imported"


class SupportStatus(StrEnum):
    SOURCE_BACKED = "source_backed"
    VERIFIED = "verified"
    SINGLE_SOURCE = "single_source"
    CONFLICTING = "conflicting"
    DERIVED = "derived"
    UNVERIFIED = "unverified"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class FindingType(StrEnum):
    RED_FLAG = "red_flag"
    RISK = "risk"
    INCONSISTENCY = "inconsistency"
    FINANCIAL_ADJUSTMENT = "financial_adjustment"
    MISSING_INFORMATION = "missing_information"
    FOLLOW_UP_REQUIRED = "follow_up_required"
    POSITIVE_FINDING = "positive_finding"
    INFORMATIONAL = "informational"


class Severity(StrEnum):
    UNASSESSED = "unassessed"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class QualitativeMateriality(StrEnum):
    UNASSESSED = "unassessed"
    IMMATERIAL = "immaterial"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DealImpactArea(StrEnum):
    VALUATION = "valuation"
    PURCHASE_PRICE = "purchase_price"
    QUALITY_OF_EARNINGS = "quality_of_earnings"
    NET_DEBT = "net_debt"
    WORKING_CAPITAL = "working_capital"
    LEGAL_PROTECTIONS = "legal_protections"
    REPS_AND_WARRANTIES = "reps_and_warranties"
    INDEMNITY = "indemnity"
    CLOSING_CONDITION = "closing_condition"
    INTEGRATION_PLANNING = "integration_planning"
    DEAL_THESIS = "deal_thesis"
    FINANCING = "financing"
    POST_CLOSE_OPERATIONS = "post_close_operations"
    OTHER = "other"


class FindingStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    MITIGATED = "mitigated"
    CLOSED = "closed"


class LikelihoodBand(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AdjustmentType(StrEnum):
    ADD_BACK = "add_back"
    NORMALIZATION = "normalization"
    ONE_TIME_EXPENSE = "one_time_expense"
    OWNER_COMPENSATION = "owner_compensation"
    NONRECURRING_LEGAL_EXPENSE = "nonrecurring_legal_expense"
    RUN_RATE = "run_rate"
    REVENUE_NORMALIZATION = "revenue_normalization"
    OTHER = "other"


class AdjustmentDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"


class Recurrence(StrEnum):
    RECURRING = "recurring"
    NONRECURRING = "nonrecurring"
    UNCERTAIN = "uncertain"


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class AnalystDecision(StrEnum):
    PENDING = "pending"
    ACCEPT = "accept"
    REJECT = "reject"
    MODIFY = "modify"


class BalanceSheetItemType(StrEnum):
    WORKING_CAPITAL = "working_capital"
    DEBT_LIKE = "debt_like"
    CASH_LIKE = "cash_like"
    OFF_BALANCE_SHEET_OBLIGATION = "off_balance_sheet_obligation"


class InclusionTreatment(StrEnum):
    UNASSESSED = "unassessed"
    INCLUDE = "include"
    EXCLUDE = "exclude"
    PARTIAL = "partial"


class ConflictStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    ACCEPTED_DIFFERENCE = "accepted_difference"


class MissingInformationStatus(StrEnum):
    IDENTIFIED = "identified"
    REQUESTED = "requested"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    WAIVED = "waived"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class QuestionStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    ANSWERED = "answered"
    CLOSED = "closed"
    WITHDRAWN = "withdrawn"


class ReviewActionType(StrEnum):
    APPROVE_FINDING = "approve_finding"
    REJECT_FINDING = "reject_finding"
    CHANGE_SEVERITY = "change_severity"
    ACCEPT_ADJUSTMENT = "accept_adjustment"
    REJECT_ADJUSTMENT = "reject_adjustment"
    RESOLVE_CONFLICT = "resolve_conflict"
    MARK_NONMATERIAL = "mark_nonmaterial"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"


class ReportSectionType(StrEnum):
    EXECUTIVE_SUMMARY = "executive_summary"
    KEY_RED_FLAGS = "key_red_flags"
    FINANCIAL_DILIGENCE = "financial_diligence"
    COMMERCIAL_DILIGENCE = "commercial_diligence"
    LEGAL_CONTRACTUAL = "legal_contractual"
    OPERATIONAL = "operational"
    QOE_ADJUSTMENTS = "qoe_adjustments"
    WORKING_CAPITAL = "working_capital"
    NET_DEBT = "net_debt"
    MISSING_INFORMATION = "missing_information"
    FOLLOW_UP_REQUESTS = "follow_up_requests"
    LIMITATIONS = "limitations"


class WorkstreamStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETE = "complete"


class RunStatus(StrEnum):
    INITIALIZED = "initialized"
    IN_PROGRESS = "in_progress"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EntityReference:
    entity_id: str
    legal_name: str
    alternative_names: tuple[str, ...] = ()
    jurisdiction: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _text(self.entity_id, "entity_id"))
        object.__setattr__(self, "legal_name", _text(self.legal_name, "legal_name"))
        object.__setattr__(
            self, "alternative_names", _unique(self.alternative_names, "alternative_names")
        )
        object.__setattr__(self, "jurisdiction", _optional_text(self.jurisdiction, "jurisdiction"))


@dataclass(frozen=True, slots=True)
class FinancialPeriod:
    kind: PeriodKind
    label: str
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _text(self.label, "period label"))
        if (self.start_date is None) != (self.end_date is None):
            raise DomainValidationError("period start_date and end_date must be supplied together")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise DomainValidationError("period start_date must not follow end_date")
        if self.kind is PeriodKind.LTM and self.end_date is None:
            raise DomainValidationError("LTM periods require dates")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        normalized = _decimal(self.amount, "amount")
        if normalized < 0:
            raise DomainValidationError("amount must not be negative")
        object.__setattr__(self, "amount", normalized)
        object.__setattr__(self, "currency", _currency(self.currency))


@dataclass(frozen=True, slots=True)
class TransactionContext:
    deal_type: DealType
    description: str | None = None
    expected_signing_date: date | None = None
    expected_closing_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "description", _optional_text(self.description, "description"))
        if (
            self.expected_signing_date is not None
            and self.expected_closing_date is not None
            and self.expected_closing_date < self.expected_signing_date
        ):
            raise DomainValidationError("expected closing date must not precede signing date")


@dataclass(frozen=True, slots=True)
class DiligenceScope:
    workstreams: tuple[DiligenceWorkstream, ...]
    included_topics: tuple[str, ...] = ()
    excluded_topics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.workstreams:
            raise DomainValidationError("diligence scope requires at least one workstream")
        if len(set(self.workstreams)) != len(self.workstreams):
            raise DomainValidationError("workstreams must not contain duplicates")
        object.__setattr__(
            self, "included_topics", _unique(self.included_topics, "included_topics")
        )
        object.__setattr__(
            self, "excluded_topics", _unique(self.excluded_topics, "excluded_topics")
        )


@dataclass(frozen=True, slots=True)
class DiligenceEngagement:
    engagement_id: str
    target: EntityReference
    buyer: EntityReference | None
    transaction: TransactionContext
    scope: DiligenceScope
    as_of_date: date
    reporting_currency: str
    jurisdiction: str | None = None
    materiality_assumptions: tuple[str, ...] = ()
    review_status: ReviewStatus = ReviewStatus.NOT_STARTED

    def __post_init__(self) -> None:
        object.__setattr__(self, "engagement_id", _text(self.engagement_id, "engagement_id"))
        object.__setattr__(self, "reporting_currency", _currency(self.reporting_currency))
        object.__setattr__(self, "jurisdiction", _optional_text(self.jurisdiction, "jurisdiction"))
        object.__setattr__(
            self,
            "materiality_assumptions",
            _unique(self.materiality_assumptions, "materiality_assumptions"),
        )
        if self.buyer is not None and self.buyer.entity_id == self.target.entity_id:
            raise DomainValidationError("buyer and target must be different entities")


@dataclass(frozen=True, slots=True)
class VdrDocument:
    document_id: str
    engagement_id: str
    filename: str
    document_type: DocumentType
    workstreams: tuple[DiligenceWorkstream, ...]
    source_reference: str
    title: str | None = None
    entity: EntityReference | None = None
    period: FinancialPeriod | None = None
    version: str | None = None
    retrieved_at: datetime | None = None
    confidentiality: Confidentiality = Confidentiality.UNKNOWN
    parse_status: ParseStatus = ParseStatus.NOT_STARTED
    checksum_sha256: str | None = None
    source_metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in ("document_id", "engagement_id", "filename", "source_reference"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "title", _optional_text(self.title, "title"))
        object.__setattr__(self, "version", _optional_text(self.version, "version"))
        if not self.workstreams:
            raise DomainValidationError("document must have at least one workstream")
        if len(set(self.workstreams)) != len(self.workstreams):
            raise DomainValidationError("document workstreams must not contain duplicates")
        if self.retrieved_at is not None:
            _aware(self.retrieved_at, "retrieved_at")
        if self.checksum_sha256 is not None:
            checksum = self.checksum_sha256.casefold()
            if len(checksum) != 64:
                raise DomainValidationError("checksum_sha256 must have 64 hexadecimal characters")
            try:
                int(checksum, 16)
            except ValueError as error:
                raise DomainValidationError("checksum_sha256 must be hexadecimal") from error
            object.__setattr__(self, "checksum_sha256", checksum)
        keys = tuple(_text(key, "source metadata key") for key, _ in self.source_metadata)
        if len(set(keys)) != len(keys):
            raise DomainValidationError("source metadata keys must be unique")
        for key, value in self.source_metadata:
            _text(key, "source metadata key")
            _text(value, "source metadata value")


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_id: str
    source_type: EvidenceSourceType
    document_id: str | None = None
    external_source_reference: str | None = None
    page_numbers: tuple[int, ...] = ()
    section: str | None = None
    table: str | None = None
    row: str | None = None
    column: str | None = None
    sheet_name: str | None = None
    cell_range: str | None = None
    chunk_id: str | None = None
    source_text: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    period: FinancialPeriod | None = None
    retrieval_context: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _text(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "document_id", _optional_text(self.document_id, "document_id"))
        object.__setattr__(
            self,
            "external_source_reference",
            _optional_text(self.external_source_reference, "external_source_reference"),
        )
        if self.document_id is None and self.external_source_reference is None:
            raise DomainValidationError("evidence must identify a document or external source")
        if self.source_type is EvidenceSourceType.VDR_DOCUMENT and self.document_id is None:
            raise DomainValidationError("VDR document evidence requires document_id")
        if tuple(sorted(set(self.page_numbers))) != self.page_numbers:
            raise DomainValidationError("page_numbers must be unique and ordered")
        if any(page < 1 for page in self.page_numbers):
            raise DomainValidationError("page_numbers must be positive")
        for name in (
            "section",
            "table",
            "row",
            "column",
            "sheet_name",
            "cell_range",
            "chunk_id",
            "source_text",
            "retrieval_context",
        ):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        if (self.span_start is None) != (self.span_end is None):
            raise DomainValidationError("source span start and end must be supplied together")
        if self.span_start is not None and self.span_end is not None:
            if self.span_start < 0 or self.span_end <= self.span_start:
                raise DomainValidationError("source span must be non-negative and increasing")
            if self.source_text is None:
                raise DomainValidationError("a source span requires source_text")


@dataclass(frozen=True, slots=True)
class FactValue:
    original: str
    normalized_text: str | None = None
    numeric_value: Decimal | None = None
    date_value: date | None = None
    boolean_value: bool | None = None
    unit: str | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "original", _text(self.original, "original value"))
        object.__setattr__(
            self, "normalized_text", _optional_text(self.normalized_text, "normalized_text")
        )
        typed_count = sum(
            value is not None
            for value in (
                self.normalized_text,
                self.numeric_value,
                self.date_value,
                self.boolean_value,
            )
        )
        if typed_count > 1:
            raise DomainValidationError("fact value may have only one normalized representation")
        if self.numeric_value is not None:
            object.__setattr__(self, "numeric_value", _decimal(self.numeric_value, "numeric_value"))
        object.__setattr__(self, "unit", _optional_text(self.unit, "unit"))
        if self.currency is not None:
            object.__setattr__(self, "currency", _currency(self.currency))
            if self.numeric_value is None:
                raise DomainValidationError("currency requires a numeric value")


@dataclass(frozen=True, slots=True)
class DeterministicDerivation:
    derivation_id: str
    method: str
    input_fact_ids: tuple[str, ...]
    expression: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "derivation_id", _text(self.derivation_id, "derivation_id"))
        object.__setattr__(self, "method", _text(self.method, "method"))
        object.__setattr__(self, "input_fact_ids", _unique(self.input_fact_ids, "input_fact_ids"))
        object.__setattr__(self, "expression", _optional_text(self.expression, "expression"))
        if not self.input_fact_ids:
            raise DomainValidationError("a derivation requires input facts")


@dataclass(frozen=True, slots=True)
class DiligenceFact:
    fact_id: str
    engagement_id: str
    subject: EntityReference
    topic: str
    value: FactValue | None
    status: SupportStatus
    extraction_method: ExtractionMethod
    evidence: tuple[EvidenceReference, ...] = ()
    period: FinancialPeriod | None = None
    derivation: DeterministicDerivation | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        for name in ("fact_id", "engagement_id", "topic"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise DomainValidationError("fact evidence IDs must be unique")
        if self.status in {SupportStatus.MISSING, SupportStatus.NOT_APPLICABLE}:
            if self.value is not None:
                raise DomainValidationError("missing or not-applicable facts cannot have a value")
        elif self.value is None:
            raise DomainValidationError("a fact with a known status requires a value")
        evidence_required = {
            SupportStatus.SOURCE_BACKED,
            SupportStatus.VERIFIED,
            SupportStatus.SINGLE_SOURCE,
            SupportStatus.CONFLICTING,
        }
        if self.status in evidence_required and not self.evidence:
            raise DomainValidationError("source-supported facts require evidence")
        if self.status is SupportStatus.DERIVED and self.derivation is None:
            raise DomainValidationError("derived facts require deterministic derivation metadata")
        if self.derivation is not None and self.status is not SupportStatus.DERIVED:
            raise DomainValidationError("derivation metadata is only valid for derived facts")


@dataclass(frozen=True, slots=True)
class MaterialityAssessment:
    qualitative: QualitativeMateriality = QualitativeMateriality.UNASSESSED
    amount: Money | None = None
    percentage: Decimal | None = None
    benchmark: str | None = None
    threshold: Money | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        if self.percentage is not None:
            percentage = _decimal(self.percentage, "materiality percentage")
            if not Decimal("0") <= percentage <= Decimal("100"):
                raise DomainValidationError("materiality percentage must be between 0 and 100")
            object.__setattr__(self, "percentage", percentage)
            if self.benchmark is None:
                raise DomainValidationError("a materiality percentage requires a benchmark")
        object.__setattr__(self, "benchmark", _optional_text(self.benchmark, "benchmark"))
        object.__setattr__(self, "rationale", _optional_text(self.rationale, "rationale"))


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    category: str
    likelihood: LikelihoodBand
    impact_areas: tuple[DealImpactArea, ...]
    rationale: str
    mitigation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _text(self.category, "risk category"))
        object.__setattr__(self, "rationale", _text(self.rationale, "risk rationale"))
        object.__setattr__(self, "mitigation", _optional_text(self.mitigation, "mitigation"))
        if len(set(self.impact_areas)) != len(self.impact_areas):
            raise DomainValidationError("risk impact areas must not contain duplicates")


@dataclass(frozen=True, slots=True)
class DiligenceFinding:
    finding_id: str
    engagement_id: str
    workstream: DiligenceWorkstream
    category: str
    title: str
    description: str
    finding_type: FindingType
    severity: Severity
    materiality: MaterialityAssessment
    support_status: SupportStatus
    status: FindingStatus = FindingStatus.OPEN
    affected_topic: str | None = None
    supporting_fact_ids: tuple[str, ...] = ()
    conflicting_fact_ids: tuple[str, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    impact_areas: tuple[DealImpactArea, ...] = ()
    potential_deal_impact: str | None = None
    recommended_follow_up: str | None = None
    risk: RiskAssessment | None = None
    analyst_review_status: ReviewStatus = ReviewStatus.NOT_STARTED

    def __post_init__(self) -> None:
        for name in ("finding_id", "engagement_id", "category", "title", "description"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("affected_topic", "potential_deal_impact", "recommended_follow_up"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(
            self, "supporting_fact_ids", _unique(self.supporting_fact_ids, "supporting_fact_ids")
        )
        object.__setattr__(
            self, "conflicting_fact_ids", _unique(self.conflicting_fact_ids, "conflicting_fact_ids")
        )
        if set(self.supporting_fact_ids) & set(self.conflicting_fact_ids):
            raise DomainValidationError("a fact cannot be both supporting and conflicting")
        if len(set(self.impact_areas)) != len(self.impact_areas):
            raise DomainValidationError("finding impact areas must not contain duplicates")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise DomainValidationError("finding evidence IDs must be unique")
        if self.support_status in {
            SupportStatus.SOURCE_BACKED,
            SupportStatus.VERIFIED,
            SupportStatus.SINGLE_SOURCE,
        } and not (self.evidence or self.supporting_fact_ids):
            raise DomainValidationError("supported findings require facts or direct evidence")
        if self.support_status is SupportStatus.CONFLICTING and not self.conflicting_fact_ids:
            raise DomainValidationError("conflicting findings require conflicting facts")
        if self.finding_type is FindingType.RISK and self.risk is None:
            raise DomainValidationError("risk findings require a risk assessment")


@dataclass(frozen=True, slots=True)
class FinancialAdjustment:
    adjustment_id: str
    engagement_id: str
    adjustment_type: AdjustmentType
    affected_metric: str
    amount: Money
    period: FinancialPeriod
    direction: AdjustmentDirection
    recurrence: Recurrence
    proposal_status: ProposalStatus
    rationale: str
    evidence: tuple[EvidenceReference, ...]
    verification_status: SupportStatus
    analyst_decision: AnalystDecision = AnalystDecision.PENDING
    finding_id: str | None = None
    input_fact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("adjustment_id", "engagement_id", "affected_metric", "rationale"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "finding_id", _optional_text(self.finding_id, "finding_id"))
        object.__setattr__(self, "input_fact_ids", _unique(self.input_fact_ids, "input_fact_ids"))
        if (
            self.verification_status
            in {
                SupportStatus.SOURCE_BACKED,
                SupportStatus.VERIFIED,
                SupportStatus.SINGLE_SOURCE,
            }
            and not self.evidence
        ):
            raise DomainValidationError("verified adjustments require evidence")
        if (
            self.proposal_status is ProposalStatus.ACCEPTED
            and self.analyst_decision is not AnalystDecision.ACCEPT
        ):
            raise DomainValidationError("accepted adjustments require an analyst acceptance")


@dataclass(frozen=True, slots=True)
class BalanceSheetItem:
    item_id: str
    engagement_id: str
    item_type: BalanceSheetItemType
    description: str
    amount: Money | None
    as_of_date: date | None
    treatment: InclusionTreatment
    rationale: str
    evidence: tuple[EvidenceReference, ...]
    verification_status: SupportStatus
    analyst_decision: AnalystDecision = AnalystDecision.PENDING

    def __post_init__(self) -> None:
        for name in ("item_id", "engagement_id", "description", "rationale"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if (self.amount is None) != (self.as_of_date is None):
            raise DomainValidationError("balance-sheet amount and as-of date must appear together")
        if self.verification_status is SupportStatus.MISSING and self.amount is not None:
            raise DomainValidationError("a missing balance-sheet item cannot have an amount")
        if (
            self.verification_status
            in {
                SupportStatus.SOURCE_BACKED,
                SupportStatus.VERIFIED,
                SupportStatus.SINGLE_SOURCE,
            }
            and not self.evidence
        ):
            raise DomainValidationError("source-supported balance-sheet items require evidence")


@dataclass(frozen=True, slots=True)
class FactConflict:
    conflict_id: str
    engagement_id: str
    topic: str
    observation_fact_ids: tuple[str, ...]
    status: ConflictStatus
    evidence: tuple[EvidenceReference, ...] = ()
    preferred_fact_id: str | None = None
    resolution_rationale: str | None = None
    resolved_by_review_action_id: str | None = None
    review_required: bool = True

    def __post_init__(self) -> None:
        for name in ("conflict_id", "engagement_id", "topic"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self,
            "observation_fact_ids",
            _unique(self.observation_fact_ids, "observation_fact_ids"),
        )
        if len(self.observation_fact_ids) < 2:
            raise DomainValidationError("a conflict requires at least two observations")
        for name in ("preferred_fact_id", "resolution_rationale", "resolved_by_review_action_id"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        resolved = self.status in {ConflictStatus.RESOLVED, ConflictStatus.ACCEPTED_DIFFERENCE}
        if resolved:
            if self.resolution_rationale is None or self.resolved_by_review_action_id is None:
                raise DomainValidationError("resolved conflicts must retain resolution metadata")
            if self.status is ConflictStatus.RESOLVED and self.preferred_fact_id is None:
                raise DomainValidationError("resolved conflicts require a preferred fact")
        elif any(
            value is not None
            for value in (
                self.preferred_fact_id,
                self.resolution_rationale,
                self.resolved_by_review_action_id,
            )
        ):
            raise DomainValidationError("open conflicts cannot carry resolution metadata")
        if (
            self.preferred_fact_id is not None
            and self.preferred_fact_id not in self.observation_fact_ids
        ):
            raise DomainValidationError("preferred fact must be one of the observations")


@dataclass(frozen=True, slots=True)
class MissingInformation:
    missing_item_id: str
    engagement_id: str
    requested_item: str
    workstream: DiligenceWorkstream
    importance: Priority
    reason_needed: str
    status: MissingInformationStatus
    blocking: bool
    follow_up_question: str | None = None
    related_finding_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("missing_item_id", "engagement_id", "requested_item", "reason_needed"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self,
            "follow_up_question",
            _optional_text(self.follow_up_question, "follow_up_question"),
        )
        object.__setattr__(
            self,
            "related_finding_id",
            _optional_text(self.related_finding_id, "related_finding_id"),
        )


@dataclass(frozen=True, slots=True)
class FollowUpQuestion:
    question_id: str
    engagement_id: str
    workstream: DiligenceWorkstream
    question: str
    priority: Priority
    rationale: str
    status: QuestionStatus = QuestionStatus.DRAFT
    related_finding_id: str | None = None
    requested_document_or_data: str | None = None
    response: str | None = None
    response_evidence: tuple[EvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        for name in ("question_id", "engagement_id", "question", "rationale"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("related_finding_id", "requested_document_or_data", "response"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        if self.status is QuestionStatus.ANSWERED and self.response is None:
            raise DomainValidationError("answered questions require a response")
        if self.response_evidence and self.response is None:
            raise DomainValidationError("response evidence requires a response")


@dataclass(frozen=True, slots=True)
class StateField:
    name: str
    value: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "state field name"))
        object.__setattr__(self, "value", _optional_text(self.value, "state field value"))


@dataclass(frozen=True, slots=True)
class HumanReviewAction:
    action_id: str
    engagement_id: str
    subject_type: str
    subject_id: str
    action: ReviewActionType
    reviewer: str
    rationale: str
    occurred_at: datetime
    prior_state: tuple[StateField, ...]
    resulting_state: tuple[StateField, ...]

    def __post_init__(self) -> None:
        for name in (
            "action_id",
            "engagement_id",
            "subject_type",
            "subject_id",
            "reviewer",
            "rationale",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        _aware(self.occurred_at, "occurred_at")
        if not self.resulting_state:
            raise DomainValidationError("a human review action requires resulting state")
        for state, name in (
            (self.prior_state, "prior_state"),
            (self.resulting_state, "resulting_state"),
        ):
            fields = [item.name for item in state]
            if len(set(fields)) != len(fields):
                raise DomainValidationError(f"{name} field names must be unique")


@dataclass(frozen=True, slots=True)
class ReportSectionContract:
    section: ReportSectionType
    title: str
    workstream: DiligenceWorkstream | None = None
    finding_ids: tuple[str, ...] = ()
    adjustment_ids: tuple[str, ...] = ()
    missing_item_ids: tuple[str, ...] = ()
    limitation_ids: tuple[str, ...] = ()
    requires_human_approval: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _text(self.title, "report section title"))
        for name in ("finding_ids", "adjustment_ids", "missing_item_ids", "limitation_ids"):
            object.__setattr__(self, name, _unique(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class WorkstreamSummary:
    workstream: DiligenceWorkstream
    status: WorkstreamStatus
    finding_count: int
    high_or_critical_count: int
    open_question_count: int

    def __post_init__(self) -> None:
        values = (self.finding_count, self.high_or_critical_count, self.open_question_count)
        if any(value < 0 for value in values):
            raise DomainValidationError("workstream summary counts must be non-negative")
        if self.high_or_critical_count > self.finding_count:
            raise DomainValidationError("high finding count cannot exceed total finding count")


@dataclass(frozen=True, slots=True)
class DiligenceSummary:
    engagement: DiligenceEngagement
    workstreams: tuple[WorkstreamSummary, ...]
    total_findings: int
    high_or_critical_findings: int
    unresolved_conflicts: int
    missing_information_count: int
    proposed_adjustment_count: int
    human_review_status: ReviewStatus

    def __post_init__(self) -> None:
        counts = (
            self.total_findings,
            self.high_or_critical_findings,
            self.unresolved_conflicts,
            self.missing_information_count,
            self.proposed_adjustment_count,
        )
        if any(count < 0 for count in counts):
            raise DomainValidationError("summary counts must be non-negative")
        if self.high_or_critical_findings > self.total_findings:
            raise DomainValidationError("high finding count cannot exceed total findings")
        streams = [item.workstream for item in self.workstreams]
        if len(set(streams)) != len(streams):
            raise DomainValidationError("workstream summaries must be unique")


@dataclass(frozen=True, slots=True)
class ProvenanceChain:
    chain_id: str
    engagement_id: str
    finding_id: str | None
    adjustment_id: str | None
    fact_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    derivation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("chain_id", "engagement_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "finding_id", _optional_text(self.finding_id, "finding_id"))
        object.__setattr__(
            self, "adjustment_id", _optional_text(self.adjustment_id, "adjustment_id")
        )
        if (self.finding_id is None) == (self.adjustment_id is None):
            raise DomainValidationError("lineage must identify exactly one finding or adjustment")
        for name in ("fact_ids", "evidence_ids", "document_ids", "derivation_ids"):
            object.__setattr__(self, name, _unique(getattr(self, name), name))
        if not self.fact_ids or not self.evidence_ids or not self.document_ids:
            raise DomainValidationError("lineage requires facts, evidence, and documents")


@dataclass(frozen=True, slots=True)
class DiligenceFixtureSet:
    engagement: DiligenceEngagement
    documents: tuple[VdrDocument, ...]
    evidence: tuple[EvidenceReference, ...]
    facts: tuple[DiligenceFact, ...]
    findings: tuple[DiligenceFinding, ...]
    conflicts: tuple[FactConflict, ...]
    adjustments: tuple[FinancialAdjustment, ...]
    balance_sheet_items: tuple[BalanceSheetItem, ...]
    missing_information: tuple[MissingInformation, ...]
    questions: tuple[FollowUpQuestion, ...]
    review_actions: tuple[HumanReviewAction, ...]
    provenance: tuple[ProvenanceChain, ...]

    def __post_init__(self) -> None:
        engagement_id = self.engagement.engagement_id
        record_engagement_ids = (
            *(item.engagement_id for item in self.documents),
            *(item.engagement_id for item in self.facts),
            *(item.engagement_id for item in self.findings),
            *(item.engagement_id for item in self.conflicts),
            *(item.engagement_id for item in self.adjustments),
            *(item.engagement_id for item in self.balance_sheet_items),
            *(item.engagement_id for item in self.missing_information),
            *(item.engagement_id for item in self.questions),
            *(item.engagement_id for item in self.review_actions),
            *(item.engagement_id for item in self.provenance),
        )
        if any(value != engagement_id for value in record_engagement_ids):
            raise DomainValidationError("fixture records must belong to one engagement")
