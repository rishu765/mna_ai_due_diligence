"""Small category-specific M4/5 evaluation for the synthetic investigation."""

from __future__ import annotations

from dataclasses import dataclass

from ma_due_diligence.specialists.models import (
    AgentId,
    ComparisonOutcome,
    CoordinatorResult,
)


@dataclass(frozen=True, slots=True)
class SpecialistEvaluationCheck:
    category: str
    passed: bool
    expected: str
    actual: str


@dataclass(frozen=True, slots=True)
class SpecialistEvaluationReport:
    checks: tuple[SpecialistEvaluationCheck, ...]

    @property
    def passed(self) -> int:
        return sum(item.passed for item in self.checks)


def evaluate_specialist_result(result: CoordinatorResult) -> SpecialistEvaluationReport:
    categories = {item.finding.category for item in result.findings}
    conflicts = result.investigation.conflicts
    comparisons = result.investigation.comparisons
    traces_by_finding = {item.finding_id: item for item in result.traces}
    compound = next(
        (
            item
            for item in result.findings
            if item.finding.category == "compound_customer_retention"
        ),
        None,
    )
    concentration_findings = tuple(
        item for item in result.findings if item.finding.category == "customer_concentration"
    )
    agent_ids = {item.agent_id for item in result.specialist_results}
    nonfinancial = tuple(
        item
        for item in result.findings
        if AgentId.FINANCIAL not in item.contributing_agents
        and AgentId.CROSS_DOCUMENT not in item.contributing_agents
    )
    grounded = all(item.claim_ids and item.finding.evidence for item in nonfinancial)
    checks = (
        SpecialistEvaluationCheck(
            "specialist_finding_detection",
            {"customer_concentration", "supplier_concentration", "change_of_control"} <= categories,
            "commercial, legal, and operational findings",
            ", ".join(sorted(categories)),
        ),
        SpecialistEvaluationCheck(
            "evidence_grounding",
            all(trace.evidence_ids for trace in result.traces),
            "every finding trace has evidence",
            str(sum(bool(trace.evidence_ids) for trace in result.traces)),
        ),
        SpecialistEvaluationCheck(
            "contradiction_detection",
            bool(conflicts),
            ">=1 open conflict",
            str(len(conflicts)),
        ),
        SpecialistEvaluationCheck(
            "false_contradiction_avoidance",
            any(item.outcome is ComparisonOutcome.NOT_COMPARABLE for item in comparisons),
            "period or type mismatch retained as not comparable",
            str(sum(item.outcome is ComparisonOutcome.NOT_COMPARABLE for item in comparisons)),
        ),
        SpecialistEvaluationCheck(
            "version_awareness",
            bool(result.investigation.superseded_claim_ids),
            "older contract claims superseded",
            str(len(result.investigation.superseded_claim_ids)),
        ),
        SpecialistEvaluationCheck(
            "finding_deduplication",
            len(concentration_findings) == 1
            and {AgentId.FINANCIAL, AgentId.COMMERCIAL}
            <= set(concentration_findings[0].contributing_agents),
            "overlapping source findings represented once",
            f"{len(concentration_findings)} consolidated concentration finding(s)",
        ),
        SpecialistEvaluationCheck(
            "compound_risk_creation",
            compound is not None and len(compound.source_finding_ids) == 3,
            "one three-signal compound risk",
            "missing" if compound is None else str(len(compound.source_finding_ids)),
        ),
        SpecialistEvaluationCheck(
            "missing_information_detection",
            len(result.missing_information) >= 3,
            ">=3 structured gaps",
            str(len(result.missing_information)),
        ),
        SpecialistEvaluationCheck(
            "question_request_quality",
            bool(result.requests)
            and all(
                item.question and item.rationale and item.workstreams for item in result.requests
            ),
            "non-empty, attributed requests",
            str(len(result.requests)),
        ),
        SpecialistEvaluationCheck(
            "no_hallucination_behavior",
            grounded
            and {
                AgentId.FINANCIAL,
                AgentId.COMMERCIAL,
                AgentId.LEGAL_CONTRACTUAL,
                AgentId.OPERATIONAL,
            }
            <= agent_ids
            and all(item.finding.finding_id in traces_by_finding for item in result.findings),
            "nonfinancial conclusions cite claims and all findings have traces",
            str(grounded),
        ),
    )
    return SpecialistEvaluationReport(checks)
