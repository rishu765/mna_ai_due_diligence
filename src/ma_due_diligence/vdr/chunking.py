"""Structure-aware deterministic chunking for diligence documents."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from ma_due_diligence.vdr.models import DiligenceChunk, ParsedElement, ParsedVdrDocument


@dataclass(frozen=True, slots=True)
class DiligenceChunkingConfig:
    max_characters: int = 1800

    def __post_init__(self) -> None:
        if self.max_characters < 200:
            raise ValueError("max_characters must be at least 200")


class DiligenceChunker:
    """Keep clauses and tabular rows intact and retain their source coordinates."""

    def __init__(self, config: DiligenceChunkingConfig | None = None) -> None:
        self.config = config or DiligenceChunkingConfig()

    def chunk(self, parsed: ParsedVdrDocument) -> tuple[DiligenceChunk, ...]:
        chunks: list[DiligenceChunk] = []
        for element in parsed.elements:
            text = self._contextual_text(element)
            for part in self._bounded_parts(text):
                chunks.append(self._make_chunk(parsed, element, len(chunks), part))
        return tuple(chunks)

    @staticmethod
    def _contextual_text(element: ParsedElement) -> str:
        parts = []
        if element.section and element.section.casefold() not in element.text.casefold():
            parts.append(f"Section: {element.section}")
        if element.nearby_context and element.nearby_context != element.text:
            parts.append(f"Headers: {element.nearby_context}")
        parts.append(element.text)
        return "\n".join(parts)

    def _bounded_parts(self, text: str) -> tuple[str, ...]:
        if len(text) <= self.config.max_characters:
            return (text,)
        parts: list[str] = []
        cursor = 0
        while cursor < len(text):
            end = min(cursor + self.config.max_characters, len(text))
            if end < len(text):
                boundary = text.rfind(" ", cursor + 100, end)
                if boundary > cursor:
                    end = boundary
            parts.append(text[cursor:end].strip())
            cursor = end
        return tuple(part for part in parts if part)

    @staticmethod
    def _make_chunk(
        parsed: ParsedVdrDocument,
        element: ParsedElement,
        chunk_index: int,
        text: str,
    ) -> DiligenceChunk:
        document = parsed.document
        content_fingerprint = sha256(text.encode("utf-8")).hexdigest()
        identity = "\0".join((document.document_id, str(chunk_index), element.element_id, text))
        page_numbers = () if element.page_number is None else (element.page_number,)
        page_indexes = () if element.physical_page_index is None else (element.physical_page_index,)
        return DiligenceChunk(
            chunk_id=f"chunk:{sha256(identity.encode('utf-8')).hexdigest()}",
            engagement_id=document.engagement_id,
            document_id=document.document_id,
            chunk_index=chunk_index,
            text=text,
            document_type=document.document_type,
            workstreams=document.workstreams,
            source_path=document.source_reference,
            page_numbers=page_numbers,
            physical_page_indexes=page_indexes,
            section=element.section,
            clause_number=element.clause_number,
            table_id=element.table_id,
            sheet_name=element.sheet_name,
            row_numbers=() if element.row_number is None else (element.row_number,),
            cell_range=element.cell_range,
            period=document.period,
            entity=document.entity,
            content_fingerprint=content_fingerprint,
        )
