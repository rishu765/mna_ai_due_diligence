"""Provider-neutral embeddings plus an offline deterministic implementation."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from typing import Protocol

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_SYNONYMS = {
    "turnover": "revenue",
    "sales": "revenue",
    "borrowings": "debt",
    "loan": "debt",
    "loans": "debt",
    "termination": "terminate",
    "terminated": "terminate",
    "customers": "customer",
    "clients": "customer",
    "adjustments": "adjustment",
    "addback": "adjustment",
    "addbacks": "adjustment",
}


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, text: str) -> tuple[float, ...]: ...


class DeterministicHashEmbedder:
    """Feature-hashing embeddings for reproducible tests and offline demos."""

    def __init__(self, dimension: int = 256) -> None:
        if dimension < 32:
            raise ValueError("embedding dimension must be at least 32")
        self._dimension = dimension

    @property
    def provider_name(self) -> str:
        return "deterministic-local"

    @property
    def model_name(self) -> str:
        return "token-hash-v1"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dimension
        features = lexical_tokens(text)
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return tuple(vector)
        return tuple(value / magnitude for value in vector)


def lexical_tokens(text: str) -> list[str]:
    tokens = [_SYNONYMS.get(token, token) for token in _TOKEN_PATTERN.findall(text.casefold())]
    return list(_with_bigrams(tokens))


def _with_bigrams(tokens: list[str]) -> Iterable[str]:
    yield from tokens
    for left, right in zip(tokens, tokens[1:], strict=False):
        yield f"{left}_{right}"
