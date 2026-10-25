"""Versioned, reviewable financial methodology for the controlled pilot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ma_due_diligence.financial.models import FinancialThresholds
from ma_due_diligence.financial.reconciliation import SourcePriorityPolicy


@dataclass(frozen=True, slots=True)
class MethodologyRule:
    code: str
    title: str
    policy: str
    formula: str | None
    challenge_questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FinancialMethodology:
    methodology_id: str
    version: str
    title: str
    rules: tuple[MethodologyRule, ...]
    thresholds: FinancialThresholds
    source_priority: SourcePriorityPolicy

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "methodology_id": self.methodology_id,
            "version": self.version,
            "title": self.title,
            "source_priority": [item.value for item in self.source_priority.default_order],
            "metric_source_overrides": {
                metric.value: [item.value for item in order]
                for metric, order in sorted(
                    self.source_priority.metric_overrides.items(),
                    key=lambda item: item[0].value,
                )
            },
            "thresholds": {
                "material_variance_percent": str(self.thresholds.material_variance_percent),
                "customer_concentration_percent": str(
                    self.thresholds.customer_concentration_percent
                ),
                "forecast_growth_percent": str(self.thresholds.forecast_growth_percent),
                "margin_change_points": str(self.thresholds.margin_change_points),
                "repeated_adjustment_count": self.thresholds.repeated_adjustment_count,
                "nwc_deviation_percent": str(self.thresholds.nwc_deviation_percent),
            },
            "rules": [
                {
                    "code": rule.code,
                    "title": rule.title,
                    "policy": rule.policy,
                    "formula": rule.formula,
                    "challenge_questions": list(rule.challenge_questions),
                }
                for rule in self.rules
            ],
        }
        payload["fingerprint_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return payload


def default_financial_methodology() -> FinancialMethodology:
    return FinancialMethodology(
        methodology_id="madd-financial-methodology",
        version="1.0.0",
        title="Evidence-first M&A financial diligence methodology",
        thresholds=FinancialThresholds(),
        source_priority=SourcePriorityPolicy(),
        rules=(
            MethodologyRule(
                "BASIS-001",
                "Currency, unit, period, and basis",
                "Monetary scale may be normalized explicitly. Currency, period, actual/forecast, "
                "and reported/adjusted bases are never converted or merged implicitly.",
                None,
                (
                    "Do all inputs use the same currency and period?",
                    "Is each value actual or forecast and reported or adjusted?",
                    "Has any FX or period conversion been separately approved?",
                ),
            ),
            MethodologyRule(
                "SOURCE-001",
                "Source hierarchy and disagreement",
                "The disclosed source hierarchy selects presentation priority only. Every observed "
                "value and material disagreement remains visible.",
                "absolute variance = maximum source value - minimum source value",
                (
                    "Is a higher-authority source complete and period-aligned?",
                    "Can management reconcile the source difference to ledgers?",
                ),
            ),
            MethodologyRule(
                "QOE-001",
                "Quality of earnings adjustments",
                "Only supported, non-duplicate adjustments that pass the disclosed recurrence and "
                "evidence rules enter the diligence bridge.",
                "reported EBITDA + accepted increases - accepted decreases = adjusted EBITDA",
                (
                    "Is the item genuinely nonrecurring?",
                    "Is the amount supported and free of double counting?",
                    "Does the adjustment recur across historical periods?",
                ),
            ),
            MethodologyRule(
                "NWC-001",
                "Net working capital",
                "Core NWC includes trade receivables and inventory, subtracts trade payables, and "
                "includes other operating current balances only when explicitly supplied.",
                "AR + inventory + other operating current assets - AP - other operating current liabilities",
                (
                    "Are all balances operating and on a consistent basis?",
                    "Is the selected peg method representative of seasonality?",
                    "Are missing months or unusual cut-off effects disclosed?",
                ),
            ),
            MethodologyRule(
                "NETDEBT-001",
                "Adjusted net debt",
                "Accepted debt and debt-like items increase net debt. Unrestricted accepted cash "
                "and cash-like items reduce it. Restricted cash is not treated as available cash.",
                "debt + debt-like items - unrestricted cash - accepted cash-like items",
                (
                    "Are debt-like classifications supported by transaction principles?",
                    "Is cash legally and operationally available at closing?",
                    "Have duplicate balances been removed?",
                ),
            ),
            MethodologyRule(
                "CONC-001",
                "Customer concentration",
                "Customer shares are calculated only across period-, currency-, and unit-aligned "
                "customer revenue inputs.",
                "customer revenue / total identified customer revenue × 100",
                (
                    "Does identified customer revenue reconcile to total revenue?",
                    "Are customer groups and related entities consistently aggregated?",
                ),
            ),
            MethodologyRule(
                "UNKNOWN-001",
                "Missing and incompatible data",
                "Unknown values remain unknown. Missing inputs, mixed currencies, mixed periods, "
                "and unsupported classifications block the affected calculation or create a warning.",
                None,
                (
                    "Which missing input prevents reproduction?",
                    "Could an assumption materially change the deal conclusion?",
                ),
            ),
        ),
    )


def engagement_methodology_payload(
    *,
    reporting_currency: str,
    unit: str,
    as_of_date: str,
    materiality_threshold: str | None,
) -> dict[str, object]:
    payload = default_financial_methodology().payload()
    payload["engagement_assumptions"] = {
        "reporting_currency": reporting_currency,
        "unit": unit,
        "as_of_date": as_of_date,
        "materiality_threshold": materiality_threshold,
        "fx_conversion": "none_without_explicit_policy",
        "period_conversion": "none_without_explicit_policy",
        "rounding": "display_only_two_decimals; calculations retain Decimal precision",
    }
    return payload
