# Project 1–4 reuse assessment

“Adapted” means Project 5 implements a bounded-context equivalent; it does not imply a runtime
dependency.

| Project | Relevant implementation inspected | M0 decision | Reason |
| --- | --- | --- | --- |
| Project 1 | Document sources, parsed pages, chunks, metadata, citations, research facts | Adapted through Project 5 models and future interfaces | `VdrDocument` and `EvidenceReference` retain document/page/section/chunk provenance while adding VDR, workstream, table-cell, confidentiality, and engagement semantics. |
| Project 2 | External identifiers, company/candidate identity, discovery evidence | Conceptually reused | `EntityReference` follows the stable-ID plus legal-name pattern. Candidate sourcing is not a direct diligence dependency. |
| Project 3 | `Decimal`, currency validation, periods, metric/unit/basis semantics, serialization | Adapted locally | Project 5 uses exact numeric types, explicit currency and periods, schema-versioned serialization, and unknown-preserving values. |
| Project 4 | Evidence references, extracted observations, verification status, retained conflicts, review decisions, typed graph state | Adapted through Project 5 contracts | Project 5 expands the patterns for diligence and keeps a conceptual state without adding LangGraph. |

## Reused directly

No source-code object is imported directly. There is no stable shared package, and repository
guidance requires two concrete consumers before adding one. Direct imports would couple independent
packages through private modules.

## Adapted through interface

Project 1 document/chunk outputs and Project 4 retrieval results can later be translated by adapters
implementing Project 5 ingestion and evidence-retrieval protocols. The protocols use Project 5
types only.

## Conceptually reused only

Project 2's stable entity identity and Project 4's checkpointed review and graph-state lessons shape
the contracts. There is no integration claim.

## Not reused

Provider implementations, vector indexes, retrieval algorithms, valuation engines, APIs, and
LangGraph runtimes are not reused in M0 because they belong to later milestones or carry the wrong
transaction-specific behavior.
