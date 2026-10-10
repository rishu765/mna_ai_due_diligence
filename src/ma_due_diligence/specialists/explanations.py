"""Optional grounded explanation boundary with evidence-citation validation."""

from __future__ import annotations

from typing import Protocol

from ma_due_diligence.errors import DomainValidationError
from ma_due_diligence.specialists.models import AttributedFinding, GroundedExplanation


class ExplanationProvider(Protocol):
    def explain(self, finding: AttributedFinding) -> GroundedExplanation: ...


class GroundedExplanationService:
    def __init__(self, provider: ExplanationProvider | None = None) -> None:
        self._provider = provider

    def explain(self, finding: AttributedFinding) -> GroundedExplanation:
        available = tuple(item.evidence_id for item in finding.finding.evidence)
        if self._provider is None:
            caveats = (finding.uncertainty,) if finding.uncertainty else ()
            return GroundedExplanation(
                finding.finding.finding_id,
                finding.finding.description,
                caveats,
                finding.finding.potential_deal_impact
                or "Deal implication requires analyst review.",
                finding.finding.recommended_follow_up,
                available,
            )
        result = self._provider.explain(finding)
        if result.finding_id != finding.finding.finding_id:
            raise DomainValidationError("explanation provider changed the finding ID")
        unsupported = set(result.cited_evidence_ids) - set(available)
        if unsupported:
            raise DomainValidationError("explanation cited evidence outside the finding context")
        return result
