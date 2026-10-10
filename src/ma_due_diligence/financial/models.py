"""Typed contracts for financial diligence inputs and deterministic outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from ma_due_diligence.domain import (
    DiligenceFinding,
    DocumentType,
    EvidenceReference,
    FinancialAdjustment,
    FinancialPeriod,
    SupportStatus,
)
from ma_due_diligence.errors import DomainValidationError

_CURRENCY = re.compile(r"[A-Z]{3}")


def _required(value: str, name: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainValidationError(f"{name} must not be blank")
    return normalized


def _finite(value: Decimal, name: str) -> Decimal:
    if not value.is_finite():
        raise DomainValidationError(f"{name} must be finite")
    return value


def _money_currency(value: str) -> str:
    normalized = value.strip().upper()
    if _CURRENCY.fullmatch(normalized) is None:
        raise DomainValidationError("currency must be a three-letter uppercase code")
    return normalized


class FinancialMetric(StrEnum):
    REVENUE = "revenue"
    GROSS_PROFIT = "gross_profit"
    GROSS_MARGIN = "gross_margin"
    EBITDA = "ebitda"
    ADJUSTED_EBITDA = "adjusted_ebitda"
    EBITDA_MARGIN = "ebitda_margin"
    EBIT = "ebit"
    NET_INCOME = "net_income"
    CASH = "cash"
    DEBT = "debt"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    INVENTORY = "inventory"
    ACCOUNTS_PAYABLE = "accounts_payable"
    ACCRUALS = "accruals"
    DEFERRED_REVENUE = "deferred_revenue"
    CAPEX = "capex"
    NET_WORKING_CAPITAL = "net_working_capital"
    CUSTOMER_REVENUE = "customer_revenue"
    OTHER = "other"


class FinancialUnit(StrEnum):
    UNITS = "units"
    THOUSAND = "thousand"
    MILLION = "million"
    BILLION = "billion"
    PERCENT = "percent"


class ReportingStatus(StrEnum):
    ACTUAL = "actual"
    FORECAST = "forecast"


class MetricBasis(StrEnum):
    REPORTED = "reported"
    MANAGEMENT_ADJUSTED = "management_adjusted"
    DILIGENCE_ADJUSTED = "diligence_adjusted"


class ReconciliationStatus(StrEnum):
    ALIGNED = "aligned"
    VARIANCE = "variance"
    CONFLICTING = "conflicting"
    PERIOD_MISMATCH = "period_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"
    INSUFFICIENT_DATA = "insufficient_data"


class CalculationWarningCode(StrEnum):
    MISSING_INPUT = "missing_input"
    ZERO_DENOMINATOR = "zero_denominator"
    PERIOD_MISMATCH = "period_mismatch"
    MIXED_CURRENCIES = "mixed_currencies"
    CONFLICTING_VALUES = "conflicting_values"
    INCOMPLETE_HISTORY = "incomplete_history"
    DUPLICATE_ITEM = "duplicate_item"
    UNSUPPORTED_CLASSIFICATION = "unsupported_classification"
    RECURRING_ADJUSTMENT = "recurring_adjustment"
    MISSING_EVIDENCE = "missing_evidence"
    UNREALIZED_RUN_RATE = "unrealized_run_rate"


class ClassificationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROPOSED = "proposed"
    REVIEW_REQUIRED = "review_required"
    CONFLICTING = "conflicting"
    UNVERIFIED = "unverified"


class NetDebtCategory(StrEnum):
    REPORTED_DEBT = "reported_debt"
    DEBT_LIKE = "debt_like"
    CASH = "cash"
    CASH_LIKE = "cash_like"


class NwcPegMethod(StrEnum):
    TRAILING_AVERAGE = "trailing_average"
    MEDIAN = "median"
    SELECTED_SEASONAL_PERIOD = "selected_seasonal_period"


@dataclass(frozen=True, slots=True)
class FinancialObservation:
    observation_id: str
    engagement_id: str
    metric: FinancialMetric
    value: Decimal | None
    currency: str | None
    unit: FinancialUnit
    period: FinancialPeriod
    reporting_status: ReportingStatus
    basis: MetricBasis
    source_document_type: DocumentType
    source_label: str
    evidence: tuple[EvidenceReference, ...]
    support_status: SupportStatus
    extraction_method: str

    def __post_init__(self) -> None:
        for name in ("observation_id", "engagement_id", "source_label", "extraction_method"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.value is not None:
            object.__setattr__(self, "value", _finite(self.value, "observation value"))
        if self.currency is not None:
            object.__setattr__(self, "currency", _money_currency(self.currency))
        if self.unit is FinancialUnit.PERCENT and self.currency is not None:
            raise DomainValidationError("percent observations cannot carry currency")
        if (
            self.unit is not FinancialUnit.PERCENT
            and self.currency is None
            and self.value is not None
        ):
            raise DomainValidationError("monetary observations require currency")
        if self.value is None and self.support_status not in {
            SupportStatus.MISSING,
            SupportStatus.UNVERIFIED,
        }:
            raise DomainValidationError("unknown observation values must be missing or unverified")
        if self.value is not None and self.support_status is SupportStatus.MISSING:
            raise DomainValidationError("missing observations cannot have a value")
        if (
            self.support_status
            in {
                SupportStatus.SOURCE_BACKED,
                SupportStatus.VERIFIED,
                SupportStatus.SINGLE_SOURCE,
                SupportStatus.CONFLICTING,
            }
            and not self.evidence
        ):
            raise DomainValidationError("source-supported observations require evidence")


@dataclass(frozen=True, slots=True)
class CalculationWarning:
    code: CalculationWarningCode
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", _required(self.message, "warning message"))


@dataclass(frozen=True, slots=True)
class CalculationLine:
    label: str
    amount: Decimal
    operation: str
    source_ids: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _required(self.label, "calculation label"))
        object.__setattr__(self, "operation", _required(self.operation, "operation"))
        object.__setattr__(self, "amount", _finite(self.amount, "line amount"))


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    metric: FinancialMetric
    period: FinancialPeriod | None
    observations: tuple[FinancialObservation, ...]
    preferred_observation_id: str | None
    absolute_variance: Decimal | None
    percent_variance: Decimal | None
    status: ReconciliationStatus
    unresolved_conflict: bool
    rationale: str
    warnings: tuple[CalculationWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class AdjustmentAssessment:
    adjustment: FinancialAdjustment
    accepted_for_bridge: bool
    rule_codes: tuple[str, ...]
    warnings: tuple[CalculationWarning, ...]


@dataclass(frozen=True, slots=True)
class EbitdaBridge:
    reported_ebitda: FinancialObservation
    management_adjustments: tuple[FinancialAdjustment, ...]
    rejected_adjustments: tuple[FinancialAdjustment, ...]
    diligence_adjustments: tuple[FinancialAdjustment, ...]
    accepted_adjustments: tuple[FinancialAdjustment, ...]
    lines: tuple[CalculationLine, ...]
    final_adjusted_ebitda: Decimal | None
    total_adjustment: Decimal | None
    uplift_percent: Decimal | None
    currency: str
    unit: FinancialUnit
    warnings: tuple[CalculationWarning, ...]


@dataclass(frozen=True, slots=True)
class MarginResult:
    metric: FinancialMetric
    period: FinancialPeriod
    percentage: Decimal | None
    input_observation_ids: tuple[str, ...]
    warnings: tuple[CalculationWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class GrowthResult:
    metric: FinancialMetric
    prior_period: FinancialPeriod
    current_period: FinancialPeriod
    percentage: Decimal | None
    warnings: tuple[CalculationWarning, ...] = ()
    input_observation_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CustomerRevenue:
    customer_id: str
    revenue: Decimal
    currency: str
    unit: FinancialUnit
    period: FinancialPeriod
    evidence: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_id", _required(self.customer_id, "customer_id"))
        object.__setattr__(self, "revenue", _finite(self.revenue, "customer revenue"))
        if self.revenue < 0:
            raise DomainValidationError("customer revenue must not be negative")
        object.__setattr__(self, "currency", _money_currency(self.currency))


@dataclass(frozen=True, slots=True)
class CustomerConcentrationResult:
    period: FinancialPeriod
    total_revenue: Decimal | None
    largest_customer_percent: Decimal | None
    top_five_percent: Decimal | None
    top_ten_percent: Decimal | None
    customer_count: int
    concentrated: bool | None
    warnings: tuple[CalculationWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkingCapitalPeriod:
    period: FinancialPeriod
    accounts_receivable: Decimal | None
    inventory: Decimal | None
    accounts_payable: Decimal | None
    other_operating_current_assets: Decimal = Decimal("0")
    other_operating_current_liabilities: Decimal = Decimal("0")
    currency: str = "GBP"
    unit: FinancialUnit = FinancialUnit.MILLION
    evidence: tuple[EvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _money_currency(self.currency))
        for name in (
            "accounts_receivable",
            "inventory",
            "accounts_payable",
            "other_operating_current_assets",
            "other_operating_current_liabilities",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite(value, name))


@dataclass(frozen=True, slots=True)
class WorkingCapitalResult:
    period: FinancialPeriod
    net_working_capital: Decimal | None
    currency: str
    unit: FinancialUnit
    lines: tuple[CalculationLine, ...]
    warnings: tuple[CalculationWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkingCapitalTrend:
    results: tuple[WorkingCapitalResult, ...]
    average: Decimal | None
    median: Decimal | None
    recent_variance_from_average: Decimal | None
    outlier_period_labels: tuple[str, ...]
    warnings: tuple[CalculationWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class NwcPegResult:
    method: NwcPegMethod
    period_labels: tuple[str, ...]
    normalized_nwc: Decimal | None
    current_nwc: Decimal | None
    surplus_or_shortfall: Decimal | None
    currency: str
    unit: FinancialUnit
    warnings: tuple[CalculationWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class NetDebtItem:
    item_id: str
    description: str
    category: NetDebtCategory
    amount: Decimal | None
    currency: str
    unit: FinancialUnit
    as_of_date: date
    status: ClassificationStatus
    rationale: str
    evidence: tuple[EvidenceReference, ...]
    restricted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _required(self.item_id, "item_id"))
        object.__setattr__(self, "description", _required(self.description, "description"))
        object.__setattr__(self, "rationale", _required(self.rationale, "rationale"))
        object.__setattr__(self, "currency", _money_currency(self.currency))
        if self.amount is not None:
            amount = _finite(self.amount, "net debt item amount")
            if amount < 0:
                raise DomainValidationError("net debt item amount must not be negative")
            object.__setattr__(self, "amount", amount)
        if self.status is ClassificationStatus.ACCEPTED and not self.evidence:
            raise DomainValidationError("accepted net debt items require evidence")


@dataclass(frozen=True, slots=True)
class NetDebtBridge:
    items: tuple[NetDebtItem, ...]
    lines: tuple[CalculationLine, ...]
    adjusted_net_debt: Decimal | None
    currency: str
    unit: FinancialUnit
    warnings: tuple[CalculationWarning, ...]


@dataclass(frozen=True, slots=True)
class FinancialFindingOutput:
    finding: DiligenceFinding
    observation_ids: tuple[str, ...]
    calculation_lines: tuple[CalculationLine, ...]
    uncertainty: str | None = None


@dataclass(frozen=True, slots=True)
class FinancialThresholds:
    material_variance_percent: Decimal = Decimal("5")
    customer_concentration_percent: Decimal = Decimal("20")
    forecast_growth_percent: Decimal = Decimal("20")
    margin_change_points: Decimal = Decimal("3")
    repeated_adjustment_count: int = 2
    nwc_deviation_percent: Decimal = Decimal("15")

    def __post_init__(self) -> None:
        for name in (
            "material_variance_percent",
            "customer_concentration_percent",
            "forecast_growth_percent",
            "margin_change_points",
            "nwc_deviation_percent",
        ):
            value = _finite(getattr(self, name), name)
            if value < 0:
                raise DomainValidationError(f"{name} must not be negative")
        if self.repeated_adjustment_count < 2:
            raise DomainValidationError("repeated_adjustment_count must be at least two")
