"""Deterministic candidate financial findings and follow-up requests."""

from __future__ import annotations

from decimal import Decimal

from ma_due_diligence.domain import (
    DealImpactArea,
    DiligenceFinding,
    DiligenceWorkstream,
    EvidenceReference,
    FindingType,
    FollowUpQuestion,
    LikelihoodBand,
    MaterialityAssessment,
    Priority,
    QualitativeMateriality,
    QuestionStatus,
    RiskAssessment,
    Severity,
    SupportStatus,
)
from ma_due_diligence.financial.models import (
    CalculationLine,
    CustomerConcentrationResult,
    EbitdaBridge,
    FinancialFindingOutput,
    FinancialObservation,
    FinancialThresholds,
    GrowthResult,
    MarginResult,
    NetDebtBridge,
    ReconciliationResult,
    ReconciliationStatus,
    WorkingCapitalTrend,
)


def materiality_for_amount(
    amount: Decimal,
    benchmark: FinancialObservation | None,
    *,
    rationale: str,
) -> MaterialityAssessment:
    percentage = None
    if benchmark is not None and benchmark.value not in {None, Decimal("0")}:
        percentage = abs(amount) / abs(benchmark.value) * Decimal("100")  # type: ignore[arg-type]
    qualitative = (
        QualitativeMateriality.HIGH
        if percentage is not None and percentage >= Decimal("10")
        else QualitativeMateriality.MEDIUM
        if percentage is not None and percentage >= Decimal("5")
        else QualitativeMateriality.LOW
    )
    return MaterialityAssessment(
        qualitative=qualitative,
        percentage=percentage,
        benchmark=None if percentage is None or benchmark is None else benchmark.metric.value,
        rationale=rationale,
    )


