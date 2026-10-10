"""Explicit financial normalization without implicit FX or period conversion."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from ma_due_diligence.domain import FinancialPeriod, PeriodKind
from ma_due_diligence.errors import DomainValidationError
from ma_due_diligence.financial.models import FinancialObservation, FinancialUnit

_FACTORS = {
    FinancialUnit.UNITS: Decimal("1"),
    FinancialUnit.THOUSAND: Decimal("1000"),
    FinancialUnit.MILLION: Decimal("1000000"),
    FinancialUnit.BILLION: Decimal("1000000000"),
}


def normalize_unit(
    observation: FinancialObservation, target_unit: FinancialUnit
) -> FinancialObservation:
    """Convert monetary scale only; currencies and periods are never changed."""

    if observation.unit is FinancialUnit.PERCENT or target_unit is FinancialUnit.PERCENT:
        if observation.unit is not target_unit:
            raise DomainValidationError("percent and monetary units are not interchangeable")
        return observation
    if observation.value is None:
        return replace(observation, unit=target_unit)
    normalized = observation.value * _FACTORS[observation.unit] / _FACTORS[target_unit]
    return replace(observation, value=normalized, unit=target_unit)


def convert_value(value: Decimal, source: FinancialUnit, target: FinancialUnit) -> Decimal:
    """Convert a monetary value between explicit scales."""

    if source is FinancialUnit.PERCENT or target is FinancialUnit.PERCENT:
        raise DomainValidationError("percent and monetary units are not interchangeable")
    return value * _FACTORS[source] / _FACTORS[target]


def require_compatible(
    observations: tuple[FinancialObservation, ...], target_unit: FinancialUnit
) -> tuple[FinancialObservation, ...]:
    if not observations:
        return ()
    currencies = {item.currency for item in observations if item.value is not None}
    if len(currencies) > 1:
        raise DomainValidationError("currency conversion requires an explicit FX policy")
    labels = {item.period.label.casefold() for item in observations}
    if len(labels) > 1:
        raise DomainValidationError("period conversion requires an explicit period policy")
    return tuple(normalize_unit(item, target_unit) for item in observations)


def parse_period(label: str) -> FinancialPeriod:
    """Parse common financial labels without converting FY, LTM, or monthly bases."""

    compact = "".join(label.upper().split())
    match = re.fullmatch(r"FY(\d{4})[AE]?", compact)
    if match:
        year = int(match.group(1))
        return FinancialPeriod(
            PeriodKind.FISCAL_YEAR,
            compact,
            date(year, 1, 1),
            date(year, 12, 31),
        )
    match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", compact)
    if match:
        year, month = map(int, match.groups())
        next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        return FinancialPeriod(
            PeriodKind.MONTH,
            compact,
            date(year, month, 1),
            date.fromordinal(next_month.toordinal() - 1),
        )
    if compact.startswith("LTM"):
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", compact)
        if match is None:
            raise DomainValidationError("LTM period requires an end date")
        end = date(*map(int, match.groups()))
        start = end - timedelta(days=364)
        return FinancialPeriod(PeriodKind.LTM, compact, start, end)
    raise DomainValidationError(f"unsupported financial period: {label}")


def safe_ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * Decimal("100")
