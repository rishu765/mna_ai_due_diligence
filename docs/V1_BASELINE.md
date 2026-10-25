# V1 Baseline

This document freezes the verified standalone V1 baseline before pilot-readiness work begins.

## Version identity

- Package version: `1.0.0`
- Baseline commit: `496c7ae9b69ca9f428222e1c44c44b972439d390`
- Baseline Git tag: `v1.0.0`
- Pilot development branch: `pilot-ready`
- Original six-project portfolio repository: out of scope and unchanged

## Verified V1 capabilities

- Offline, evidence-first M&A due-diligence workflow
- PDF, TXT/Markdown, CSV, XLSX, and basic HTML ingestion
- Structure-aware chunking with document and location provenance
- Deterministic semantic, BM25, and hybrid retrieval
- Financial, commercial, legal/contractual, and operational specialists
- Source reconciliation and cross-document conflict detection
- Quality-of-earnings, EBITDA, customer-concentration, working-capital, and net-debt analysis
- Checkpointed LangGraph orchestration with interrupt/resume and human review
- Evidence-linked report generation
- Local FastAPI proof-of-concept interface

## Verified engineering baseline

- Tests: 102 passed
- Ruff lint: passed
- Ruff formatting: passed across 86 files
- Strict mypy: passed across 73 source files
- Final evaluation: 14/14 scenarios passed

## Verified demonstration baseline

### Final workflow

- 25 documents processed
- 4 specialist workstreams completed; 0 failed
- 14 prioritized findings
- 9 review actions
- 12 trace events
- 100% citation coverage on the fixture
- Initial status: `review_required`
- Final status: `completed_with_warnings`

### Retrieval

- 10 documents
- 67 chunks
- 1 duplicate detected
- 1 version relationship detected
- Hit@5: 1.000
- Recall@5: 0.929
- MRR: 0.857
- Source correctness: 0.714
- Metadata-filter correctness: 1.000

### Financial analysis

- Revenue variance: GBP 8.0 million
- Diligence-adjusted EBITDA: GBP 15.0 million
- Gross margin: 36%
- Largest-customer concentration: 42%
- Current net working capital: GBP 12.5 million
- Normalized net working capital: GBP 9.3090909 million
- Adjusted net debt: GBP 20.0 million
- Financial evaluation: 11/11 scenarios passed

## V1 boundaries

V1 is a tested portfolio prototype, not an enterprise production system. It intentionally does not
provide user authentication, multi-tenant deal isolation, production document storage, OCR,
malware scanning, enterprise integrations, or a live LLM. Its process-local API and checkpointing
are suitable for demonstrations and deterministic evaluation only.

All pilot changes must preserve the following design rules:

1. Unknown values remain unknown and never silently become zero.
2. Financial arithmetic remains deterministic and reproducible.
3. AI-generated content remains a candidate until evidence validation and human review.
4. Every material conclusion retains source and derivation lineage.
5. A failed document or specialist is visible and does not silently disappear.
6. The immutable V1 baseline remains recoverable from the `v1.0.0` tag.
