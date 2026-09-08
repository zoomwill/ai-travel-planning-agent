"""Local deterministic embedding interface and offline implementation."""

import hashlib
import math
import re
from typing import Protocol, cast

import numpy as np


class EmbeddingModel(Protocol):
    """Small embedding surface accepted by the vector-store adapter."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Convert document text into one vector per item."""

    def embed_query(self, text: str) -> list[float]:
        """Convert one query into a vector in the same coordinate space."""


EmbeddingBackend = EmbeddingModel


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


class SentenceTransformerModel(Protocol):
    """Public SentenceTransformer methods used behind an injectable boundary."""

    def encode_document(self, sentences: list[str], **kwargs: object) -> object:
        """Encode passages for retrieval."""

    def encode_query(self, sentences: str, **kwargs: object) -> object:
        """Encode one retrieval query."""

    def encode(self, sentences: str | list[str], **kwargs: object) -> object:
        """Public fallback for models without prompt-aware methods."""

    def get_embedding_dimension(self) -> int | None:
        """Return the model output dimension through Sentence Transformers 5.7+."""


class SentenceTransformerEmbeddingBackend:
    """Local semantic embedding adapter loaded explicitly, never during import."""

    def __init__(
        self,
        model: SentenceTransformerModel,
        *,
        normalize_embeddings: bool,
    ) -> None:
        self._model = model
        self._normalize_embeddings = normalize_embeddings
        get_dimension = getattr(model, "get_embedding_dimension", None)
        if callable(get_dimension):
            dimension = get_dimension()
        else:
            legacy_get_dimension = getattr(model, "get_sentence_embedding_dimension", None)
            if not callable(legacy_get_dimension):
                raise ValueError("Sentence Transformer does not expose an embedding dimension")
            dimension = legacy_get_dimension()
        if dimension is None or dimension <= 0:
            raise ValueError("Sentence Transformer did not report a valid embedding dimension")
        self.dimensions = dimension

    @classmethod
    def load(
        cls,
        model_name: str,
        *,
        device: str,
        normalize_embeddings: bool,
        local_files_only: bool,
        revision: str | None = None,
    ) -> "SentenceTransformerEmbeddingBackend":
        """Load one public SentenceTransformer model on an explicit code path."""

        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            model_name,
            device=device,
            local_files_only=local_files_only,
            revision=revision,
        )
        return cls(
            cast(SentenceTransformerModel, model),
            normalize_embeddings=normalize_embeddings,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Encode documents through the retrieval-specific public method."""

        if not texts:
            return []
        method = getattr(self._model, "encode_document", None)
        if callable(method):
            result = method(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize_embeddings,
                show_progress_bar=False,
            )
        else:
            result = self._model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize_embeddings,
                show_progress_bar=False,
            )
        vectors = np.asarray(result, dtype=np.float32)
        self._validate_shape(vectors, expected_count=len(texts))
        return cast(list[list[float]], vectors.tolist())

    def embed_query(self, text: str) -> list[float]:
        """Encode a query through the retrieval-specific public method."""

        method = getattr(self._model, "encode_query", None)
        if callable(method):
            result = method(
                text,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize_embeddings,
                show_progress_bar=False,
            )
        else:
            result = self._model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize_embeddings,
                show_progress_bar=False,
            )
        vector = np.asarray(result, dtype=np.float32)
        if vector.ndim != 1 or vector.shape[0] != self.dimensions:
            raise ValueError("query embedding has the wrong dimension")
        return cast(list[float], vector.tolist())

    def _validate_shape(
        self,
        vectors: np.ndarray[tuple[int, ...], np.dtype[np.float32]],
        *,
        expected_count: int,
    ) -> None:
        """Require one same-dimension vector per input document."""

        if vectors.ndim != 2 or vectors.shape != (expected_count, self.dimensions):
            raise ValueError("document embeddings have the wrong shape")


DeterministicHashEmbeddingBackend = DeterministicHashEmbedding
