"""Public schemas for the authenticated pilot API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from ma_due_diligence.domain import ReviewActionType, Severity
from ma_due_diligence.persistence.models import DealStatus
from ma_due_diligence.security.models import DealRole


class PilotLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class PilotPrincipalResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    is_pilot_admin: bool


class PilotLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: PilotPrincipalResponse


class PilotDealResponse(BaseModel):
    deal_id: str
    name: str
    target_name: str
    buyer_name: str | None
    transaction_type: str
    reporting_currency: str
    as_of_date: date
    materiality_threshold: str | None
    unit: str
    workstreams: tuple[str, ...]
    notes: str | None
    status: DealStatus


class CreatePilotDealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    target_name: str = Field(min_length=1, max_length=160)
    buyer_name: str | None = Field(default=None, max_length=160)
    transaction_type: str = Field(min_length=1, max_length=80)
    reporting_currency: str = Field(min_length=3, max_length=3)
    as_of_date: date
    materiality_threshold: str | None = Field(default=None, max_length=80)
    unit: str = Field(default="units", min_length=1, max_length=40)
    workstreams: tuple[str, ...] = ()
    notes: str | None = Field(default=None, max_length=2_000)


class AssignDealRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=160)
    role: DealRole


class DealMembershipResponse(BaseModel):
    deal_id: str
    user_id: str
    role: DealRole
    assigned_by: str
    assigned_at: datetime


class PilotReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: str = Field(min_length=1, max_length=40)
    subject_id: str = Field(min_length=1, max_length=180)
    action: ReviewActionType
    rationale: str = Field(min_length=1, max_length=2_000)
    severity: Severity | None = None
    preferred_source_id: str | None = Field(default=None, max_length=180)


class PilotReviewSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(min_length=1, max_length=2_000)
    decisions: list[PilotReviewDecisionRequest] = Field(min_length=1, max_length=200)
