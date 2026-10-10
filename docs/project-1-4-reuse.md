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

## M1/2 implementation update

Project 1's normalization, page/index provenance, chunk identity, embedding protocol, and semantic
retrieval shapes were adapted into Project 5's VDR context. Project 4's HTML/text ingestion,
deterministic embeddings, BM25, weighted hybrid fusion, metadata filters, atomic index update, and
warning patterns were adapted. No direct Project 1–4 import was added because their packages remain
independent and repository instructions prohibit private implementation coupling.

Project 5 adds diligence-specific CSV/XLSX provenance, primary/secondary workstreams, engagement
isolation, document versions, cross-document grouping, and bounded context construction. LangChain
was inspected as an option and was not used because it adds no necessary behavior here.

## M3 implementation update

Project 3's exact `Decimal` arithmetic, explicit units, ISO-style currencies, period labels,
actual/estimate status, reported/adjusted basis, safe ratio behavior, and calculation traces were
adapted locally behind Project 5 financial models. No valuation assumptions or private Project 3
module imports were added.

Project 4's source hierarchy, retained conflicting observations, explicit verification status,
evidence lineage, and review-ready ambiguity were adapted for financial reconciliation and
candidate findings. M3 does not import Project 4 internals or add its LangGraph runtime.

## M4/5 implementation update

Project 4's provider protocols, immutable observation comparisons, retained open conflicts,
source-priority review candidates, grounded explanation validation, and failure-as-data patterns
were adapted locally. Project 5 adds diligence workstream retrieval plans, typed claims, period and
revision compatibility, contributing-agent attribution, finding consolidation, lightweight
relationships, compound risks, information requests, and investigation traces.

No Project 4 source module is imported. Its transaction-specific verification contracts and
LangGraph runtime were not reused because they have a different bounded context and M6/7 owns the
Project 5 graph. LangChain was not used because the existing typed services provide the required
structured boundaries without a new dependency.
