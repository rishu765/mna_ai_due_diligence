"""Rule-based adjustment assessment and deterministic EBITDA bridge."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from ma_due_diligence.domain import (
    AdjustmentDirection,
    AdjustmentType,
    AnalystDecision,
    FinancialAdjustment,
    ProposalStatus,
    Recurrence,
)
from ma_due_diligence.financial.models import (
    AdjustmentAssessment,
    CalculationLine,
    CalculationWarning,
    CalculationWarningCode,
    EbitdaBridge,
    FinancialObservation,
    FinancialThresholds,
    FinancialUnit,
)
from ma_due_diligence.financial.normalization import convert_value, normalize_unit, safe_ratio


class AdjustmentAssessmentService:
    def __init__(self, thresholds: FinancialThresholds | None = None) -> None:
        self.thresholds = thresholds or FinancialThresholds()

    def assess(
        self, adjustments: tuple[FinancialAdjustment, ...]
    ) -> tuple[AdjustmentAssessment, ...]:
        labels = Counter((item.adjustment_type, item.rationale.casefold()) for item in adjustments)
        seen: set[tuple[AdjustmentType, str, Decimal, str]] = set()
        output: list[AdjustmentAssessment] = []
        for item in adjustments:
            rules: list[str] = []
            warnings: list[CalculationWarning] = []
            key = (
                item.adjustment_type,
                item.period.label.casefold(),
                item.amount.amount,
                item.rationale.casefold(),
            )
            if key in seen:
                rules.append("duplicate_adjustment")
                warnings.append(
                    CalculationWarning(
                        CalculationWarningCode.DUPLICATE_ITEM,
                        "An identical adjustment is already present.",
                    )
                )
            seen.add(key)
            repeated = (
                labels[(item.adjustment_type, item.rationale.casefold())]
                >= self.thresholds.repeated_adjustment_count
            )
            if item.recurrence is Recurrence.NONRECURRING and repeated:
                rules.append("repeated_one_time_item")
                warnings.append(
                    CalculationWarning(
                        CalculationWarningCode.RECURRING_ADJUSTMENT,
                        "The purported nonrecurring category appears in multiple periods.",
                    )
                )
            if not item.evidence:
                rules.append("missing_evidence")
                warnings.append(
                    CalculationWarning(
                        CalculationWarningCode.MISSING_EVIDENCE,
                        "The adjustment has no supporting evidence.",
                    )
                )
            if (
                item.adjustment_type is AdjustmentType.RUN_RATE
                and item.verification_status.value != "verified"
            ):
                rules.append("unrealized_run_rate")
                warnings.append(
                    CalculationWarning(
                        CalculationWarningCode.UNREALIZED_RUN_RATE,
                        "The run-rate benefit is not verified as realized.",
                    )
                )
            accepted = (
                item.proposal_status is ProposalStatus.ACCEPTED
                and item.analyst_decision is AnalystDecision.ACCEPT
                and not rules
            )
            output.append(AdjustmentAssessment(item, accepted, tuple(rules), tuple(warnings)))
        return tuple(output)


def build_ebitda_bridge(
    reported: FinancialObservation,
    assessments: tuple[AdjustmentAssessment, ...],
    *,
    target_unit: FinancialUnit = FinancialUnit.MILLION,
) -> EbitdaBridge:
    normalized = normalize_unit(reported, target_unit)
    management = tuple(item.adjustment for item in assessments)
    accepted = tuple(item.adjustment for item in assessments if item.accepted_for_bridge)
    rejected = tuple(item.adjustment for item in assessments if not item.accepted_for_bridge)
    warnings = tuple(warning for item in assessments for warning in item.warnings)
    if normalized.value is None:
        return EbitdaBridge(
            reported,
            management,
            rejected,
            (),
            accepted,
            (),
            None,
            None,
            None,
            normalized.currency or "GBP",
            target_unit,
            warnings
            + (
                CalculationWarning(
                    CalculationWarningCode.MISSING_INPUT, "Reported EBITDA is missing."
                ),
            ),
        )
    lines: list[CalculationLine] = [
        CalculationLine(
            "Reported EBITDA",
            normalized.value,
            "base",
            (reported.observation_id,),
            reported.evidence,
        )
    ]
    total = Decimal("0")
    for adjustment in accepted:
        factor = (
            Decimal("1") if adjustment.direction is AdjustmentDirection.INCREASE else Decimal("-1")
        )
        amount = (
            convert_value(
                adjustment.amount.amount,
                FinancialUnit(adjustment.unit),
                target_unit,
            )
            * factor
        )
        total += amount
        lines.append(
            CalculationLine(
                adjustment.rationale,
                amount,
                "+" if amount >= 0 else "-",
                (adjustment.adjustment_id, *adjustment.input_fact_ids),
                adjustment.evidence,
            )
        )
    final = normalized.value + total
    return EbitdaBridge(
        reported,
        management,
        rejected,
        accepted,
        accepted,
        tuple(lines),
        final,
        total,
        safe_ratio(total, abs(normalized.value)),
        normalized.currency or "GBP",
        target_unit,
        warnings,
    )
