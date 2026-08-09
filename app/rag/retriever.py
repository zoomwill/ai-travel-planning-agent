"""High-level retrieval service used by the LangGraph Retriever Agent."""

from typing import Protocol

from langchain_core.documents import Document

from app.core.config import Settings, get_settings
from app.rag.vector_store import ChromaVectorStore, create_chroma_vector_store


class DocumentSearcher(Protocol):
    """Search surface that can be replaced by an in-memory fake in tests."""

    def search_documents(self, query: str, *, top_k: int = 4) -> list[Document]:
        """Return matching knowledge chunks."""


class TravelKnowledgeRetriever:
    """Turn matching vector-store documents into graph-ready context strings."""

    def __init__(self, vector_store: DocumentSearcher, *, top_k: int = 4) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        self._vector_store = vector_store
        self._top_k = top_k

    def retrieve(self, query: str) -> list[str]:
        """Return non-empty context strings in vector similarity order."""

        documents = self._vector_store.search_documents(query, top_k=self._top_k)
        return [document.page_content for document in documents if document.page_content.strip()]


def create_travel_knowledge_retriever(
    settings: Settings | None = None,
) -> TravelKnowledgeRetriever:
    """Create a retriever backed by the existing Chroma Docker service."""

    resolved_settings = settings or get_settings()
    vector_store: ChromaVectorStore = create_chroma_vector_store(resolved_settings)
    return TravelKnowledgeRetriever(vector_store)


def retrieve_travel_context(query: str) -> list[str]:
    """Retrieve context from Chroma without connecting during module import."""

    return create_travel_knowledge_retriever().retrieve(query)
