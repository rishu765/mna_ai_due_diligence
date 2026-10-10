"""Cross-source financial reconciliation with transparent source priority."""

from __future__ import annotations

from dataclasses import dataclass, field

from ma_due_diligence.domain import DocumentType
from ma_due_diligence.financial.models import (
    CalculationWarning,
    CalculationWarningCode,
    FinancialMetric,
    FinancialObservation,
    FinancialThresholds,
    FinancialUnit,
    ReconciliationResult,
    ReconciliationStatus,
)
from ma_due_diligence.financial.normalization import normalize_unit, safe_ratio


@dataclass(frozen=True, slots=True)
class SourcePriorityPolicy:
    """Default ranking can be overridden per metric and document type."""

    default_order: tuple[DocumentType, ...] = (
        DocumentType.FINANCIAL_STATEMENTS,
        DocumentType.GENERAL_LEDGER_EXPORT,
        DocumentType.MANAGEMENT_ACCOUNTS,
        DocumentType.BOARD_MATERIAL,
        DocumentType.MANAGEMENT_PRESENTATION,
        DocumentType.SALES_REPORT,
        DocumentType.OTHER,
    )
    metric_overrides: dict[FinancialMetric, tuple[DocumentType, ...]] = field(default_factory=dict)

    def rank(self, observation: FinancialObservation) -> int:
        order = self.metric_overrides.get(observation.metric, self.default_order)
        try:
            return order.index(observation.source_document_type)
        except ValueError:
            return len(order)


class FinancialReconciliationService:
    def __init__(
        self,
        policy: SourcePriorityPolicy | None = None,
        thresholds: FinancialThresholds | None = None,
    ) -> None:
        self.policy = policy or SourcePriorityPolicy()
        self.thresholds = thresholds or FinancialThresholds()

    def reconcile(
        self,
        metric: FinancialMetric,
        observations: tuple[FinancialObservation, ...],
        *,
        target_unit: FinancialUnit = FinancialUnit.MILLION,
    ) -> ReconciliationResult:
        relevant = tuple(
            item for item in observations if item.metric is metric and item.value is not None
        )
        if len(relevant) < 2:
            return ReconciliationResult(
                metric,
                None if not relevant else relevant[0].period,
                relevant,
                None if not relevant else relevant[0].observation_id,
                None,
                None,
                ReconciliationStatus.INSUFFICIENT_DATA,
                False,
                "At least two supported observations are required for reconciliation.",
                (
                    CalculationWarning(
                        CalculationWarningCode.MISSING_INPUT, "Insufficient observations."
                    ),
                ),
            )
        periods = {item.period.label.casefold() for item in relevant}
        if len(periods) > 1:
            return self._incompatible(metric, relevant, ReconciliationStatus.PERIOD_MISMATCH)
        currencies = {item.currency for item in relevant}
        if len(currencies) > 1:
            return self._incompatible(metric, relevant, ReconciliationStatus.CURRENCY_MISMATCH)
        normalized = tuple(normalize_unit(item, target_unit) for item in relevant)
        preferred = min(normalized, key=lambda item: (self.policy.rank(item), item.observation_id))
        values = tuple(item.value for item in normalized if item.value is not None)
        assert preferred.value is not None
        absolute = max(values) - min(values)
        percentage = safe_ratio(absolute, abs(preferred.value))
        material = (
            percentage is not None and percentage >= self.thresholds.material_variance_percent
        )
        status = (
            ReconciliationStatus.ALIGNED
            if absolute == 0
            else ReconciliationStatus.CONFLICTING
            if material
            else ReconciliationStatus.VARIANCE
        )
        warnings = (
            (
                CalculationWarning(
                    CalculationWarningCode.CONFLICTING_VALUES,
                    "Source values exceed the configured material variance threshold.",
                ),
            )
            if material
            else ()
        )
        return ReconciliationResult(
            metric,
            preferred.period,
            relevant,
            preferred.observation_id,
            absolute,
            percentage,
            status,
            material,
            "Preferred source selected by the disclosed source-priority policy; all values retained.",
            warnings,
        )

    @staticmethod
    def _incompatible(
        metric: FinancialMetric,
        observations: tuple[FinancialObservation, ...],
        status: ReconciliationStatus,
    ) -> ReconciliationResult:
        code = (
            CalculationWarningCode.PERIOD_MISMATCH
            if status is ReconciliationStatus.PERIOD_MISMATCH
            else CalculationWarningCode.MIXED_CURRENCIES
        )
        return ReconciliationResult(
            metric,
            None,
            observations,
            None,
            None,
            None,
            status,
            True,
            "Values were preserved and not reconciled because their bases are incompatible.",
            (CalculationWarning(code, "Observations require an explicit normalization policy."),),
        )
