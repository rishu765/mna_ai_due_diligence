# VDR intelligence and RAG

## Scope

M1/2 implements local ingestion through evidence retrieval. It produces source-grounded evidence
and bounded context, not diligence conclusions. QoE, specialist analysis, conflict resolution,
LangGraph, final review, reports, API, and frontend remain outside this milestone.

## Pipeline

```mermaid
flowchart LR
    A[Folder / file list / manifest] --> B[Checksum and duplicate detection]
    B --> C[Format parser]
    C --> D[Rule-based classification]
    D --> E[Structure-aware chunks]
    E --> F[Atomic semantic + BM25 index]
    F --> G[Metadata-filtered hybrid retrieval]
    G --> H[Grouped evidence / bounded RAG context]
```

Failures are document-local. A corrupt PDF, empty file, malformed CSV, unreadable workbook, or
unsupported format appears in `VdrCorpus.issues`; usable documents continue through the pipeline.

## Formats and structure

| Format | Preserved structure | Known limitation |
| --- | --- | --- |
| PDF | canonical page, zero-based physical index, headings/paragraphs, table-like lines | no OCR or geometric table reconstruction |
| TXT/Markdown | headings, paragraphs, numbered contract clauses | structure depends on source line/paragraph conventions |
| CSV | table ID, row, A1 range, header context | one logical table per file |
| XLSX | workbook file, sheet, row, A1 range, header context | values only; no formula evaluation or layout engine |
| HTML | headings, paragraphs, table rows | basic HTML only; no browser rendering |

Normalization uses Unicode NFC, canonical line endings, and removal of non-text control characters.
It preserves spaces, line structure, punctuation, currency signs, negatives, dates, and numbers.

## Classification

Deterministic rules inspect a bounded filename/title/content sample. Each decision retains rationale,
an ordered workstream list, a primary workstream, and ambiguity state. Manifests may override
classification. An optional future LLM classifier can implement the same Project 5 boundary, but
no LLM is called in M1/2.

## Chunking

Each parsed structural element remains intact unless it exceeds the configured character bound.
Contract clauses carry clause number and section. Financial/tabular rows carry header context,
period, source coordinates, and table/sheet identity. This avoids separating a numeric value from
its header or a clause body from its number.

## Index and retrieval

The in-memory index stores chunks, normalized vectors, token frequencies, and document lengths.
`rebuild=True` clears the old index only after every replacement vector and token record has been
prepared successfully. Duplicate chunk IDs are idempotent; conflicting content under one ID fails.

The test/demo embedding is deterministic token feature hashing with a small disclosed synonym map.
Production embeddings can replace it behind `EmbeddingProvider`. BM25 provides exact phrase and
keyword sensitivity. Hybrid score is:

```text
0.55 * max(0, cosine similarity) + 0.45 * (BM25 / maximum BM25 for the query)
```

Scores rank evidence; they are not confidence percentages.

## Filters and cross-document evidence

Filters cover engagement, document, type, workstream, period, entity, page, and sheet. All searches
require an engagement ID, preventing cross-engagement leakage. `retrieve_grouped` groups ranked
chunks by document and leaves disagreements unresolved.

`EvidenceReference` carries document, page, section, table, row, chunk, sheet, cell range, source
text, period, and retrieval context. The lineage is therefore:

```text
retrieval result -> evidence reference -> chunk -> structured element -> VDR document/source file
```

## Quality signals

Warnings expose no evidence, weak scores, single-source support, differing values across documents,
stale-period or wrong-workstream filters, near-duplicate evidence, and parse failures elsewhere in
the corpus. They do not resolve conflicts or invent missing facts.

## RAG context

The context builder calls hybrid retrieval, retains source labels and evidence objects, removes
identical chunk content, and respects a fixed character budget. It returns `text=None` with warnings
when support is insufficient. M1/2 deliberately omits answer generation.

## Project 1 reuse

Inspected and adapted: conservative source normalization, canonical/physical page semantics,
content-addressed identity, provenance-complete chunks, embedding protocols, vector validation, and
semantic retrieval orchestration. Direct imports were rejected because Project 1 is an independently
packaged application and its private modules are not a shared stable API.

## Project 4 reuse

Inspected and adapted: text/HTML parsing boundaries, deterministic local embeddings, in-memory BM25,
weighted hybrid score fusion, metadata filters, atomic indexing, and explicit retrieval warnings.
Transaction-specific source types and deal identity were not reused.

## LangChain

LangChain is not used. The milestone needs small typed parsers, deterministic indexes, and one
retrieval pipeline; adding framework wrappers would not improve interoperability or behavior.

## Evaluation

The checked-in dataset contains seven queries with expected sources and selected metadata filters.
Metrics are Hit@K, Recall@K, MRR, top-source correctness, and metadata-filter correctness, with
separate narrative and table Hit@K. At K=5 the current fixture produces:

| Metric | Result |
| --- | ---: |
| Hit@5 | 1.000 |
| Recall@5 | 0.929 |
| MRR | 0.857 |
| Top-source correctness | 0.714 |
| Metadata-filter correctness | 1.000 |
| Narrative Hit@5 | 1.000 |
| Table Hit@5 | 1.000 |

The dataset is synthetic and small. Results are regression indicators, not evidence of production
accuracy or readiness.

## Limitations

- no OCR, image extraction, scanned-document support, or perfect PDF table reconstruction;
- no legacy `.xls`, macro execution, formula calculation, or spreadsheet formatting analysis;
- no persistent/vector database or incremental disk index;
- deterministic local embeddings are suitable for tests, not production semantics;
- phrase rules can leave ambiguous files as `OTHER`;
- differing values are signaled but never resolved;
- no generated Q&A, calculations, specialist conclusions, orchestration, API, or report.
