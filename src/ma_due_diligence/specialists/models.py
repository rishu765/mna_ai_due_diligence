"""Typed specialist, claim, investigation, consolidation, and trace contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from ma_due_diligence.domain import (
    DiligenceEngagement,
    DiligenceFact,
    DiligenceFinding,
    DiligenceWorkstream,
    DocumentType,
    EvidenceReference,
    FactConflict,
    FinancialPeriod,
    FollowUpQuestion,
    MissingInformation,
    Priority,
    VdrDocument,
)
from ma_due_diligence.errors import DomainValidationError
from ma_due_diligence.financial.models import FinancialFindingOutput
from ma_due_diligence.retrieval.models import DiligenceEvidenceResult, RetrievalWarning


def _text(value: str, name: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainValidationError(f"{name} must not be blank")
    return normalized


class AgentId(StrEnum):
    FINANCIAL = "financial_specialist"
    COMMERCIAL = "commercial_specialist"
    LEGAL_CONTRACTUAL = "legal_contractual_specialist"
    OPERATIONAL = "operational_specialist"
    CROSS_DOCUMENT = "cross_document_investigator"


class ClaimValueKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"


class ClaimStatus(StrEnum):
    ASSERTED = "asserted"
    SOURCE_BACKED = "source_backed"
    SUPERSEDED = "superseded"
    CONFLICTING = "conflicting"


class SourceAuthority(StrEnum):
    SIGNED_CONTRACT = "signed_contract"
    AUDITED = "audited"
    DIRECT_SCHEDULE = "direct_schedule"
    BOARD_REPORT = "board_report"
    MANAGEMENT_ACCOUNTS = "management_accounts"
    MANAGEMENT_NARRATIVE = "management_narrative"
    OTHER = "other"


class ComparisonOutcome(StrEnum):
    ALIGNED = "aligned"
    CONFLICT = "conflict"
    NOT_COMPARABLE = "not_comparable"
    SUPERSEDED = "superseded"


class FindingRelationshipType(StrEnum):
    RELATED = "related"
    AMPLIFIES = "amplifies"
    DEPENDS_ON = "depends_on"
    CAUSED_BY = "caused_by"
    CONTRADICTS = "contradicts"


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    agent_id: AgentId
    workstreams: tuple[DiligenceWorkstream, ...]
    document_types: tuple[DocumentType, ...]
    queries: tuple[str, ...]
    top_k_per_query: int = 6

    def __post_init__(self) -> None:
        if not self.workstreams or not self.document_types or not self.queries:
            raise DomainValidationError(
                "retrieval plans require workstreams, document types, and queries"
            )
        if self.top_k_per_query < 1:
            raise DomainValidationError("top_k_per_query must be positive")


@dataclass(frozen=True, slots=True)
class InvestigationClaim:
    claim_id: str
    subject: str
    topic: str
    value_kind: ClaimValueKind
    statement: str
    evidence: EvidenceReference
    document_type: DocumentType
    workstream: DiligenceWorkstream
    authority: SourceAuthority
    text_value: str | None = None
    numeric_value: Decimal | None = None
    boolean_value: bool | None = None
    date_value: date | None = None
    unit: str | None = None
    period: FinancialPeriod | None = None
    entity_id: str | None = None
    version: str | None = None
    effective_date: date | None = None
    logical_document_key: str | None = None
    status: ClaimStatus = ClaimStatus.SOURCE_BACKED

    def __post_init__(self) -> None:
        for name in ("claim_id", "subject", "topic", "statement"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        values = (self.text_value, self.numeric_value, self.boolean_value, self.date_value)
        if sum(value is not None for value in values) != 1:
            raise DomainValidationError("claims require exactly one typed value")
        expected = {
            ClaimValueKind.TEXT: self.text_value,
            ClaimValueKind.NUMBER: self.numeric_value,
            ClaimValueKind.BOOLEAN: self.boolean_value,
            ClaimValueKind.DATE: self.date_value,
        }[self.value_kind]
        if expected is None:
            raise DomainValidationError("claim value does not match value_kind")
        if self.numeric_value is not None and not self.numeric_value.is_finite():
            raise DomainValidationError("numeric claim must be finite")


@dataclass(frozen=True, slots=True)
class AttributedFinding:
    finding: DiligenceFinding
    contributing_agents: tuple[AgentId, ...]
    source_finding_ids: tuple[str, ...]
    uncertainty: str | None = None
    claim_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.contributing_agents or len(set(self.contributing_agents)) != len(
            self.contributing_agents
        ):
            raise DomainValidationError("attributed findings require unique contributing agents")


@dataclass(frozen=True, slots=True)
class SpecialistContext:
    engagement: DiligenceEngagement
    documents: tuple[VdrDocument, ...]
    evidence_results: tuple[DiligenceEvidenceResult, ...]
    claims: tuple[InvestigationClaim, ...]
    facts: tuple[DiligenceFact, ...] = ()
    existing_findings: tuple[DiligenceFinding, ...] = ()
    financial_findings: tuple[FinancialFindingOutput, ...] = ()
    retrieval_warnings: tuple[RetrievalWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentError:
    agent_id: AgentId
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class SpecialistResult:
    agent_id: AgentId
    findings: tuple[AttributedFinding, ...]
    missing_information: tuple[MissingInformation, ...]
    questions: tuple[FollowUpQuestion, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClaimComparison:
    comparison_id: str
    left_claim_id: str
    right_claim_id: str
    outcome: ComparisonOutcome
    rationale: str
    preferred_claim_id: str | None = None
    conflict: FactConflict | None = None


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    comparisons: tuple[ClaimComparison, ...]
    conflicts: tuple[FactConflict, ...]
    superseded_claim_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FindingRelationship:
    relationship_id: str
    source_finding_id: str
    target_finding_id: str
    relationship: FindingRelationshipType
    rationale: str


@dataclass(frozen=True, slots=True)
class InvestigationTrace:
    trace_id: str
    finding_id: str
    agent_ids: tuple[AgentId, ...]
    fact_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    document_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsolidatedRequest:
    request_id: str
    question: str
    workstreams: tuple[DiligenceWorkstream, ...]
    priority: Priority
    rationale: str
    related_finding_ids: tuple[str, ...]
    requested_document_or_data: str | None = None


@dataclass(frozen=True, slots=True)
class GroundedExplanation:
    finding_id: str
    explanation: str
    caveats: tuple[str, ...]
    deal_implication: str
    follow_up: str | None
    cited_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoordinatorResult:
    specialist_results: tuple[SpecialistResult, ...]
    investigation: InvestigationResult
    findings: tuple[AttributedFinding, ...]
    relationships: tuple[FindingRelationship, ...]
    missing_information: tuple[MissingInformation, ...]
    requests: tuple[ConsolidatedRequest, ...]
    traces: tuple[InvestigationTrace, ...]
    errors: tuple[AgentError, ...]
