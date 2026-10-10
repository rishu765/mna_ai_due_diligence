"""Period-, version-, and source-aware cross-document claim comparison."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from itertools import combinations

from ma_due_diligence.domain import ConflictStatus, EvidenceReference, FactConflict
from ma_due_diligence.specialists.models import (
    ClaimComparison,
    ClaimStatus,
    ComparisonOutcome,
    InvestigationClaim,
    InvestigationResult,
    SourceAuthority,
)

_AUTHORITY = {
    SourceAuthority.SIGNED_CONTRACT: 0,
    SourceAuthority.AUDITED: 1,
    SourceAuthority.DIRECT_SCHEDULE: 2,
    SourceAuthority.BOARD_REPORT: 3,
    SourceAuthority.MANAGEMENT_ACCOUNTS: 4,
    SourceAuthority.MANAGEMENT_NARRATIVE: 5,
    SourceAuthority.OTHER: 6,
}


class CrossDocumentInvestigator:
    def compare(
        self, claims: tuple[InvestigationClaim, ...], engagement_id: str
    ) -> InvestigationResult:
        comparisons: list[ClaimComparison] = []
        conflicts: list[FactConflict] = []
        superseded: set[str] = set()

        by_logical: dict[tuple[str, str], list[InvestigationClaim]] = defaultdict(list)
        for claim in claims:
            if claim.logical_document_key is not None:
                by_logical[(claim.logical_document_key, claim.topic)].append(claim)
        for group in by_logical.values():
            document_ids = {claim.evidence.document_id for claim in group}
            if len(document_ids) < 2:
                continue
            current = max(group, key=_revision_rank)
            for old in group:
                if old.evidence.document_id == current.evidence.document_id:
                    continue
                superseded.add(old.claim_id)
                comparisons.append(
                    ClaimComparison(
                        f"comparison-{len(comparisons) + 1}",
                        old.claim_id,
                        current.claim_id,
                        ComparisonOutcome.SUPERSEDED,
                        "A newer revision of the same logical document supersedes this claim.",
                        current.claim_id,
                    )
                )

        active = tuple(claim for claim in claims if claim.claim_id not in superseded)
        groups: dict[tuple[str, str, str | None], list[InvestigationClaim]] = defaultdict(list)
        for claim in active:
            groups[(claim.subject.casefold(), claim.topic, claim.entity_id)].append(claim)
        for group in groups.values():
            for left, right in combinations(group, 2):
                comparison = self._compare_pair(left, right, engagement_id, len(comparisons) + 1)
                comparisons.append(comparison)
                if comparison.conflict is not None:
                    conflicts.append(comparison.conflict)
        return InvestigationResult(
            tuple(comparisons),
            tuple(conflicts),
            tuple(sorted(superseded)),
        )

    def _compare_pair(
        self,
        left: InvestigationClaim,
        right: InvestigationClaim,
        engagement_id: str,
        sequence: int,
    ) -> ClaimComparison:
        comparison_id = f"comparison-{sequence}"
        if (
            left.period is not None
            and right.period is not None
            and left.period.label.casefold() != right.period.label.casefold()
        ):
            return ClaimComparison(
                comparison_id,
                left.claim_id,
                right.claim_id,
                ComparisonOutcome.NOT_COMPARABLE,
                "Claims refer to different periods and were not treated as contradictory.",
            )
        if left.value_kind is not right.value_kind or left.unit != right.unit:
            return ClaimComparison(
                comparison_id,
                left.claim_id,
                right.claim_id,
                ComparisonOutcome.NOT_COMPARABLE,
                "Claims use incompatible value types or units.",
            )
        if _value(left) == _value(right):
            return ClaimComparison(
                comparison_id,
                left.claim_id,
                right.claim_id,
                ComparisonOutcome.ALIGNED,
                "Comparable claims agree.",
                _preferred(left, right).claim_id,
            )
        preferred = _preferred(left, right)
        evidence = _unique_evidence((left.evidence, right.evidence))
        conflict = FactConflict(
            conflict_id=f"conflict-{sequence}",
            engagement_id=engagement_id,
            topic=left.topic,
            observation_fact_ids=(left.claim_id, right.claim_id),
            status=ConflictStatus.OPEN,
            evidence=evidence,
            review_required=True,
        )
        return ClaimComparison(
            comparison_id,
            left.claim_id,
            right.claim_id,
            ComparisonOutcome.CONFLICT,
            "Comparable current claims disagree; source authority identifies a review candidate only.",
            preferred.claim_id,
            conflict,
        )


def mark_claim_statuses(
    claims: tuple[InvestigationClaim, ...], result: InvestigationResult
) -> tuple[InvestigationClaim, ...]:
    conflicting = {claim_id for item in result.conflicts for claim_id in item.observation_fact_ids}
    superseded = set(result.superseded_claim_ids)
    return tuple(
        replace(
            claim,
            status=(
                ClaimStatus.SUPERSEDED
                if claim.claim_id in superseded
                else ClaimStatus.CONFLICTING
                if claim.claim_id in conflicting
                else claim.status
            ),
        )
        for claim in claims
    )


def _revision_rank(claim: InvestigationClaim) -> tuple[int, int, str]:
    effective = claim.effective_date.toordinal() if claim.effective_date else 0
    version_number = 0
    if claim.version:
        digits = "".join(character for character in claim.version if character.isdigit())
        version_number = (
            int(digits) if digits else (1 if "revised" in claim.version.casefold() else 0)
        )
    return effective, version_number, claim.claim_id


def _preferred(left: InvestigationClaim, right: InvestigationClaim) -> InvestigationClaim:
    left_rank = (_AUTHORITY[left.authority], -_revision_rank(left)[0], left.claim_id)
    right_rank = (_AUTHORITY[right.authority], -_revision_rank(right)[0], right.claim_id)
    return min((left_rank, left), (right_rank, right), key=lambda item: item[0])[1]


def _value(claim: InvestigationClaim) -> object:
    return next(
        value
        for value in (
            claim.text_value,
            claim.numeric_value,
            claim.boolean_value,
            claim.date_value,
        )
        if value is not None
    )


def _unique_evidence(values: tuple[EvidenceReference, ...]) -> tuple[EvidenceReference, ...]:
    by_id = {item.evidence_id: item for item in values}
    return tuple(by_id[key] for key in sorted(by_id))
