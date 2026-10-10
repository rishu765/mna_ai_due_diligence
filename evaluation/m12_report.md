# M1/2 offline retrieval baseline

- Dataset: `northstar-vdr-m12`
- Cases: 7
- K: 5

| Metric | Result |
| --- | ---: |
| Hit@5 | 1.000 |
| Recall@5 | 0.929 |
| Mean reciprocal rank | 0.857 |
| Top-source correctness | 0.714 |
| Metadata-filter correctness | 1.000 |
| Narrative Hit@5 | 1.000 |
| Table Hit@5 | 1.000 |

This synthetic baseline is a deterministic regression check. It is too small and curated to support
claims about production retrieval quality.