class FinancialFindingService:
    def __init__(self, thresholds: FinancialThresholds | None = None) -> None:
        self.thresholds = thresholds or FinancialThresholds()

    def generate(
        self,
        *,
        engagement_id: str,
        reconciliations: tuple[ReconciliationResult, ...] = (),
        concentration: CustomerConcentrationResult | None = None,
        bridge: EbitdaBridge | None = None,
        nwc_trend: WorkingCapitalTrend | None = None,
        net_debt: NetDebtBridge | None = None,
        revenue_growth_results: tuple[GrowthResult, ...] = (),
        margin_results: tuple[MarginResult, ...] = (),
    ) -> tuple[FinancialFindingOutput, ...]:
        output: list[FinancialFindingOutput] = []
        for result in reconciliations:
            if result.status is not ReconciliationStatus.CONFLICTING:
                continue
            evidence = _unique_evidence(
                tuple(item for obs in result.observations for item in obs.evidence)
            )
            fact_ids = tuple(item.observation_id for item in result.observations)
            amount = result.absolute_variance or Decimal("0")
            preferred = next(
                (
                    item
                    for item in result.observations
                    if item.observation_id == result.preferred_observation_id
                ),
                None,
            )
            finding = DiligenceFinding(
                finding_id=f"fin-conflict-{result.metric.value}",
                engagement_id=engagement_id,
                workstream=DiligenceWorkstream.FINANCIAL,
                category="source_reconciliation",
                title=f"Material {result.metric.value.replace('_', ' ')} discrepancy",
                description="Financial sources report materially different values for the same period.",
                finding_type=FindingType.INCONSISTENCY,
                severity=Severity.HIGH,
                materiality=materiality_for_amount(
                    amount, preferred, rationale="Measured against the preferred source value."
                ),
                support_status=SupportStatus.CONFLICTING,
                conflicting_fact_ids=fact_ids,
                evidence=evidence,
                affected_topic=result.metric.value,
                impact_areas=(DealImpactArea.QUALITY_OF_EARNINGS, DealImpactArea.VALUATION),
                recommended_follow_up="Reconcile the source values and provide the supporting ledger bridge.",
            )
            output.append(FinancialFindingOutput(finding, fact_ids, (), result.rationale))
        if concentration is not None and concentration.concentrated:
            percentage = concentration.largest_customer_percent
            finding = DiligenceFinding(
                finding_id="fin-customer-concentration",
                engagement_id=engagement_id,
                workstream=DiligenceWorkstream.FINANCIAL,
                category="revenue_quality",
                title="Material customer concentration",
                description=f"The largest customer represents {percentage}% of identified revenue.",
                finding_type=FindingType.RISK,
                severity=Severity.HIGH,
                materiality=MaterialityAssessment(
                    qualitative=QualitativeMateriality.HIGH,
                    percentage=percentage,
                    benchmark="Revenue",
                    rationale="Largest-customer share exceeds the configured threshold.",
                ),
                support_status=SupportStatus.DERIVED,
                affected_topic="customer_concentration",
                impact_areas=(DealImpactArea.QUALITY_OF_EARNINGS, DealImpactArea.DEAL_THESIS),
                recommended_follow_up="Provide renewal, churn, and pipeline details for the largest customer.",
                risk=RiskAssessment(
                    "customer_concentration",
                    LikelihoodBand.UNKNOWN,
                    (DealImpactArea.QUALITY_OF_EARNINGS, DealImpactArea.DEAL_THESIS),
                    "Revenue dependency may affect earnings sustainability.",
                ),
            )
            output.append(FinancialFindingOutput(finding, (), ()))
        if bridge is not None and any(
            w.code.value == "recurring_adjustment" for w in bridge.warnings
        ):
            finding = DiligenceFinding(
                finding_id="fin-recurring-addback",
                engagement_id=engagement_id,
                workstream=DiligenceWorkstream.FINANCIAL,
                category="quality_of_earnings",
                title="Repeated item presented as nonrecurring",
                description="A management EBITDA adjustment category appears across multiple periods.",
                finding_type=FindingType.FINANCIAL_ADJUSTMENT,
                severity=Severity.MEDIUM,
                materiality=MaterialityAssessment(rationale="Requires analyst assessment."),
                support_status=SupportStatus.SOURCE_BACKED,
                evidence=_unique_evidence(
                    tuple(
                        item
                        for adjustment in bridge.management_adjustments
                        for item in adjustment.evidence
                    )
                ),
                affected_topic="adjusted_ebitda",
                impact_areas=(DealImpactArea.QUALITY_OF_EARNINGS,),
                recommended_follow_up="Explain why the recurring category should qualify as an add-back.",
            )
            output.append(FinancialFindingOutput(finding, (), bridge.lines))
        if (
            nwc_trend is not None
            and nwc_trend.average is not None
            and nwc_trend.average != 0
            and nwc_trend.recent_variance_from_average is not None
        ):
            deviation = abs(
                nwc_trend.recent_variance_from_average / nwc_trend.average * Decimal("100")
            )
            if deviation >= self.thresholds.nwc_deviation_percent:
                output.append(
                    self._simple_finding(
                        engagement_id,
                        "fin-nwc-volatility",
                        "Working-capital volatility",
                        "Recent NWC differs materially from historical average.",
                        DealImpactArea.WORKING_CAPITAL,
                        nwc_trend.results[-1].lines,
                    )
                )
        if net_debt is not None and any(
            w.code.value == "unsupported_classification" for w in net_debt.warnings
        ):
            output.append(
                self._simple_finding(
                    engagement_id,
                    "fin-restricted-cash",
                    "Restricted cash classification",
                    "Restricted cash was presented within cash evidence and excluded from available cash.",
                    DealImpactArea.NET_DEBT,
                    net_debt.lines,
                )
            )
        for growth in revenue_growth_results:
            if (
                growth.percentage is not None
                and growth.percentage >= self.thresholds.forecast_growth_percent
            ):
                output.append(
                    self._derived_finding(
                        engagement_id,
                        f"fin-growth-{growth.current_period.label}",
                        "Unusually high revenue growth",
                        f"Revenue growth of {growth.percentage}% exceeds the configured threshold.",
                        "revenue_growth",
                        growth.input_observation_ids,
                    )
                )
        known_margins = tuple(item for item in margin_results if item.percentage is not None)
        for prior, current in zip(known_margins, known_margins[1:], strict=False):
            assert prior.percentage is not None and current.percentage is not None
            decline = prior.percentage - current.percentage
            if decline >= self.thresholds.margin_change_points:
                output.append(
                    self._derived_finding(
                        engagement_id,
                        f"fin-margin-{current.period.label}",
                        "Declining margin trend",
                        f"Margin declined by {decline} percentage points.",
                        current.metric.value,
                        current.input_observation_ids,
                    )
                )
        return tuple(output)

    @staticmethod
    def _simple_finding(
        engagement_id: str,
        finding_id: str,
        title: str,
        description: str,
        impact: DealImpactArea,
        lines: tuple[CalculationLine, ...],
    ) -> FinancialFindingOutput:
        evidence = _unique_evidence(tuple(item for line in lines for item in line.evidence))
        finding = DiligenceFinding(
            finding_id=finding_id,
            engagement_id=engagement_id,
            workstream=DiligenceWorkstream.FINANCIAL,
            category="financial_red_flag",
            title=title,
            description=description,
            finding_type=FindingType.RED_FLAG,
            severity=Severity.MEDIUM,
            materiality=MaterialityAssessment(
                rationale="Quantification retained in the calculation trace."
            ),
            support_status=SupportStatus.SOURCE_BACKED if evidence else SupportStatus.UNVERIFIED,
            evidence=evidence,
            impact_areas=(impact,),
            recommended_follow_up="Provide supporting detail and management's reconciliation.",
        )
        return FinancialFindingOutput(finding, (), lines)

    @staticmethod
    def _derived_finding(
        engagement_id: str,
        finding_id: str,
        title: str,
        description: str,
        topic: str,
        observation_ids: tuple[str, ...],
    ) -> FinancialFindingOutput:
        finding = DiligenceFinding(
            finding_id=finding_id,
            engagement_id=engagement_id,
            workstream=DiligenceWorkstream.FINANCIAL,
            category="revenue_quality",
            title=title,
            description=description,
            finding_type=FindingType.RED_FLAG,
            severity=Severity.MEDIUM,
            materiality=MaterialityAssessment(
                rationale="Compared with configured trend thresholds."
            ),
            support_status=SupportStatus.DERIVED,
            affected_topic=topic,
            supporting_fact_ids=observation_ids,
            impact_areas=(DealImpactArea.QUALITY_OF_EARNINGS,),
            recommended_follow_up="Explain the underlying drivers and provide supporting monthly detail.",
        )
        return FinancialFindingOutput(finding, observation_ids, ())


def follow_up_questions(
    engagement_id: str, findings: tuple[FinancialFindingOutput, ...]
) -> tuple[FollowUpQuestion, ...]:
    questions: list[FollowUpQuestion] = []
    for index, output in enumerate(findings, start=1):
        wording = output.finding.recommended_follow_up
        if wording is None:
            continue
        questions.append(
            FollowUpQuestion(
                question_id=f"fin-question-{index}",
                engagement_id=engagement_id,
                workstream=DiligenceWorkstream.FINANCIAL,
                question=wording,
                priority=Priority.HIGH
                if output.finding.severity is Severity.HIGH
                else Priority.MEDIUM,
                rationale=output.finding.description,
                status=QuestionStatus.DRAFT,
                related_finding_id=output.finding.finding_id,
            )
        )
    return tuple(questions)


def _unique_evidence(evidence: tuple[EvidenceReference, ...]) -> tuple[EvidenceReference, ...]:
    by_id = {item.evidence_id: item for item in evidence}
    return tuple(by_id[key] for key in sorted(by_id))
