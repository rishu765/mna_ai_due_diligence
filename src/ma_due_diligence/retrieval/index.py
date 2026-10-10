"""Atomic in-memory semantic and BM25 index isolated by engagement metadata."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from ma_due_diligence.errors import IndexingError
from ma_due_diligence.retrieval.embedding import EmbeddingProvider, lexical_tokens
from ma_due_diligence.retrieval.models import ChannelMatch, RetrievalFilters
from ma_due_diligence.vdr.models import DiligenceChunk


@dataclass(frozen=True, slots=True)
class IndexingReport:
    chunks_received: int
    chunks_indexed: int
    duplicate_chunks: int
    total_chunks: int
    rebuilt: bool
    embedding_provider: str
    embedding_model: str


class InMemoryDiligenceIndex:
    def __init__(self, embedder: EmbeddingProvider) -> None:
        self._embedder = embedder
        self._chunks: dict[str, DiligenceChunk] = {}
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._terms: dict[str, Counter[str]] = {}
        self._lengths: dict[str, int] = {}

    @property
    def count(self) -> int:
        return len(self._chunks)

    def index(self, chunks: tuple[DiligenceChunk, ...], *, rebuild: bool = False) -> IndexingReport:
        base_chunks = {} if rebuild else dict(self._chunks)
        unique: dict[str, DiligenceChunk] = {}
        duplicates = 0
        for chunk in chunks:
            existing = unique.get(chunk.chunk_id) or base_chunks.get(chunk.chunk_id)
            if existing is not None:
                if existing != chunk:
                    raise IndexingError(f"chunk ID {chunk.chunk_id!r} has conflicting content")
                duplicates += 1
                continue
            unique[chunk.chunk_id] = chunk
        pending_vectors: dict[str, tuple[float, ...]] = {}
        pending_terms: dict[str, Counter[str]] = {}
        pending_lengths: dict[str, int] = {}
        for chunk_id, chunk in unique.items():
            vector = self._embedder.embed(chunk.text)
            if len(vector) != self._embedder.dimension:
                raise IndexingError("embedding provider returned wrong dimension")
            terms = lexical_tokens(chunk.text)
            pending_vectors[chunk_id] = vector
            pending_terms[chunk_id] = Counter(terms)
            pending_lengths[chunk_id] = len(terms)
        if rebuild:
            self._chunks.clear()
            self._vectors.clear()
            self._terms.clear()
            self._lengths.clear()
        self._chunks.update(unique)
        self._vectors.update(pending_vectors)
        self._terms.update(pending_terms)
        self._lengths.update(pending_lengths)
        return IndexingReport(
            len(chunks),
            len(unique),
            duplicates,
            self.count,
            rebuild,
            self._embedder.provider_name,
            self._embedder.model_name,
        )

    def semantic_search(self, query: str, filters: RetrievalFilters) -> tuple[ChannelMatch, ...]:
        query_vector = self._embedder.embed(query)
        matches = (
            ChannelMatch(chunk, _cosine(query_vector, self._vectors[chunk_id]))
            for chunk_id, chunk in self._chunks.items()
            if filters.matches(chunk)
        )
        return tuple(sorted(matches, key=lambda item: (-item.score, item.chunk.chunk_id)))

    def lexical_search(self, query: str, filters: RetrievalFilters) -> tuple[ChannelMatch, ...]:
        query_terms = lexical_tokens(query)
        eligible = {
            chunk_id: chunk for chunk_id, chunk in self._chunks.items() if filters.matches(chunk)
        }
        if not eligible:
            return ()
        average_length = sum(self._lengths[chunk_id] for chunk_id in eligible) / len(eligible)
        document_frequency = Counter(
            term for chunk_id in eligible for term in self._terms[chunk_id]
        )
        matches = (
            ChannelMatch(
                chunk,
                _bm25(
                    query_terms,
                    self._terms[chunk_id],
                    self._lengths[chunk_id],
                    average_length,
                    document_frequency,
                    len(eligible),
                ),
            )
            for chunk_id, chunk in eligible.items()
        )
        return tuple(sorted(matches, key=lambda item: (-item.score, item.chunk.chunk_id)))


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _bm25(
    query_terms: list[str],
    term_frequency: Counter[str],
    document_length: int,
    average_length: float,
    document_frequency: Counter[str],
    document_count: int,
) -> float:
    if not query_terms or average_length == 0:
        return 0.0
    score = 0.0
    for term in set(query_terms):
        frequency = term_frequency[term]
        if frequency == 0:
            continue
        inverse_frequency = math.log(
            1 + (document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
        )
        score += (
            inverse_frequency
            * (frequency * 2.5)
            / (frequency + 1.5 * (0.25 + 0.75 * document_length / average_length))
        )
    return score
