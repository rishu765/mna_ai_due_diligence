"""Revenue, margin, concentration, and working-capital calculations."""

from __future__ import annotations

from decimal import Decimal
from statistics import median

from ma_due_diligence.financial.models import (
    CalculationLine,
    CalculationWarning,
    CalculationWarningCode,
    CustomerConcentrationResult,
    CustomerRevenue,
    FinancialMetric,
    FinancialObservation,
    FinancialUnit,
    GrowthResult,
    MarginResult,
    NwcPegMethod,
    NwcPegResult,
    WorkingCapitalPeriod,
    WorkingCapitalResult,
    WorkingCapitalTrend,
)
from ma_due_diligence.financial.normalization import normalize_unit, safe_ratio


def calculate_margin(
    numerator: FinancialObservation,
    revenue: FinancialObservation,
    metric: FinancialMetric,
) -> MarginResult:
    if numerator.period.label.casefold() != revenue.period.label.casefold():
        return MarginResult(
            metric,
            revenue.period,
            None,
            (numerator.observation_id, revenue.observation_id),
            (CalculationWarning(CalculationWarningCode.PERIOD_MISMATCH, "Margin periods differ."),),
        )
    if numerator.currency != revenue.currency:
        return MarginResult(
            metric,
            revenue.period,
            None,
            (numerator.observation_id, revenue.observation_id),
            (
                CalculationWarning(
                    CalculationWarningCode.MIXED_CURRENCIES, "Margin currencies differ."
                ),
            ),
        )
    normalized = normalize_unit(numerator, revenue.unit)
    result = safe_ratio(normalized.value, revenue.value)
    warnings: tuple[CalculationWarning, ...] = ()
    if revenue.value == 0:
        warnings = (
            CalculationWarning(CalculationWarningCode.ZERO_DENOMINATOR, "Revenue is zero."),
        )
    elif result is None:
        warnings = (
            CalculationWarning(CalculationWarningCode.MISSING_INPUT, "Margin input is missing."),
        )
    return MarginResult(
        metric,
        revenue.period,
        result,
        (numerator.observation_id, revenue.observation_id),
        warnings,
    )


def revenue_growth(prior: FinancialObservation, current: FinancialObservation) -> GrowthResult:
    if prior.currency != current.currency:
        return GrowthResult(
            FinancialMetric.REVENUE,
            prior.period,
            current.period,
            None,
            (
                CalculationWarning(
                    CalculationWarningCode.MIXED_CURRENCIES, "Revenue currencies differ."
                ),
            ),
            (prior.observation_id, current.observation_id),
        )
    normalized = normalize_unit(current, prior.unit)
    percentage = (
        None
        if prior.value is None or normalized.value is None
        else safe_ratio(normalized.value - prior.value, abs(prior.value))
    )
    warning: tuple[CalculationWarning, ...] = ()
    if prior.value == 0:
        warning = (
            CalculationWarning(CalculationWarningCode.ZERO_DENOMINATOR, "Prior revenue is zero."),
        )
    elif percentage is None:
        warning = (
            CalculationWarning(CalculationWarningCode.MISSING_INPUT, "Revenue value is missing."),
        )
    return GrowthResult(
        FinancialMetric.REVENUE,
        prior.period,
        current.period,
        percentage,
        warning,
        (prior.observation_id, current.observation_id),
    )


def customer_concentration(
    customers: tuple[CustomerRevenue, ...],
    *,
    threshold: Decimal = Decimal("20"),
) -> CustomerConcentrationResult:
    if not customers:
        raise ValueError("customer concentration requires customer rows")
    period = customers[0].period
    compatible = all(
        item.currency == customers[0].currency
        and item.unit is customers[0].unit
        and item.period.label.casefold() == period.label.casefold()
        for item in customers
    )
    if not compatible:
        return CustomerConcentrationResult(
            period,
            None,
            None,
            None,
            None,
            len(customers),
            None,
            (
                CalculationWarning(
                    CalculationWarningCode.PERIOD_MISMATCH, "Customer rows are incompatible."
                ),
            ),
        )
    values = sorted((item.revenue for item in customers), reverse=True)
    total = sum(values, Decimal("0"))
    if total == 0:
        return CustomerConcentrationResult(
            period,
            total,
            None,
            None,
            None,
            len(values),
            None,
            (
                CalculationWarning(
                    CalculationWarningCode.ZERO_DENOMINATOR, "Customer revenue totals zero."
                ),
            ),
        )

    def pct(count: int) -> Decimal:
        return sum(values[:count], Decimal("0")) / total * Decimal("100")

    largest = pct(1)
    return CustomerConcentrationResult(
        period,
        total,
        largest,
        pct(5),
        pct(10),
        len(values),
        largest >= threshold,
    )


