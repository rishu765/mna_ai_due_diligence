# Pilot-Readiness Implementation Plan

This sequence is the locked implementation order. A later stage does not start implicitly; each
stage must meet its exit criteria and preserve the V1 evidence and review guarantees.

## 1. Freeze V1

- Tag and record the verified baseline.
- Develop on `pilot-ready` only.
- Keep the original six-project repository unchanged.

Exit: V1 is recoverable and its verified metrics are documented.

## 2. Lock pilot scope and acceptance criteria

- Define users, permitted data, workflow, human-control policy, success measures, and exclusions.

Exit: `PILOT_SCOPE.md` is reviewable by a participating company.

## 3. Design the user journey and wireframes

- Map login, deal creation, upload, processing, findings, evidence, review, and export screens.
- Validate terminology with finance users before frontend implementation.

Exit: every required pilot action has an approved screen and state transition.

## 4. Add database and secure document storage

- Persist users, deals, documents, runs, findings, reviews, audit events, and reports.
- Add protected object storage and a persistent retrieval index.

Exit: state survives restart and every object is scoped to a deal.

## 5. Implement authentication and deal isolation

- Add invited users, roles, sessions, authorization checks, and tenant/deal boundaries.

Exit: automated negative tests prove unauthorized access is rejected.

## 6. Build the minimum UI

- Build the browser workflow defined in Stage 3.
- Keep the existing FastAPI service as the backend boundary.

Exit: a finance reviewer completes the journey without command-line or API assistance.

## 7. Strengthen document processing

- Add OCR, upload validation, malware scanning, better table extraction, batch status, and
  recoverable per-document failures according to pilot needs.

Exit: the agreed representative VDR produces a complete and transparent ingestion report.

## 8. Formalize financial methodologies

- Document calculation policies, source hierarchy, materiality, units, periods, assumptions, and
  missing-data behavior.

Exit: a finance reviewer can independently reproduce and challenge every released calculation.

## 9. Connect review actions and audit history

- Persist approval, rejection, edit, severity, comment, assignment, and information-request events.

Exit: every released finding has a complete immutable decision history.

## 10. Add report and Excel exports

- Produce professional report, findings-register, and financial-schedule outputs.

Exit: exported values, citations, review status, and limitations match application state.

## 11. Add controlled AI features where valuable

- Introduce optional evidence-bound interpretation or drafting behind validation, citation checks,
  provider policy, cost limits, and human approval.

Exit: AI output cannot bypass deterministic finance, evidence requirements, or review.

## 12. Expand security and testing

- Cover authentication, authorization, uploads, persistence, recovery, prompt injection, backups,
  performance, browsers, and end-to-end workflows.

Exit: all pilot gates pass and outstanding risks are explicitly accepted or corrected.

## 13. Deploy the pilot environment

- Provide HTTPS, isolated environments, secure secrets, health monitoring, backup, rollback, and
  operator documentation.

Exit: invited reviewers can reliably access a stable pilot URL.

## 14. Run an internal synthetic-data pilot

- Exercise the complete workflow with representative safe data and observe actual users.

Exit: no unresolved critical defects and a documented internal evaluation report.

## 15. Fix observed issues

- Prioritize by confidentiality, correctness, auditability, workflow blockage, and usability.

Exit: all external-pilot blockers are closed or explicitly excluded from scope.

## 16. Begin a controlled external company pilot

- Obtain authorization, onboard users, enforce the agreed data policy, support the exercise, and
  record quantitative and qualitative results.

Exit: the company completes the agreed evaluation and feedback process.

## 17. Collect evidence and decide the product roadmap

- Compare results with success criteria and choose a broader pilot, corrective repeat, narrower
  product, or stop decision.

Exit: the next investment decision is supported by pilot evidence rather than assumptions.

## Cross-stage quality gates

At every implementation milestone:

1. Run Ruff lint and formatting checks.
2. Run strict mypy.
3. Run the full pytest suite.
4. Run relevant evaluation and demonstration flows.
5. Verify no secrets or pilot documents are tracked.
6. Update architecture, threat, operations, and user documentation when behavior changes.
7. Record significant design decisions and known limitations.
