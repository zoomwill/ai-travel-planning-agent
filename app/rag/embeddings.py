"""Local deterministic embedding interface and offline implementation."""

import hashlib
import math
import re
from typing import Protocol


class EmbeddingModel(Protocol):
    """Small embedding surface accepted by the vector-store adapter."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Convert document text into one vector per item."""

    def embed_query(self, text: str) -> list[float]:
        """Convert one query into a vector in the same coordinate space."""


class DeterministicHashEmbedding:
    """Create normalized hashed bag-of-words vectors without downloads or APIs."""

    def __init__(self, dimensions: int = 128) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be greater than zero")
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed every document independently and in input order."""

        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embed one search query deterministically."""

        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        """Hash normalized tokens into a fixed vector and apply L2 normalization."""

        vector = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.casefold(), flags=re.UNICODE):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:8], byteorder="big") % self.dimensions
            sign = 1.0 if digest[8] % 2 else -1.0
            vector[bucket] += sign

        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]
