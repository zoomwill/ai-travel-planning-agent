"""Tests for the high-level travel knowledge retriever."""

from langchain_core.documents import Document

from app.rag.retriever import TravelKnowledgeRetriever


class FakeDocumentSearcher:
    """Return controlled documents without Chroma or network access."""

    def __init__(self) -> None:
        self.query: str | None = None
        self.top_k: int | None = None

    def search_documents(self, query: str, *, top_k: int = 4) -> list[Document]:
        """Record the search and return one useful plus one empty chunk."""

        self.query = query
        self.top_k = top_k
        return [
            Document(
                page_content="Yanaka is suitable for street photography.",
                metadata={"source": "tokyo.md", "city": "Tokyo"},
            ),
            Document(page_content="  ", metadata={}),
        ]


def test_retriever_returns_nonempty_context_strings() -> None:
    """Only useful text is written into graph state."""

    searcher = FakeDocumentSearcher()
    retriever = TravelKnowledgeRetriever(searcher, top_k=3)

    context = retriever.retrieve("Tokyo photography trip")

    assert context == ["Yanaka is suitable for street photography."]
    assert searcher.query == "Tokyo photography trip"
    assert searcher.top_k == 3
