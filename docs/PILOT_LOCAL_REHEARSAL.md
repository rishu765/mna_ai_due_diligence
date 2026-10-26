# Local Synthetic Pilot Rehearsal

## Status and boundary

On 26 October 2026, the Step 13 container was exercised locally with the 25-document synthetic VDR.
This was a pre-gate rehearsal, not the formal Step 14 internal pilot: no approved public host, stable
HTTPS URL, independent monitor, or invited-company reviewer was used.

The reviewer journey completed login, deal creation, analysis, findings and financial inspection,
controlled-AI drafting, 14 finding dispositions, five conflict resolutions, report release, and PDF
and Excel downloads. The released state contained 14 findings, 79 report citation instances, 19
review actions, and zero unsupported material conclusions.

## Observations and remediation

### PILOT-OBS-001 — finding evidence was not sufficiently inspectable

The Findings screen exposed source documents but the financial fixture evidence used generic labels,
so the conflicting values, evidence identifiers, and precise locators were not consistently visible.

Remediation:

- the run payload now retains table, row, column, sheet, cell-range, and chunk locators;
- the Findings screen displays evidence ID plus the best available locator; and
- synthetic financial evidence now carries the actual source values and missing-data context.

### PILOT-OBS-002 — local AI draft omitted quantitative detail and one citation

The local controlled-AI template cited only three of four revenue evidence items and generated a
generic rationale without the GBP 92m, GBP 95m, and GBP 100m source values.

Remediation:

- the local provider cites every bounded evidence item; and
- a bounded evidence digest includes source, locator, and excerpt text while remaining subject to the
  existing numerical-claim, citation, token, cost, and prompt-control validators.

The draft is still pending human review and cannot change finance, choose a disposition, or submit a
review.

### PILOT-OBS-003 — supplier expiry was attributed to a customer finding

The commercial analyzer selected the earliest active `contract_expiry` claim without restricting the
document type. This produced a customer-renewal finding from the Orion supplier agreement expiring
31 March 2028 instead of the Apex customer agreement expiring 31 December 2027.

Remediation:

- the commercial retrieval plan now explicitly retrieves customer-contract expiry clauses; and
- customer-renewal analysis accepts expiry claims only from `customer_contract` documents.

A regression test verifies the exact Apex date and source excerpt.

### PILOT-OBS-004 — persisted runs were not discoverable after restart

The pilot database and encrypted LangGraph checkpoint retained the completed run, but the browser
cleared its in-memory run identifier when a deal was reopened. The API required a known run ID and
offered no deal-scoped latest-run lookup, so durable state appeared to be missing after a process or
container restart.

Remediation:

- the pilot database exposes the latest run for a deal using deterministic update-time ordering;
- the run service rehydrates that run from its encrypted LangGraph checkpoint;
- a deal-scoped `GET /pilot/deals/{deal_id}/runs/latest` endpoint returns the restored run or `204`
  when no run exists; and
- the browser restores the latest persisted run whenever a deal workspace is opened.

A restart regression test closes the complete pilot runtime, creates a new runtime over the same
database and checkpoint files, and verifies that the original 14-finding review checkpoint is
returned with the same run ID.

## Verification

The remediation branch passes:

- dependency consistency, Ruff lint, and Ruff format checks;
- strict mypy across 105 source files;
- 156 tests with 86.15% branch-aware coverage; and
- all 14 deterministic evaluation scenarios.

The corrected build still requires a fresh manual local rehearsal after merge. Step 13 remains open
until its live HTTPS, monitoring, backup/restore, and invited-reviewer acceptance criteria pass; only
then can the formal Step 14 pilot begin.
