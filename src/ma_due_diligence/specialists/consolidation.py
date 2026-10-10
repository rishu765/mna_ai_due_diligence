"""Finding deduplication, relationships, compound risks, requests, and lineage."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ma_due_diligence.domain import (
    DealImpactArea,
    DiligenceFinding,
    DiligenceWorkstream,
    EvidenceReference,
    FindingType,
    FollowUpQuestion,
    LikelihoodBand,
    MaterialityAssessment,
    MissingInformation,
    Priority,
    QualitativeMateriality,
    RiskAssessment,
    Severity,
    SupportStatus,
)
from ma_due_diligence.specialists.models import (
    AgentId,
    AttributedFinding,
    ConsolidatedRequest,
    FindingRelationship,
    FindingRelationshipType,
    InvestigationClaim,
    InvestigationResult,
    InvestigationTrace,
)

_SEVERITY = {
    Severity.UNASSESSED: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}
_PRIORITY = {Priority.LOW: 0, Priority.MEDIUM: 1, Priority.HIGH: 2, Priority.URGENT: 3}


@dataclass(slots=True)
class _RequestGroup:
    question: str
    workstreams: list[DiligenceWorkstream]
    priority: Priority
    rationales: list[str]
    findings: list[str]
    requested: str | None


class FindingConsolidator:
    def consolidate(self, findings: tuple[AttributedFinding, ...]) -> tuple[AttributedFinding, ...]:
        groups: dict[str, list[AttributedFinding]] = {}
        for item in findings:
            groups.setdefault(_finding_key(item.finding), []).append(item)
        return tuple(self._merge(key, tuple(group)) for key, group in sorted(groups.items()))

    @staticmethod
    def _merge(key: str, group: tuple[AttributedFinding, ...]) -> AttributedFinding:
        primary = max(group, key=lambda item: _SEVERITY[item.finding.severity])
        evidence = _unique_evidence(
            tuple(evidence for item in group for evidence in item.finding.evidence)
        )
        support = primary.finding.support_status
        if evidence and support in {SupportStatus.DERIVED, SupportStatus.UNVERIFIED}:
            support = SupportStatus.SOURCE_BACKED
        descriptions = tuple(dict.fromkeys(item.finding.description for item in group))
        merged = replace(
            primary.finding,
            finding_id=f"consolidated-{key}",
            category=key,
            description=" ".join(descriptions),
            support_status=support,
            evidence=evidence,
            supporting_fact_ids=_unique_text(
                tuple(value for item in group for value in item.finding.supporting_fact_ids)
            ),
            conflicting_fact_ids=_unique_text(
                tuple(value for item in group for value in item.finding.conflicting_fact_ids)
            ),
            impact_areas=tuple(
                dict.fromkeys(value for item in group for value in item.finding.impact_areas)
            ),
        )
        return AttributedFinding(
            merged,
            tuple(dict.fromkeys(agent for item in group for agent in item.contributing_agents)),
            _unique_text(tuple(value for item in group for value in item.source_finding_ids)),
            "Merged overlapping specialist findings; severity remains reviewable.",
            _unique_text(tuple(value for item in group for value in item.claim_ids)),
            _unique_text(tuple(value for item in group for value in item.conflict_ids)),
        )


def conflict_findings(
    engagement_id: str,
    claims: tuple[InvestigationClaim, ...],
    investigation: InvestigationResult,
) -> tuple[AttributedFinding, ...]:
    by_id = {item.claim_id: item for item in claims}
    output: list[AttributedFinding] = []
    for conflict in investigation.conflicts:
        related = tuple(by_id[value] for value in conflict.observation_fact_ids if value in by_id)
        if not related:
            continue
        topic = conflict.topic.replace("_", " ")
        evidence = _unique_evidence(tuple(item.evidence for item in related))
        finding = DiligenceFinding(
            finding_id=f"investigation-{conflict.conflict_id}",
            engagement_id=engagement_id,
            workstream=related[0].workstream,
            category=f"conflict_{conflict.topic}",
            title=f"Conflicting claims about {topic}",
            description="Current source evidence contains inconsistent claims; neither value was overwritten.",
            finding_type=FindingType.INCONSISTENCY,
            severity=Severity.HIGH if "concentration" in conflict.topic else Severity.MEDIUM,
            materiality=MaterialityAssessment(
                rationale="Materiality requires review of the conflicting source claims."
            ),
            support_status=SupportStatus.CONFLICTING,
            conflicting_fact_ids=conflict.observation_fact_ids,
            evidence=evidence,
            affected_topic=conflict.topic,
            impact_areas=(DealImpactArea.DEAL_THESIS,),
            recommended_follow_up=f"Reconcile the source claims concerning {topic}.",
        )
        output.append(
            AttributedFinding(
                finding,
                (AgentId.CROSS_DOCUMENT,),
                (finding.finding_id,),
                "The source hierarchy identifies a preferred review candidate but does not resolve the conflict.",
                conflict.observation_fact_ids,
                (conflict.conflict_id,),
            )
        )
    return tuple(output)


def create_compound_customer_risk(
    engagement_id: str, findings: tuple[AttributedFinding, ...]
) -> AttributedFinding | None:
    concentration = _find(findings, "customer_concentration")
    expiry = _find(findings, "customer_renewal")
    consent = _find(findings, "change_of_control")
    if concentration is None or expiry is None or consent is None:
        return None
    sources = (concentration, expiry, consent)
    evidence = _unique_evidence(tuple(value for item in sources for value in item.finding.evidence))
    percentage = concentration.finding.materiality.percentage
    finding = DiligenceFinding(
        finding_id="compound-material-customer-retention",
        engagement_id=engagement_id,
        workstream=DiligenceWorkstream.COMMERCIAL,
        category="compound_customer_retention",
        title="Compound material customer-retention risk",
        description="High revenue concentration, near-term contract expiry, and a change-of-control consent or termination right combine into an elevated retention and closing risk.",
        finding_type=FindingType.RISK,
        severity=Severity.HIGH,
        materiality=MaterialityAssessment(
            qualitative=QualitativeMateriality.HIGH,
            percentage=percentage,
            benchmark="Revenue" if percentage is not None else None,
            rationale="Combines the quantified concentration with contractual renewal and control-change signals.",
        ),
        support_status=SupportStatus.SOURCE_BACKED,
        evidence=evidence,
        impact_areas=(
            DealImpactArea.DEAL_THESIS,
            DealImpactArea.QUALITY_OF_EARNINGS,
            DealImpactArea.CLOSING_CONDITION,
            DealImpactArea.REPS_AND_WARRANTIES,
        ),
        potential_deal_impact="May affect deal thesis, closing planning, protections, and customer-retention assumptions.",
        recommended_follow_up="Confirm renewal intent and obtain any required change-of-control consent before closing.",
        risk=RiskAssessment(
            "compound_customer_retention",
            LikelihoodBand.UNKNOWN,
            (DealImpactArea.DEAL_THESIS, DealImpactArea.CLOSING_CONDITION),
            "Multiple independent signals amplify customer-retention exposure.",
        ),
    )
    return AttributedFinding(
        finding,
        tuple(dict.fromkeys(agent for item in sources for agent in item.contributing_agents)),
        tuple(item.finding.finding_id for item in sources),
        "The signals are established; the customer's future behavior remains unknown.",
        _unique_text(tuple(value for item in sources for value in item.claim_ids)),
        _unique_text(tuple(value for item in sources for value in item.conflict_ids)),
    )


def build_relationships(
    findings: tuple[AttributedFinding, ...], compound: AttributedFinding | None
) -> tuple[FindingRelationship, ...]:
    if compound is None:
        return ()
    relationships: list[FindingRelationship] = []
    for source_id in compound.source_finding_ids:
        relationships.append(
            FindingRelationship(
                f"rel-{len(relationships) + 1}",
                source_id,
                compound.finding.finding_id,
                FindingRelationshipType.AMPLIFIES,
                "This underlying signal amplifies the compound customer-retention risk.",
            )
        )
    return tuple(relationships)


def consolidate_requests(
    missing: tuple[MissingInformation, ...],
    questions: tuple[FollowUpQuestion, ...],
) -> tuple[ConsolidatedRequest, ...]:
    groups: dict[str, _RequestGroup] = {}
    for item in missing:
        key = _matching_request_key(groups, item.requested_item)
        group = groups.setdefault(
            key,
            _RequestGroup(
                item.follow_up_question or f"Please provide {item.requested_item}.",
                [],
                item.importance,
                [],
                [],
                item.requested_item,
            ),
        )
        group.workstreams.append(item.workstream)
        group.rationales.append(item.reason_needed)
        if item.related_finding_id:
            group.findings.append(item.related_finding_id)
        if _PRIORITY[item.importance] > _PRIORITY[group.priority]:
            group.priority = item.importance
    for question in questions:
        key = _matching_request_key(groups, question.question)
        group = groups.setdefault(
            key,
            _RequestGroup(
                question.question,
                [],
                question.priority,
                [],
                [],
                question.requested_document_or_data,
            ),
        )
        group.workstreams.append(question.workstream)
        group.rationales.append(question.rationale)
        if question.related_finding_id:
            group.findings.append(question.related_finding_id)
        if _PRIORITY[question.priority] > _PRIORITY[group.priority]:
            group.priority = question.priority
    return tuple(
        ConsolidatedRequest(
            f"request-{index}",
            group.question,
            tuple(dict.fromkeys(group.workstreams)),
            group.priority,
            " ".join(dict.fromkeys(group.rationales)),
            tuple(dict.fromkeys(group.findings)),
            group.requested,
        )
        for index, (_, group) in enumerate(sorted(groups.items()), start=1)
    )


def build_traces(findings: tuple[AttributedFinding, ...]) -> tuple[InvestigationTrace, ...]:
    traces = []
    for index, item in enumerate(findings, start=1):
        evidence_ids = tuple(evidence.evidence_id for evidence in item.finding.evidence)
        document_ids = tuple(
            dict.fromkeys(
                evidence.document_id
                for evidence in item.finding.evidence
                if evidence.document_id is not None
            )
        )
        traces.append(
            InvestigationTrace(
                f"trace-{index}",
                item.finding.finding_id,
                item.contributing_agents,
                _unique_text(
                    (*item.finding.supporting_fact_ids, *item.finding.conflicting_fact_ids)
                ),
                item.claim_ids,
                item.conflict_ids,
                evidence_ids,
                document_ids,
            )
        )
    return tuple(traces)


def _finding_key(finding: DiligenceFinding) -> str:
    text = f"{finding.category} {finding.title}".casefold()
    if "customer concentration" in text or finding.finding_id == "fin-customer-concentration":
        return "customer_concentration"
    if "change-of-control" in text or "change of control" in text:
        return "change_of_control"
    if "supplier concentration" in text:
        return "supplier_concentration"
    if "renewal" in text or "contract approaching expiry" in text:
        return "customer_renewal"
    return re.sub(r"[^a-z0-9]+", "_", finding.category.casefold()).strip("_")


def _find(findings: tuple[AttributedFinding, ...], key: str) -> AttributedFinding | None:
    return next((item for item in findings if _finding_key(item.finding) == key), None)


def _request_key(value: str) -> str:
    return " ".join(sorted(_request_tokens(value)))


def _request_tokens(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    ignored = {"please", "provide", "confirm", "the", "and", "a", "an"}
    return {token[:5] for token in tokens if token not in ignored}


def _matching_request_key(groups: dict[str, _RequestGroup], value: str) -> str:
    candidate = _request_tokens(value)
    exact = " ".join(sorted(candidate))
    for key in groups:
        existing = set(key.split())
        union = candidate | existing
        if union and len(candidate & existing) / len(union) >= 0.4:
            return key
    return exact


def _unique_evidence(values: tuple[EvidenceReference, ...]) -> tuple[EvidenceReference, ...]:
    by_id = {item.evidence_id: item for item in values}
    return tuple(by_id[key] for key in sorted(by_id))


def _unique_text(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