def calculate_nwc(item: WorkingCapitalPeriod) -> WorkingCapitalResult:
    missing = any(
        value is None for value in (item.accounts_receivable, item.inventory, item.accounts_payable)
    )
    if missing:
        return WorkingCapitalResult(
            item.period,
            None,
            item.currency,
            item.unit,
            (),
            (
                CalculationWarning(
                    CalculationWarningCode.MISSING_INPUT, "Core NWC component is missing."
                ),
            ),
        )
    assert item.accounts_receivable is not None
    assert item.inventory is not None
    assert item.accounts_payable is not None
    lines = (
        CalculationLine("Accounts receivable", item.accounts_receivable, "+", (), item.evidence),
        CalculationLine("Inventory", item.inventory, "+", (), item.evidence),
        CalculationLine(
            "Other operating current assets",
            item.other_operating_current_assets,
            "+",
            (),
            item.evidence,
        ),
        CalculationLine("Accounts payable", -item.accounts_payable, "-", (), item.evidence),
        CalculationLine(
            "Other operating current liabilities",
            -item.other_operating_current_liabilities,
            "-",
            (),
            item.evidence,
        ),
    )
    value = sum((line.amount for line in lines), Decimal("0"))
    return WorkingCapitalResult(item.period, value, item.currency, item.unit, lines)


def analyze_nwc_trend(periods: tuple[WorkingCapitalPeriod, ...]) -> WorkingCapitalTrend:
    results = tuple(calculate_nwc(item) for item in periods)
    known = [item.net_working_capital for item in results if item.net_working_capital is not None]
    warnings: list[CalculationWarning] = []
    if len(known) < len(results):
        warnings.append(
            CalculationWarning(
                CalculationWarningCode.INCOMPLETE_HISTORY, "NWC history contains missing periods."
            )
        )
    if not known:
        return WorkingCapitalTrend(results, None, None, None, (), tuple(warnings))
    average = sum(known, Decimal("0")) / Decimal(len(known))
    midpoint = Decimal(str(median(known)))
    recent = known[-1]
    variance = recent - average
    outliers = tuple(
        item.period.label
        for item in results
        if item.net_working_capital is not None
        and average != 0
        and abs((item.net_working_capital - average) / average * Decimal("100")) > Decimal("25")
    )
    return WorkingCapitalTrend(results, average, midpoint, variance, outliers, tuple(warnings))


def calculate_nwc_peg(
    trend: WorkingCapitalTrend,
    method: NwcPegMethod,
    *,
    selected_period_label: str | None = None,
) -> NwcPegResult:
    known = tuple(item for item in trend.results if item.net_working_capital is not None)
    if not known:
        return NwcPegResult(
            method,
            (),
            None,
            None,
            None,
            "GBP",
            trend.results[0].unit if trend.results else FinancialUnit.MILLION,
            (
                CalculationWarning(
                    CalculationWarningCode.MISSING_INPUT, "No NWC history is available."
                ),
            ),
        )
    values = [item.net_working_capital for item in known]
    assert all(value is not None for value in values)
    normalized: Decimal | None
    if method is NwcPegMethod.TRAILING_AVERAGE:
        normalized = sum((value for value in values if value is not None), Decimal("0")) / Decimal(
            len(values)
        )
    elif method is NwcPegMethod.MEDIAN:
        normalized = Decimal(str(median(value for value in values if value is not None)))
    else:
        selected = next(
            (item for item in known if item.period.label == selected_period_label), None
        )
        normalized = None if selected is None else selected.net_working_capital
    current = known[-1].net_working_capital
    warnings = (
        ()
        if normalized is not None
        else (
            CalculationWarning(
                CalculationWarningCode.MISSING_INPUT, "Selected seasonal period was unavailable."
            ),
        )
    )
    return NwcPegResult(
        method,
        tuple(item.period.label for item in known),
        normalized,
        current,
        None if normalized is None or current is None else current - normalized,
        known[0].currency,
        known[0].unit,
        warnings,
    )
