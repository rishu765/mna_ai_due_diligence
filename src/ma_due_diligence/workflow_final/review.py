"""Deterministic review gates and immutable analyst decision application."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from ma_due_diligence.domain import (
    ConflictStatus,
    FactConflict,
    FindingStatus,
    HumanReviewAction,
    MaterialityAssessment,
    Priority,
    QualitativeMateriality,
    ReviewActionType,
    ReviewStatus,
    Severity,
    StateField,
    SupportStatus,
)
from ma_due_diligence.specialists.models import AttributedFinding, CoordinatorResult
from ma_due_diligence.workflow_final.models import (
    HumanReviewSubmission,
    ReviewPolicy,
    ReviewRequest,
)


def build_review_request(
    coordinator: CoordinatorResult, policy: ReviewPolicy
) -> ReviewRequest | None:
    reasons: list[str] = []
    finding_ids: list[str] = []
    conflict_ids: list[str] = []
    missing_ids: list[str] = []
    for item in coordinator.findings:
        finding = item.finding
        uncertain_material = finding.severity in {Severity.HIGH, Severity.CRITICAL} and (
            finding.support_status in {SupportStatus.CONFLICTING, SupportStatus.UNVERIFIED}
            or finding.materiality.qualitative
            in {QualitativeMateriality.HIGH, QualitativeMateriality.UNASSESSED}
        )
        compound = finding.category == "compound_customer_retention"
        if uncertain_material or compound:
            finding_ids.append(finding.finding_id)
            reasons.append(f"Analyst decision required for {finding.title}.")
    for conflict in coordinator.investigation.conflicts:
        if conflict.status in {ConflictStatus.OPEN, ConflictStatus.UNDER_REVIEW}:
            conflict_ids.append(conflict.conflict_id)
            reasons.append(f"Unresolved source conflict: {conflict.topic}.")
    for missing in coordinator.missing_information:
        if missing.blocking or missing.importance is Priority.URGENT:
            missing_ids.append(missing.missing_item_id)
            reasons.append(f"Critical information is missing: {missing.requested_item}.")
    needed = policy is ReviewPolicy.ALWAYS or (policy is ReviewPolicy.WHEN_NEEDED and bool(reasons))
    if not needed:
        return None
    return ReviewRequest(
        tuple(dict.fromkeys(reasons or ["Configured policy requires analyst review."])),
        tuple(dict.fromkeys(finding_ids)),
        tuple(dict.fromkeys(conflict_ids)),
        tuple(dict.fromkeys(missing_ids)),
    )


def apply_review(
    findings: tuple[AttributedFinding, ...],
    conflicts: tuple[FactConflict, ...],
    submission: HumanReviewSubmission,
    engagement_id: str,
) -> tuple[
    tuple[AttributedFinding, ...],
    tuple[FactConflict, ...],
    tuple[HumanReviewAction, ...],
    bool,
]:
    finding_map = {item.finding.finding_id: item for item in findings}
    conflict_map = {item.conflict_id: item for item in conflicts}
    actions: list[HumanReviewAction] = []
    waiting_for_information = False
    for ordinal, decision in enumerate(submission.decisions, start=1):
        action_id = f"review-{engagement_id}-{ordinal}"
        prior: tuple[StateField, ...]
        resulting: tuple[StateField, ...]
        if decision.subject_type == "finding":
            item = finding_map.get(decision.subject_id)
            if item is None:
                raise ValueError(f"unknown finding: {decision.subject_id}")
            finding = item.finding
            prior = (
                StateField("status", finding.status.value),
                StateField("severity", finding.severity.value),
                StateField("materiality", finding.materiality.qualitative.value),
            )
            if decision.action is ReviewActionType.APPROVE_FINDING:
                finding = replace(
                    finding,
                    status=FindingStatus.CONFIRMED,
                    analyst_review_status=ReviewStatus.REVIEWED,
                )
            elif decision.action is ReviewActionType.REJECT_FINDING:
                finding = replace(
                    finding,
                    status=FindingStatus.CLOSED,
                    analyst_review_status=ReviewStatus.REVIEWED,
                )
            elif decision.action is ReviewActionType.CHANGE_SEVERITY:
                assert decision.severity is not None
                finding = replace(
                    finding,
                    severity=decision.severity,
                    analyst_review_status=ReviewStatus.REVIEWED,
                )
            elif decision.action is ReviewActionType.MARK_NONMATERIAL:
                finding = replace(
                    finding,
                    materiality=MaterialityAssessment(
                        QualitativeMateriality.IMMATERIAL,
                        rationale=decision.rationale,
                    ),
                    analyst_review_status=ReviewStatus.REVIEWED,
                )
            elif decision.action is ReviewActionType.REQUEST_MORE_EVIDENCE:
                finding = replace(finding, status=FindingStatus.UNDER_REVIEW)
                waiting_for_information = True
            else:
                raise ValueError(f"action {decision.action.value} is invalid for a finding")
            finding_map[decision.subject_id] = replace(item, finding=finding)
            resulting = (
                StateField("status", finding.status.value),
                StateField("severity", finding.severity.value),
                StateField("materiality", finding.materiality.qualitative.value),
            )
        elif decision.subject_type == "conflict":
            conflict = conflict_map.get(decision.subject_id)
            if conflict is None:
                raise ValueError(f"unknown conflict: {decision.subject_id}")
            if decision.action is not ReviewActionType.RESOLVE_CONFLICT:
                raise ValueError("conflicts may only be resolved")
            assert decision.preferred_source_id is not None
            prior = (StateField("status", conflict.status.value),)
            conflict = replace(
                conflict,
                status=ConflictStatus.RESOLVED,
                preferred_fact_id=decision.preferred_source_id,
                resolution_rationale=decision.rationale,
                resolved_by_review_action_id=action_id,
                review_required=False,
            )
            conflict_map[decision.subject_id] = conflict
            resulting = (
                StateField("status", conflict.status.value),
                StateField("preferred_fact_id", conflict.preferred_fact_id),
            )
        else:
            raise ValueError(f"unsupported review subject type: {decision.subject_type}")
        actions.append(
            HumanReviewAction(
                action_id,
                engagement_id,
                decision.subject_type,
                decision.subject_id,
                decision.action,
                submission.reviewer,
                decision.rationale,
                submission.recorded_at if submission.recorded_at.year > 1 else datetime.now(UTC),
                prior,
                resulting,
            )
        )
    return (
        tuple(finding_map.values()),
        tuple(conflict_map.values()),
        tuple(actions),
        waiting_for_information,
    )
