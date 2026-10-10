"""Deterministic specialist analyzers over filtered, evidence-bound contexts."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

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
    MissingInformationStatus,
    Priority,
    QualitativeMateriality,
    QuestionStatus,
    RiskAssessment,
    Severity,
    SupportStatus,
)
from ma_due_diligence.specialists.models import (
    AgentId,
    AttributedFinding,
    ClaimStatus,
    InvestigationClaim,
    RetrievalPlan,
    SpecialistContext,
    SpecialistResult,
)
from ma_due_diligence.specialists.plans import (
    COMMERCIAL_PLAN,
    FINANCIAL_PLAN,
    LEGAL_PLAN,
    OPERATIONAL_PLAN,
)


class SpecialistAnalyzer(Protocol):
    @property
    def agent_id(self) -> AgentId: ...

    @property
    def retrieval_plan(self) -> RetrievalPlan: ...

    def analyze(self, context: SpecialistContext) -> SpecialistResult: ...


class FinancialDiligenceAnalyzer:
    """Translate M3 deterministic outputs without recalculating finance."""

    agent_id = AgentId.FINANCIAL
    retrieval_plan = FINANCIAL_PLAN

    def analyze(self, context: SpecialistContext) -> SpecialistResult:
        findings = tuple(
            AttributedFinding(
                _ground_financial_finding(item.finding, context.claims),
                (self.agent_id,),
                (item.finding.finding_id,),
                item.uncertainty,
                claim_ids=(),
            )
            for item in context.financial_findings
        )
        missing: tuple[MissingInformation, ...] = ()
        if not any(
            "working capital" in result.text.casefold() for result in context.evidence_results
        ):
            missing = (
                _missing(
                    context,
                    self.agent_id,
                    "Monthly working-capital history",
                    "A complete history is needed to assess seasonality and an indicative peg.",
                    Priority.HIGH,
                ),
            )
        return SpecialistResult(
            self.agent_id,
            findings,
            missing,
            _questions(context, self.agent_id, findings),
        )


class CommercialDiligenceAnalyzer:
    agent_id = AgentId.COMMERCIAL
    retrieval_plan = COMMERCIAL_PLAN

    def analyze(self, context: SpecialistContext) -> SpecialistResult:
        findings: list[AttributedFinding] = []
        concentration = _highest_claim(context.claims, "customer_concentration_percent")
        if (
            concentration is not None
            and concentration.numeric_value is not None
            and concentration.numeric_value >= 20
        ):
            findings.append(
                _risk_finding(
                    context,
                    self.agent_id,
                    "commercial-customer-concentration",
                    "customer_concentration",
                    "High customer concentration",
                    f"The largest identified customer represents {concentration.numeric_value}% of revenue.",
                    Severity.HIGH,
                    (DealImpactArea.DEAL_THESIS, DealImpactArea.QUALITY_OF_EARNINGS),
                    (concentration,),
                    "Provide retention, renewal, and churn history for the top five customers.",
                    percentage=concentration.numeric_value,
                )
            )
        expiry = _earliest_claim(context.claims, "contract_expiry")
        if expiry is not None and expiry.date_value is not None:
            horizon = context.engagement.as_of_date + timedelta(days=730)
            if expiry.date_value <= horizon:
                findings.append(
                    _risk_finding(
                        context,
                        self.agent_id,
                        "commercial-major-renewal",
                        "customer_renewal",
                        "Major customer contract approaching expiry",
                        f"A material customer contract expires on {expiry.date_value.isoformat()}.",
                        Severity.HIGH,
                        (DealImpactArea.DEAL_THESIS, DealImpactArea.VALUATION),
                        (expiry,),
                        "Provide renewal status, customer communications, and downside planning.",
                    )
                )
        forecast = _highest_claim(context.claims, "forecast_revenue_growth")
        actual = _highest_claim(context.claims, "actual_revenue_growth")
        if (
            forecast is not None
            and actual is not None
            and forecast.numeric_value is not None
            and actual.numeric_value is not None
            and forecast.numeric_value - actual.numeric_value >= Decimal("20")
        ):
            findings.append(
                _risk_finding(
                    context,
                    self.agent_id,
                    "commercial-growth-gap",
                    "growth_sustainability",
                    "Forecast growth materially exceeds recent actual growth",
                    f"Forecast growth is {forecast.numeric_value}% versus recent actual growth of {actual.numeric_value}%.",
                    Severity.MEDIUM,
                    (DealImpactArea.DEAL_THESIS, DealImpactArea.VALUATION),
                    (forecast, actual),
                    "Provide the customer-level bridge supporting forecast growth.",
                )
            )
        missing = (
            _missing(
                context,
                self.agent_id,
                "Customer churn and retention report",
                "The VDR contains concentration data but no cohort-level retention history.",
                Priority.HIGH,
            ),
        )
        return SpecialistResult(
            self.agent_id,
            tuple(findings),
            missing,
            _questions(context, self.agent_id, tuple(findings)),
            (
                "External market research was not performed; commercial conclusions use VDR evidence only.",
            ),
        )


class LegalContractualAnalyzer:
    """Contract issue spotting only; outputs are not legal advice."""

    agent_id = AgentId.LEGAL_CONTRACTUAL
    retrieval_plan = LEGAL_PLAN

    def analyze(self, context: SpecialistContext) -> SpecialistResult:
        specs = (
            (
                "change_of_control_consent",
                "legal-change-control",
                "Change-of-control consent or termination right",
                Severity.HIGH,
                DealImpactArea.CLOSING_CONDITION,
                "Confirm whether required consent has been obtained.",
            ),
            (
                "termination_for_convenience",
                "legal-termination",
                "Termination-for-convenience right",
                Severity.HIGH,
                DealImpactArea.DEAL_THESIS,
                "Quantify revenue exposed to termination rights and confirm current customer intent.",
            ),
            (
                "assignment_restriction",
                "legal-assignment",
                "Assignment restriction",
                Severity.MEDIUM,
                DealImpactArea.LEGAL_PROTECTIONS,
                "Confirm transaction structure and any required assignment consent.",
            ),
        )
        findings: list[AttributedFinding] = []
        for topic, finding_id, title, severity, impact, question in specs:
            claim = _true_claim(context.claims, topic)
            if claim is not None:
                findings.append(
                    _risk_finding(
                        context,
                        self.agent_id,
                        finding_id,
                        topic,
                        title,
                        f"The contract evidence contains a {title.casefold()}.",
                        severity,
                        (impact, DealImpactArea.REPS_AND_WARRANTIES),
                        (claim,),
                        question,
                    )
                )
        consent_claim = _true_claim(context.claims, "change_of_control_consent")
        missing: tuple[MissingInformation, ...] = ()
        if consent_claim is not None:
            missing = (
                _missing(
                    context,
                    self.agent_id,
                    "Executed change-of-control consent",
                    "The material customer agreement indicates a transaction-related consent or termination right.",
                    Priority.URGENT,
                    related_finding_id="legal-change-control",
                ),
            )
        return SpecialistResult(
            self.agent_id,
            tuple(findings),
            missing,
            _questions(context, self.agent_id, tuple(findings)),
            ("Contract outputs are issue spotting and are not legal advice.",),
        )


class OperationalDiligenceAnalyzer:
    agent_id = AgentId.OPERATIONAL
    retrieval_plan = OPERATIONAL_PLAN

    def analyze(self, context: SpecialistContext) -> SpecialistResult:
        findings: list[AttributedFinding] = []
        supplier = _highest_claim(context.claims, "supplier_concentration_percent")
        if (
            supplier is not None
            and supplier.numeric_value is not None
            and supplier.numeric_value >= 50
        ):
            findings.append(
                _risk_finding(
                    context,
                    self.agent_id,
                    "operational-supplier-concentration",
                    "supplier_concentration",
                    "High supplier concentration",
                    f"The identified supplier represents {supplier.numeric_value}% of relevant supply.",
                    Severity.HIGH,
                    (DealImpactArea.POST_CLOSE_OPERATIONS, DealImpactArea.INTEGRATION_PLANNING),
                    (supplier,),
                    "Provide qualified alternatives, lead times, and transition costs.",
                    percentage=supplier.numeric_value,
                )
            )
        sole_source = _true_claim(context.claims, "single_source_supplier")
        if sole_source is not None:
            findings.append(
                _risk_finding(
                    context,
                    self.agent_id,
                    "operational-single-source",
                    "single_source_dependency",
                    "Single-source component dependency",
                    "A supplier agreement or operations report identifies a sole-source component.",
                    Severity.HIGH,
                    (DealImpactArea.POST_CLOSE_OPERATIONS,),
                    (sole_source,),
                    "Provide supplier alternatives, qualification status, safety stock, and lead times.",
                )
            )
        capacity = _highest_claim(context.claims, "capacity_utilization")
        if (
            capacity is not None
            and capacity.numeric_value is not None
            and capacity.numeric_value >= 90
        ):
            findings.append(
                _risk_finding(
                    context,
                    self.agent_id,
                    "operational-capacity",
                    "capacity_constraint",
                    "Limited operating capacity headroom",
                    f"Reported capacity utilization is {capacity.numeric_value}%.",
                    Severity.MEDIUM,
                    (DealImpactArea.POST_CLOSE_OPERATIONS, DealImpactArea.DEAL_THESIS),
                    (capacity,),
                    "Provide capacity expansion plans, timing, cost, and contingency measures.",
                )
            )
        missing = (
            _missing(
                context,
                self.agent_id,
                "Business continuity and supplier contingency plan",
                "Operational evidence identifies concentrated or sole-source supply without a supporting contingency document.",
                Priority.HIGH,
            ),
        )
        return SpecialistResult(
            self.agent_id,
            tuple(findings),
            missing,
            _questions(context, self.agent_id, tuple(findings)),
        )


def _risk_finding(
    context: SpecialistContext,
    agent_id: AgentId,
    finding_id: str,
    category: str,
    title: str,
    description: str,
    severity: Severity,
    impacts: tuple[DealImpactArea, ...],
    claims: tuple[InvestigationClaim, ...],
    follow_up: str,
    *,
    percentage: Decimal | None = None,
) -> AttributedFinding:
    evidence = _claim_evidence(claims)
    materiality = MaterialityAssessment(
        qualitative=QualitativeMateriality.HIGH
        if percentage is not None and percentage >= 40
        else QualitativeMateriality.MEDIUM,
        percentage=percentage,
        benchmark="Revenue"
        if percentage is not None and "customer" in category
        else "Relevant supply"
        if percentage is not None
        else None,
        rationale="Quantitative source data retained where available; severity remains a separate recommendation.",
    )
    finding = DiligenceFinding(
        finding_id=finding_id,
        engagement_id=context.engagement.engagement_id,
        workstream=_workstream(agent_id),
        category=category,
        title=title,
        description=description,
        finding_type=FindingType.RISK,
        severity=severity,
        materiality=materiality,
        support_status=SupportStatus.SOURCE_BACKED,
        evidence=evidence,
        impact_areas=impacts,
        potential_deal_impact="Potential effect requires transaction-team and specialist review.",
        recommended_follow_up=follow_up,
        risk=RiskAssessment(category, LikelihoodBand.UNKNOWN, impacts, description),
    )
    return AttributedFinding(
        finding,
        (agent_id,),
        (finding_id,),
        "Severity is a reviewable recommendation based only on available VDR evidence.",
        tuple(claim.claim_id for claim in claims),
    )


def _ground_financial_finding(
    finding: DiligenceFinding, claims: tuple[InvestigationClaim, ...]
) -> DiligenceFinding:
    if finding.evidence or finding.finding_id != "fin-customer-concentration":
        return finding
    concentration = _highest_claim(claims, "customer_concentration_percent")
    if concentration is None:
        return finding
    return replace(
        finding,
        evidence=(concentration.evidence,),
        supporting_fact_ids=(*finding.supporting_fact_ids, concentration.claim_id),
    )


def _missing(
    context: SpecialistContext,
    agent_id: AgentId,
    requested_item: str,
    reason: str,
    priority: Priority,
    *,
    related_finding_id: str | None = None,
) -> MissingInformation:
    return MissingInformation(
        f"missing-{agent_id.value}-{requested_item.casefold().replace(' ', '-')}",
        context.engagement.engagement_id,
        requested_item,
        _workstream(agent_id),
        priority,
        reason,
        MissingInformationStatus.IDENTIFIED,
        priority is Priority.URGENT,
        f"Please provide {requested_item.casefold()}.",
        related_finding_id,
    )


def _questions(
    context: SpecialistContext,
    agent_id: AgentId,
    findings: tuple[AttributedFinding, ...],
) -> tuple[FollowUpQuestion, ...]:
    return tuple(
        FollowUpQuestion(
            f"question-{agent_id.value}-{index}",
            context.engagement.engagement_id,
            finding.finding.workstream,
            finding.finding.recommended_follow_up or "Provide supporting evidence.",
            Priority.HIGH
            if finding.finding.severity in {Severity.HIGH, Severity.CRITICAL}
            else Priority.MEDIUM,
            finding.finding.description,
            QuestionStatus.DRAFT,
            finding.finding.finding_id,
        )
        for index, finding in enumerate(findings, start=1)
    )


def _workstream(agent_id: AgentId) -> DiligenceWorkstream:
    return {
        AgentId.FINANCIAL: DiligenceWorkstream.FINANCIAL,
        AgentId.COMMERCIAL: DiligenceWorkstream.COMMERCIAL,
        AgentId.LEGAL_CONTRACTUAL: DiligenceWorkstream.LEGAL_CONTRACTUAL,
        AgentId.OPERATIONAL: DiligenceWorkstream.OPERATIONAL,
        AgentId.CROSS_DOCUMENT: DiligenceWorkstream.OPERATIONAL,
    }[agent_id]


def _active_claims(
    claims: tuple[InvestigationClaim, ...], topic: str
) -> tuple[InvestigationClaim, ...]:
    return tuple(
        claim
        for claim in claims
        if claim.topic == topic and claim.status is not ClaimStatus.SUPERSEDED
    )


def _highest_claim(claims: tuple[InvestigationClaim, ...], topic: str) -> InvestigationClaim | None:
    values = tuple(
        claim for claim in _active_claims(claims, topic) if claim.numeric_value is not None
    )
    return max(values, key=lambda item: item.numeric_value or Decimal("0"), default=None)


def _earliest_claim(
    claims: tuple[InvestigationClaim, ...], topic: str
) -> InvestigationClaim | None:
    values = tuple(claim for claim in _active_claims(claims, topic) if claim.date_value is not None)
    return min(values, key=lambda item: item.date_value or date.max, default=None)


def _true_claim(claims: tuple[InvestigationClaim, ...], topic: str) -> InvestigationClaim | None:
    return next(
        (claim for claim in _active_claims(claims, topic) if claim.boolean_value is True), None
    )


def _claim_evidence(claims: tuple[InvestigationClaim, ...]) -> tuple[EvidenceReference, ...]:
    by_id = {claim.evidence.evidence_id: claim.evidence for claim in claims}
    return tuple(by_id[key] for key in sorted(by_id))
