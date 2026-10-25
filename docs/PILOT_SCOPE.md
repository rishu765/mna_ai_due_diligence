# Controlled Pilot Scope

## Purpose

The pilot will determine whether the V1 evidence-first due-diligence workflow is useful,
trustworthy, and operationally understandable to professional M&A reviewers. It is an evaluation
of decision support, not authorization for autonomous investment decisions or unrestricted use on
live confidential transactions.

## Initial pilot profile

The initial build targets one invited company, one controlled deal workspace at a time, and a
small group of authorized reviewers. The preferred reviewers are transaction-services, corporate-
development, private-equity, investment-banking, or related M&A professionals.

Until a participating company formally authorizes confidential data processing, the pilot will use
synthetic, public, or properly anonymized documents only.

## In-scope user journey

1. An invited user signs in.
2. The user creates a deal workspace and records target, buyer, scope, currency, as-of date, and
   materiality assumptions.
3. The user uploads permitted VDR documents.
4. The system reports accepted, duplicated, unsupported, and failed documents.
5. The user starts the diligence workflow and can see processing status.
6. The system presents financial, commercial, legal/contractual, and operational findings.
7. The reviewer opens every material finding beside its supporting evidence.
8. The reviewer approves, rejects, edits, comments on, or requests more evidence for a finding.
9. The system exposes conflicts, missing information, calculations, assumptions, and limitations.
10. The reviewer exports a reviewed diligence report and findings register.

## In-scope capabilities

- Secure invited-user access
- Deal-level workspace and data separation
- Batch VDR upload and processing-status reporting
- Persistent document, workflow, finding, review, and audit state
- Evidence retrieval with source and page/sheet/range provenance
- Four existing specialist workstreams
- Deterministic QoE, EBITDA, revenue, customer-concentration, NWC, and net-debt analysis
- Visible document failures, evidence gaps, contradictions, and version relationships
- Human review with recorded identity, rationale, timestamp, prior state, and resulting state
- Evidence-linked report preview
- PDF/Word report and Excel findings/financial-schedule export, subject to implementation validation
- Administrative monitoring sufficient for a controlled pilot

## Explicitly out of scope for the first pilot

- Autonomous deal approval, rejection, valuation, or investment recommendation
- Unsupervised release of AI-generated conclusions
- Broad public self-service access
- Mobile applications
- Automated billing
- Full enterprise single sign-on
- Every VDR, CRM, messaging, and productivity-suite integration
- Every jurisdiction, accounting framework, tax regime, and diligence workstream
- Production claims based only on the existing synthetic fixture benchmark

## Human-control policy

- Material conclusions require human review before final-report inclusion.
- Reviewers can inspect evidence and deterministic derivations.
- Unsupported or materially ambiguous conclusions must abstain or remain flagged.
- Reviewer overrides require a rationale and are retained in the audit history.
- The product assists professional judgment; it does not replace it.

## Data-handling constraints

- No customer documents, secrets, generated indexes, or raw pilot outputs may be committed to Git.
- Confidential data may be used only after written authorization and an agreed retention policy.
- Each deal must be isolated from every other deal.
- Logs must exclude document contents, credentials, and sensitive extracted facts.
- Any external AI provider must be approved for the pilot and its retention/training terms recorded.
- A deletion procedure must cover documents, indexes, derived artifacts, reports, and backups.

## Pilot success criteria

The pilot is successful only when the agreed evaluation corpus and reviewer exercise satisfy all
mandatory criteria below.

| Area | Mandatory criterion |
| --- | --- |
| Evidence | 100% of released material findings include inspectable supporting evidence. |
| Citations | At least 95% citation correctness on the agreed pilot benchmark. |
| Calculations | 100% of released financial calculations are reproducible from displayed inputs, formula, units, period, currency, and sources. |
| Unsupported claims | Zero unsupported material conclusions are released as established facts. |
| Abstention | Insufficient evidence produces an explicit abstention, warning, or information request. |
| Isolation | Users cannot access deals or documents for which they lack permission. |
| Failures | Failed, unsupported, duplicated, and skipped documents are visible to the user. |
| Review | Every material finding has a recorded human disposition before final release. |
| Reliability | The agreed VDR completes without unrecoverable workflow-state loss. |
| Usability | Reviewers can complete the defined journey without command-line or API assistance. |
| Utility | Participating reviewers identify concrete time savings or decision-support value. |
| Auditability | A reviewer can reconstruct how a released conclusion was produced and changed. |

Baseline metrics are not production claims. Final thresholds may be tightened after the pilot corpus
and participating company's risk tolerance are known.

## Evaluation outputs

- Technical test and security results
- Retrieval, citation, calculation, abstention, and material-risk metrics
- Reviewer decisions and qualitative feedback
- Processing time and failure summary
- Known limitations and incidents
- Recommended fixes and product-roadmap decision

## Exit decision

At the end of the controlled pilot, the product owner and participating reviewers will choose one
of three outcomes:

1. Proceed to a second, broader pilot.
2. Repeat the controlled pilot after specified corrective work.
3. Stop or narrow development because the evidence does not justify further investment.
