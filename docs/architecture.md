# M0 architecture decisions

## Foundation boundary

M0 defines contracts from engagement and documents through evidence, facts, findings, financial
candidates, human decisions, and future report sections. It contains no production ingestion,
retrieval, extraction, calculation, orchestration, API, or report-generation behavior.

```text
engagement/document -> evidence -> fact -> finding/adjustment/conflict -> review/report contract
```

Evidence references documents by ID. Facts own evidence references. Findings normally own fact IDs
and may retain direct evidence. `ProvenanceChain` supplies an auditable flattened index for later
persistence and report assembly.

## Model organization

- `domain.py`: frozen domain values and validation;
- `contracts.py`: minimal future provider and specialist protocols;
- `workflow.py`: conceptual future LangGraph state, without a graph dependency;
- `serialization.py`: schema-versioned deterministic JSON round trips;
- `fixtures.py`: typed synthetic case for tests and later milestones.

## Conflicts and authority

`FactConflict` retains every observation. Open conflicts cannot carry a preferred fact or resolution
metadata. Resolved conflicts retain a rationale and human-review action; a resolved preferred value
must point to an original observation. Source priority cannot silently erase disagreement.

## Severity and materiality

Severity expresses seriousness. Materiality is separate and may contain a qualitative band, amount,
percentage with benchmark, threshold, and rationale. Neither is calculated in M0.

## Financial values

Money uses `Decimal` and a three-letter currency code. Adjustment amounts are nonnegative with an
explicit direction. Periods preserve type, label, and optional dates. M0 stores candidates but does
not calculate results.

## Future boundaries

The VDR/RAG layer implements `DocumentIngestionProvider`, `DocumentClassifier`,
`EvidenceRetriever`, and `TableExtractionAdapter` boundaries. M4/5 replaces the early placeholder
analyzer contracts with concrete, provider-neutral `SpecialistAnalyzer`, `SpecialistContext`,
`SpecialistResult`, and `CrossDocumentInvestigator` contracts in the `specialists` package. These
contracts consume Project 5 types and contain no provider SDK types.

## Future graph state

`DiligenceGraphState` anticipates engagement, documents, classifications, evidence, facts,
conflicts, findings, adjustments, balance-sheet items, missing information, questions, decisions,
report sections, warnings, errors, summary, and run status. It is a `TypedDict`, not a runtime graph.

## Non-goals

M0 does not provide VDR ingestion, PDF/table extraction, embeddings, vector or hybrid retrieval,
RAG, live LLM extraction, QoE or normalized EBITDA calculations, a working-capital peg, net-debt
computation, concentration or clause extraction, specialist agents, cross-document AI investigation,
LangGraph execution, interrupt/resume, API, frontend, or final report generation.
