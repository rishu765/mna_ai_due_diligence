"""Typed contracts for the checkpointed final diligence workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import NotRequired

from typing_extensions import TypedDict

from ma_due_diligence.domain import (
    DiligenceEngagement,
    EvidenceReference,
    FactConflict,
    HumanReviewAction,
    MissingInformation,
    ReviewActionType,
    Severity,
    VdrDocument,
)
from ma_due_diligence.financial.models import (
    CustomerConcentrationResult,
    EbitdaBridge,
    FinancialFindingOutput,
    NetDebtBridge,
    NwcPegResult,
    ReconciliationResult,
    WorkingCapitalTrend,
)
from ma_due_diligence.retrieval.index import InMemoryDiligenceIndex
from ma_due_diligence.retrieval.models import DiligenceEvidenceResult
from ma_due_diligence.specialists.models import (
    AttributedFinding,
    ConsolidatedRequest,
    CoordinatorResult,
    FindingRelationship,
    SpecialistResult,
)
from ma_due_diligence.vdr.models import VdrCorpus


class WorkflowStatus(StrEnum):
    CREATED = "created"
    INGESTING = "ingesting"
    ANALYZING = "analyzing"
    REVIEW_REQUIRED = "review_required"
    WAITING_FOR_INFORMATION = "waiting_for_information"
    RESUMING = "resuming"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class FailureCode(StrEnum):
    NO_DOCUMENTS = "no_documents"
    INGESTION_FAILED = "ingestion_failed"
    RETRIEVAL_INSUFFICIENT = "retrieval_insufficient"
    FINANCIAL_ANALYSIS_INCOMPLETE = "financial_analysis_incomplete"
    SPECIALIST_ANALYSIS_FAILED = "specialist_analysis_failed"
    REVIEW_REQUIRED = "review_required"
    MISSING_CRITICAL_INFORMATION = "missing_critical_information"
    REPORT_GENERATION_FAILED = "report_generation_failed"
    INVALID_INPUT = "invalid_input"


class ReviewPolicy(StrEnum):
    WHEN_NEEDED = "when_needed"
    ALWAYS = "always"
    NEVER = "never"


class ReportStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"
    UNAVAILABLE = "unavailable"


class PriorityBand(StrEnum):
    IMMEDIATE = "immediate"
    HIGH = "high"
    STANDARD = "standard"


class ReviewDecisionInput(TypedDict):
    subject_type: str
    subject_id: str
    action: str
    rationale: str
    severity: NotRequired[str]
    preferred_source_id: NotRequired[str]


class HumanReviewInput(TypedDict):
    reviewer: str
    rationale: str
    decisions: list[ReviewDecisionInput]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    ingestion: int = 1
    report: int = 1

    def __post_init__(self) -> None:
        if self.ingestion < 0 or self.report < 0:
            raise ValueError("retry limits must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkflowRequest:
    run_id: str
    engagement: DiligenceEngagement
    manifest_path: Path
    review_policy: ReviewPolicy = ReviewPolicy.WHEN_NEEDED

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be blank")
        if self.engagement.engagement_id != self.run_id:
            raise ValueError("run and engagement IDs must match")


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    subject_type: str
    subject_id: str
    action: ReviewActionType
    rationale: str
    severity: Severity | None = None
    preferred_source_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.subject_type.strip()
            or not self.subject_id.strip()
            or not self.rationale.strip()
        ):
            raise ValueError("review decision fields must not be blank")
        if self.action is ReviewActionType.CHANGE_SEVERITY and self.severity is None:
            raise ValueError("change-severity decisions require severity")
        if self.action is ReviewActionType.RESOLVE_CONFLICT and self.preferred_source_id is None:
            raise ValueError("conflict resolution requires preferred_source_id")


@dataclass(frozen=True, slots=True)
class HumanReviewSubmission:
    reviewer: str
    rationale: str
    decisions: tuple[ReviewDecision, ...]
    recorded_at: datetime = datetime.min.replace(tzinfo=UTC)

    def __post_init__(self) -> None:
        if not self.reviewer.strip() or not self.rationale.strip() or not self.decisions:
            raise ValueError("human review requires reviewer, rationale, and decisions")
        if self.recorded_at.tzinfo is None:
            raise ValueError("review timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    reasons: tuple[str, ...]
    finding_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    missing_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkflowIssue:
    code: FailureCode
    node: str
    message: str
    recoverable: bool
    attempt: int


@dataclass(frozen=True, slots=True)
class TraceEvent:
    node: str
    status: WorkflowStatus
    message: str
    occurred_at: datetime
    duration_ms: int
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class FinancialDiligenceSnapshot:
    revenue_reconciliation: ReconciliationResult
    ebitda_bridge: EbitdaBridge
    concentration: CustomerConcentrationResult
    working_capital: WorkingCapitalTrend
    nwc_peg: NwcPegResult
    net_debt: NetDebtBridge
    findings: tuple[FinancialFindingOutput, ...]


@dataclass(frozen=True, slots=True)
class PrioritizedFinding:
    finding: AttributedFinding
    priority: PriorityBand
    rationale: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class ReportCitation:
    evidence_id: str
    document_id: str | None
    locator: str
    source_excerpt: str | None


@dataclass(frozen=True, slots=True)
class ReportFinding:
    finding_id: str
    title: str
    severity: Severity
    support_status: str
    narrative: str
    uncertainty: str | None
    citations: tuple[ReportCitation, ...]


@dataclass(frozen=True, slots=True)
class ReportSection:
    section_id: str
    title: str
    narrative: str
    findings: tuple[ReportFinding, ...] = ()
    request_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FinancialReportSummary:
    reported_ebitda: Decimal | None
    accepted_adjustments: Decimal | None
    diligence_adjusted_ebitda: Decimal | None
    customer_concentration_percent: Decimal | None
    normalized_nwc: Decimal | None
    adjusted_net_debt: Decimal | None
    currency: str
    unit: str


@dataclass(frozen=True, slots=True)
class DiligenceReport:
    report_id: str
    run_id: str
    target_name: str
    generated_at: datetime
    status: ReportStatus
    executive_finding_ids: tuple[str, ...]
    sections: tuple[ReportSection, ...]
    financial_summary: FinancialReportSummary
    limitations: tuple[str, ...]
    review_action_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunEvaluationMetadata:
    document_count: int
    chunk_count: int
    finding_count: int
    high_or_critical_count: int
    conflict_count: int
    missing_information_count: int
    citation_coverage_percent: Decimal
    report_consistent: bool
    completed_specialists: int
    failed_specialists: int


@dataclass(frozen=True, slots=True)
class DiligenceWorkflowResult:
    run_id: str
    status: WorkflowStatus
    failure_code: FailureCode | None
    engagement: DiligenceEngagement
    documents: tuple[VdrDocument, ...]
    specialist_results: tuple[SpecialistResult, ...]
    final_findings: tuple[PrioritizedFinding, ...]
    conflicts: tuple[FactConflict, ...]
    relationships: tuple[FindingRelationship, ...]
    missing_information: tuple[MissingInformation, ...]
    information_requests: tuple[ConsolidatedRequest, ...]
    review_actions: tuple[HumanReviewAction, ...]
    report: DiligenceReport | None
    evaluation: RunEvaluationMetadata | None
    warnings: tuple[str, ...]
    errors: tuple[WorkflowIssue, ...]
    trace: tuple[TraceEvent, ...]


class WorkflowState(TypedDict, total=False):
    request: WorkflowRequest
    corpus: VdrCorpus
    documents: tuple[VdrDocument, ...]
    index: InMemoryDiligenceIndex
    retrieved_evidence: tuple[DiligenceEvidenceResult, ...]
    financial: FinancialDiligenceSnapshot
    specialist_result: CoordinatorResult
    final_findings: tuple[PrioritizedFinding, ...]
    conflicts: tuple[FactConflict, ...]
    review_request: ReviewRequest
    review_submission: HumanReviewSubmission
    review_actions: tuple[HumanReviewAction, ...]
    report: DiligenceReport
    evaluation: RunEvaluationMetadata
    final_result: DiligenceWorkflowResult
    status: WorkflowStatus
    failure_code: FailureCode | None
    warnings: tuple[str, ...]
    errors: tuple[WorkflowIssue, ...]
    retry_counts: dict[str, int]
    retry_stage: str | None
    trace: tuple[TraceEvent, ...]


def citation_from_evidence(evidence: EvidenceReference) -> ReportCitation:
    locators: list[str] = []
    if evidence.page_numbers:
        locators.append("pages " + ",".join(str(value) for value in evidence.page_numbers))
    if evidence.section:
        locators.append(f"section {evidence.section}")
    if evidence.table:
        locators.append(f"table {evidence.table}")
    if evidence.sheet_name:
        locators.append(f"sheet {evidence.sheet_name}")
    if evidence.cell_range:
        locators.append(f"cells {evidence.cell_range}")
    if evidence.chunk_id:
        locators.append(f"chunk {evidence.chunk_id}")
    return ReportCitation(
        evidence.evidence_id,
        evidence.document_id,
        "; ".join(locators) or "document",
        evidence.source_text,
    )
