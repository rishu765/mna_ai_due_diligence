# Step 8 Financial Methodology and Reproducibility

## Purpose

Step 8 makes the financial logic reviewable as a controlled methodology rather than a collection of
opaque outputs. It does not change the frozen V1 arithmetic. It publishes the existing rules,
thresholds, source hierarchy, deal assumptions, signed calculation lines, evidence identifiers, and
reconciliation checks so a finance reviewer can reproduce and challenge the displayed results.

The default methodology is identified as `madd-financial-methodology` version `1.0.0`. Its canonical
policy payload carries a SHA-256 fingerprint. Deal-specific assumptions are displayed separately so
the global methodology fingerprint remains stable.

## Engagement assumptions

Every deal-specific methodology response states:

- reporting currency;
- monetary unit;
- as-of date;
- configured materiality threshold, if any;
- no FX conversion without an explicit approved policy;
- no period conversion without an explicit approved policy;
- full `Decimal` precision for calculations and rounding only for display.

Unknown values remain unknown. A missing input, mixed currency, mixed period, mixed unit, or
unsupported classification produces a warning or blocks the affected calculation rather than being
silently replaced with zero or an assumption.

## Source hierarchy

The default presentation order is:

1. financial statements;
2. general-ledger export;
3. management accounts;
4. board materials;
5. management presentation;
6. sales report;
7. other sources.

Metric-specific overrides can replace this order. Source priority selects the preferred presentation
value only after period and currency compatibility checks. It never deletes a source observation.
Absolute and percentage variances, all inputs, evidence IDs, and the unresolved status remain visible.

## Thresholds

| Policy | Default |
| --- | ---: |
| Material source variance | 5% |
| Customer concentration | 20% |
| Forecast growth | 20% |
| Margin change | 3 percentage points |
| Repeated adjustment | 2 occurrences |
| NWC deviation | 15% |

These defaults are detection and review thresholds, not transaction-specific legal or accounting
materiality. A participating company can configure deal assumptions, but changing the methodology
requires a new version and fingerprint.

## Quality of earnings and EBITDA

Formula:

`reported EBITDA + accepted upward adjustments - accepted downward adjustments = diligence-adjusted EBITDA`

Only evidence-supported, non-duplicate adjustments that pass the disclosed recurrence and
classification rules enter the bridge. Rejected adjustments remain listed. Every accepted line shows
its signed amount, operation, adjustment/fact IDs, and evidence IDs. The UI checks that the signed
line total equals the released adjusted EBITDA.

Reviewer challenges include whether an adjustment is genuinely nonrecurring, whether the amount is
supported, whether it is duplicated elsewhere, and whether a similar category recurs historically.

## Net working capital and peg

Period NWC formula:

`accounts receivable + inventory + other operating current assets - accounts payable - other operating current liabilities`

Every available period exposes the signed lines and a reconciliation check. Missing core balances
produce an unknown result. Historical aggregation requires one currency and one unit.

The default indicative peg uses the trailing average of known compatible NWC periods. The trace
discloses the method, included period labels, normalized NWC, current NWC, and surplus or shortfall.
The result is an analytical indication, not a purchase-agreement definition.

## Adjusted net debt

Formula:

`debt + accepted debt-like items - unrestricted cash - accepted cash-like items = adjusted net debt`

Only accepted, evidenced items enter the bridge. Duplicate IDs are ignored with warnings. Restricted
cash is not treated as available cash. Mixed currencies or units block aggregation. Each signed line
retains the source item and evidence identifiers, and the UI verifies the line total against the
released adjusted net debt.

## Customer concentration

Formula:

`customer revenue / total identified customer revenue × 100`

Only period-, currency-, and unit-aligned customer revenue inputs are aggregated. The calculation
trace exposes each customer input, value, period, evidence IDs, total identified revenue, and largest,
top-five, and top-ten percentages. A reviewer must separately challenge whether identified customer
revenue reconciles to total revenue and whether related customers are grouped consistently.

## Revenue reconciliation

The trace retains every source observation with value, currency, unit, period, actual/forecast status,
reported/adjusted basis, document type, and evidence IDs. It discloses the preferred observation,
absolute variance, percentage variance, status, and selection rationale.

## Application and API

The Financials screen shows:

- methodology version and fingerprint;
- engagement assumptions;
- all policy rules and reviewer challenge questions;
- summary outputs;
- expandable EBITDA, period NWC, NWC-peg, customer-concentration, net-debt, and
  revenue-reconciliation traces.

The deal-scoped methodology endpoint is:

`GET /pilot/deals/{deal_id}/financial-methodology`

The analysis-run payload embeds the exact global methodology payload and calculation trace used for
the displayed fixture results. Authorization is enforced server-side using `deal_read` permission.

## Control boundary and limitations

- This methodology documents the current deterministic V1 fixture engine; it is not an accounting,
  valuation, tax, or legal opinion.
- The real uploaded VDR is still isolated from the synthetic analysis run.
- Company-specific transaction definitions, agreed accounting policies, FX sources, completion
  accounts mechanics, locked-box leakage, and purchase-agreement drafting require explicit later
  configuration and review.
- Step 9 will strengthen editable review actions and immutable decision history around released
  findings and calculations.

## Verification

Automated tests prove that the methodology payload and fingerprint are stable, engagement assumptions
prohibit implicit conversion, unauthorized deals cannot expose policy, and every known EBITDA, NWC,
and net-debt output reconciles to its signed lines. Customer concentration retains its customer-level
inputs, and the complete existing finance and 14-scenario diligence evaluations remain regression
gates.
