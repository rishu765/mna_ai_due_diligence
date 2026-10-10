"""Evidence-backed debt, debt-like, cash, and cash-like bridge calculations."""

from __future__ import annotations

from decimal import Decimal

from ma_due_diligence.financial.models import (
    CalculationLine,
    CalculationWarning,
    CalculationWarningCode,
    ClassificationStatus,
    FinancialUnit,
    NetDebtBridge,
    NetDebtCategory,
    NetDebtItem,
)


def calculate_adjusted_net_debt(items: tuple[NetDebtItem, ...]) -> NetDebtBridge:
    if not items:
        return NetDebtBridge(
            (),
            (),
            None,
            "GBP",
            FinancialUnit.MILLION,
            (
                CalculationWarning(
                    CalculationWarningCode.MISSING_INPUT, "No net debt items were supplied."
                ),
            ),
        )
    currencies = {item.currency for item in items if item.amount is not None}
    units = {item.unit for item in items if item.amount is not None}
    if len(currencies) > 1 or len(units) > 1:
        return NetDebtBridge(
            items,
            (),
            None,
            items[0].currency,
            items[0].unit,
            (
                CalculationWarning(
                    CalculationWarningCode.MIXED_CURRENCIES,
                    "Net debt items have incompatible bases.",
                ),
            ),
        )
    lines: list[CalculationLine] = []
    warnings: list[CalculationWarning] = []
    seen: set[str] = set()
    total = Decimal("0")
    accepted_count = 0
    for item in items:
        if item.item_id in seen:
            warnings.append(
                CalculationWarning(
                    CalculationWarningCode.DUPLICATE_ITEM,
                    f"Duplicate net debt item {item.item_id}.",
                )
            )
            continue
        seen.add(item.item_id)
        if item.status is not ClassificationStatus.ACCEPTED or item.amount is None:
            if item.amount is None:
                warnings.append(
                    CalculationWarning(
                        CalculationWarningCode.MISSING_INPUT, f"{item.description} has no amount."
                    )
                )
            continue
        accepted_count += 1
        subtract = item.category in {NetDebtCategory.CASH, NetDebtCategory.CASH_LIKE}
        if subtract and item.restricted:
            warnings.append(
                CalculationWarning(
                    CalculationWarningCode.UNSUPPORTED_CLASSIFICATION,
                    f"Restricted item {item.description} was not treated as available cash.",
                )
            )
            continue
        signed = -item.amount if subtract else item.amount
        total += signed
        lines.append(
            CalculationLine(
                item.description,
                signed,
                "-" if subtract else "+",
                (item.item_id,),
                item.evidence,
            )
        )
    if accepted_count == 0:
        warnings.append(
            CalculationWarning(
                CalculationWarningCode.MISSING_INPUT, "No accepted net debt items were available."
            )
        )
        adjusted: Decimal | None = None
    else:
        adjusted = total
    return NetDebtBridge(
        items, tuple(lines), adjusted, items[0].currency, items[0].unit, tuple(warnings)
    )
