"""Chroma-backed storage for deterministic travel-knowledge vectors."""

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from functools import partial
from typing import Final, Protocol, TypeVar, cast

import chromadb
from langchain_core.documents import Document

from app.core.config import Settings
from app.rag.embeddings import DeterministicHashEmbedding, EmbeddingModel

TRAVEL_KNOWLEDGE_COLLECTION: Final = "travel_knowledge"
MetadataValue = str | int | float | bool
T = TypeVar("T")


class VectorStoreError(RuntimeError):
    """Describe a safe Chroma operation failure without exposing internals."""


class ChromaCollection(Protocol):
    """Small synchronous collection surface used by this adapter and its tests."""

    def count(self) -> int:
        """Return the number of indexed records."""

    def upsert(
        self,
        *,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, MetadataValue]],
        documents: list[str],
    ) -> None:
        """Create or replace records with deterministic identifiers."""

    def query(
        self,
        *,
        query_embeddings: list[list[float]],
        n_results: int,
        include: list[str],
    ) -> Mapping[str, object]:
        """Return nearest records for one or more query vectors."""


class ChromaClient(Protocol):
    """Small client surface needed to open the persistent collection."""

    def get_or_create_collection(
        self,
        *,
        name: str,
        metadata: dict[str, MetadataValue],
        embedding_function: None,
    ) -> ChromaCollection:
        """Return an existing collection or create it without deleting data."""


class ChromaVectorStore:
    """Index and search `Document` objects through an injected Chroma client."""

    def __init__(
        self,
        client: ChromaClient,
        embedding_model: EmbeddingModel,
        *,
        timeout_seconds: float,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._embedding_model = embedding_model
        self._timeout_seconds = timeout_seconds
        self._collection = self._run(
            "open collection",
            lambda: client.get_or_create_collection(
                name=TRAVEL_KNOWLEDGE_COLLECTION,
                metadata={"description": "Deterministic local travel knowledge"},
                embedding_function=None,
            ),
        )

    def index_documents(self, documents: list[Document]) -> int:
        """Upsert chunks by deterministic chunk ID and return the indexed count."""

        if not documents:
            return 0

        ids = [_document_id(document) for document in documents]
        texts = [document.page_content for document in documents]
        embeddings = self._embedding_model.embed_documents(texts)
        if len(embeddings) != len(documents):
            raise ValueError("embedding model returned the wrong number of vectors")
        metadatas = [_chroma_metadata(document.metadata) for document in documents]

        self._run(
            "index documents",
            partial(
                self._collection.upsert,
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=texts,
            ),
        )
        return len(documents)

    def search_documents(self, query: str, *, top_k: int = 4) -> list[Document]:
        """Return the closest stored chunks for a non-empty query."""

        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")

        record_count = self._run("count documents", self._collection.count)
        if record_count == 0:
            return []

        query_embedding = self._embedding_model.embed_query(query)
        result = self._run(
            "search documents",
            partial(
                self._collection.query,
                query_embeddings=[query_embedding],
                n_results=min(top_k, record_count),
                include=["documents", "metadatas", "distances"],
            ),
        )
        return _documents_from_query_result(result)

    def _run(self, operation_name: str, operation: Callable[[], T]) -> T:
        """Run one official sync client call behind a caller-visible deadline."""

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chroma-rag")
        future = executor.submit(operation)
        try:
            return future.result(timeout=self._timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise VectorStoreError(f"Chroma {operation_name} timed out") from exc
        except Exception as exc:
            raise VectorStoreError(f"Chroma {operation_name} failed") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def create_chroma_vector_store(
    settings: Settings,
    embedding_model: EmbeddingModel | None = None,
) -> ChromaVectorStore:
    """Create the official HTTP client and open the persistent collection."""

    timeout_seconds = settings.infrastructure_timeout_seconds
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chroma-connect")
    future = executor.submit(
        chromadb.HttpClient,
        host=settings.chroma_host,
        port=settings.chroma_port,
        ssl=settings.chroma_ssl,
    )
    try:
        raw_client = future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise VectorStoreError("Chroma connection timed out") from exc
    except Exception as exc:
        raise VectorStoreError("Chroma connection failed") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    client = cast(ChromaClient, raw_client)
    return ChromaVectorStore(
        client,
        embedding_model or DeterministicHashEmbedding(),
        timeout_seconds=timeout_seconds,
    )


def _document_id(document: Document) -> str:
    """Read the splitter's deterministic record ID from metadata."""

    chunk_id = document.metadata.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id:
        raise ValueError("each indexed document needs a non-empty chunk_id")
    return chunk_id


def _chroma_metadata(metadata: dict[str, object]) -> dict[str, MetadataValue]:
    """Keep only primitive metadata values supported by Chroma."""

    normalized: dict[str, MetadataValue] = {}
    for key, value in metadata.items():
        if isinstance(value, str | int | float | bool):
            normalized[key] = value
    return normalized


def _documents_from_query_result(result: Mapping[str, object]) -> list[Document]:
    """Convert Chroma's nested one-query response into LangChain documents."""

    document_groups = cast(list[list[str | None]] | None, result.get("documents"))
    metadata_groups = cast(
        list[list[dict[str, object] | None]] | None,
        result.get("metadatas"),
    )
    if not document_groups or not document_groups[0]:
        return []

    first_metadata_group = metadata_groups[0] if metadata_groups else []
    documents: list[Document] = []
    for index, content in enumerate(document_groups[0]):
        if content is None:
            continue
        metadata = (
            first_metadata_group[index]
            if index < len(first_metadata_group) and first_metadata_group[index] is not None
            else {}
        )
        documents.append(Document(page_content=content, metadata=metadata))
    return documents
