"""Bounded, citation-preserving context construction for later analysis."""

from __future__ import annotations

from ma_due_diligence.retrieval.models import RagContext, RetrievalFilters
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever


class RagContextBuilder:
    def __init__(self, retriever: HybridDiligenceRetriever, *, max_characters: int = 6000) -> None:
        if max_characters < 200:
            raise ValueError("context budget must be at least 200 characters")
        self._retriever = retriever
        self._max_characters = max_characters

    def build(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        top_k: int = 8,
    ) -> RagContext:
        response = self._retriever.retrieve(query, filters=filters, top_k=top_k)
        if not response.results:
            return RagContext(query, None, (), (), response.warnings, False)
        blocks: list[str] = []
        results = []
        evidence = []
        used = 0
        truncated = False
        for result in response.results:
            location = _location(result.evidence)
            block = f"[{len(blocks) + 1}] {result.document_id}{location}\n{result.text}"
            additional = len(block) + (2 if blocks else 0)
            if used + additional > self._max_characters:
                truncated = True
                continue
            blocks.append(block)
            results.append(result)
            evidence.append(result.evidence)
            used += additional
        return RagContext(
            query,
            "\n\n".join(blocks) or None,
            tuple(evidence),
            tuple(results),
            response.warnings,
            truncated,
        )


def _location(evidence: object) -> str:
    parts = []
    page_numbers = getattr(evidence, "page_numbers", ())
    sheet = getattr(evidence, "sheet_name", None)
    cell_range = getattr(evidence, "cell_range", None)
    section = getattr(evidence, "section", None)
    if page_numbers:
        parts.append("page " + ",".join(map(str, page_numbers)))
    if section:
        parts.append(str(section))
    if sheet:
        parts.append(f"sheet {sheet}")
    if cell_range:
        parts.append(str(cell_range))
    return " — " + "; ".join(parts) if parts else ""
