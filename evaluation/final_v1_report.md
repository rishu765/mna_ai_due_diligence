# Project 5 Final V1 Evaluation

Run date: 2026-10-10  
Result: **14/14 scenarios passed**

## Subsystem Results

| Subsystem | Metric | Result | Representative failure behavior |
| --- | --- | --- | --- |
| VDR ingestion | Final fixture documents | 25 ingested | Unsupported/duplicate inputs become warnings; usable corpus continues |
| Retrieval | Hit@5 / Recall@5 / MRR | 1.000 / 0.929 / 0.857 | Empty/weak/single-source/parse-failure signals are structured |
| Retrieval | Source / metadata correctness | 0.714 / 1.000 | Filters remain engagement scoped |
| Financial diligence | Category checks | 11/11 passed | Missing values, conflicts, mixed bases, and zero denominators return warnings |
| Specialist analysis | Category checks | 10/10 passed | One specialist exception is isolated and reported |
| Contradiction handling | Final fixture conflicts | 5 retained | Period mismatches and superseded versions avoid false conflict resolution |
| Human review | Pause/resume and audit checks | Passed | Invalid subjects/actions fail with a structured code |
| Report | Citation/numeric/limitation checks | Passed | Provider failure retries once, then fails with `report_generation_failed` |
| Graph | End-to-end terminal state | `completed_with_warnings` | Invalid input and waiting-for-information terminate explicitly |

| ID | Dimension | Scenario | Evidence | Result |
| --- | --- | --- | --- | --- |
| E01 | Ingestion quality | Fixture VDR ingests a broad corpus | 25 documents | Pass |
| E02 | Ingestion quality | Malformed/duplicate items remain visible | 5 warnings | Pass |
| E03 | Retrieval relevance | Core query returns multi-document evidence | 20 results | Pass |
| E04 | Evidence accuracy | Report citations are a subset of finding evidence | 22 citations | Pass |
| E05 | Financial calculation | EBITDA bridge reconciles deterministically | Adjusted EBITDA 15 | Pass |
| E06 | Financial calculation | Customer concentration is quantified | Largest customer 42.00% | Pass |
| E07 | Finding detection | Specialists produce structured findings | 14 findings | Pass |
| E08 | Finding detection | Compound customer risk is created | Compound finding present | Pass |
| E09 | Contradiction detection | Cross-document conflicts are retained | 5 conflicts | Pass |
| E10 | Contradiction detection | Superseded versions are distinguished | 1 superseded claim | Pass |
| E11 | Human review | Workflow pauses before report generation | `review_required` | Pass |
| E12 | Human review | Decisions preserve audit actions | 9 actions | Pass |
| E13 | Report consistency | Report values match deterministic M3 outputs | Consistency true | Pass |
| E14 | End to end | Run completes with report and no fatal error | `completed_with_warnings` | Pass |

## Interpretation

This evaluation is a deterministic regression suite over a small fictitious diligence case. It
demonstrates that the components are wired correctly and preserve evidence through the final
workflow. It does not estimate production accuracy across real VDRs, scanned documents, unusual
accounting policies, legal jurisdictions, or adversarial content.

## Reproduce

From `05_ai_due_diligence/` run:

```powershell
& .\.venv\Scripts\python.exe -m ma_due_diligence.evaluation_final
```
