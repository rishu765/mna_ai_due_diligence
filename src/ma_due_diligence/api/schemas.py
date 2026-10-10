"""Typed public API schemas; domain objects stay inside the service boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ma_due_diligence.domain import ReviewActionType, Severity
from ma_due_diligence.workflow_final.models import (
    FailureCode,
    ReportStatus,
    ReviewPolicy,
    WorkflowStatus,
)


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=120)
    review_policy: ReviewPolicy = ReviewPolicy.WHEN_NEEDED
    fixture_mode: Literal[True] = True


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    action: ReviewActionType
    rationale: str
    severity: Severity | None = None
    preferred_source_id: str | None = None


class SubmitReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str
    rationale: str
    decisions: list[ReviewDecisionRequest]


class RunStatusResponse(BaseModel):
    run_id: str
    status: WorkflowStatus
    failure_code: FailureCode | None
    document_count: int
    finding_count: int
    review_required: bool
    review_reasons: list[str]
    warnings: list[str]
    errors: list[str]


class StartRunResponse(RunStatusResponse):
    created: bool = True


class ReviewResponse(RunStatusResponse):
    review_action_count: int


class ReportCitationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_id: str
    document_id: str | None
    locator: str
    source_excerpt: str | None


class ReportFindingSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding_id: str
    title: str
    severity: Severity
    support_status: str
    narrative: str
    uncertainty: str | None
    citations: tuple[ReportCitationSchema, ...]


class ReportSectionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    section_id: str
    title: str
    narrative: str
    findings: tuple[ReportFindingSchema, ...]
    request_ids: tuple[str, ...]


class FinancialSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reported_ebitda: Decimal | None
    accepted_adjustments: Decimal | None
    diligence_adjusted_ebitda: Decimal | None
    customer_concentration_percent: Decimal | None
    normalized_nwc: Decimal | None
    adjusted_net_debt: Decimal | None
    currency: str
    unit: str


class DiligenceReportSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: str
    run_id: str
    target_name: str
    generated_at: datetime
    status: ReportStatus
    executive_finding_ids: tuple[str, ...]
    sections: tuple[ReportSectionSchema, ...]
    financial_summary: FinancialSummarySchema
    limitations: tuple[str, ...]
    review_action_ids: tuple[str, ...]


class ReportResponse(BaseModel):
    run_id: str
    status: WorkflowStatus
    report: DiligenceReportSchema
