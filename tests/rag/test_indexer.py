"""Docker-free corpus preparation tests for the explicit P10 indexer."""

from app.core.config import Settings
from app.rag.evaluation import load_evaluation_queries
from app.rag.indexer import build_advanced_corpus


def test_demo_corpus_exceeds_required_document_parent_and_child_counts() -> None:
    """Committed fixtures are large enough for meaningful multi-stage retrieval."""

    corpus = build_advanced_corpus(Settings(_env_file=None), embedding_dimension=384)

    assert corpus.markdown_count >= 12
    assert len(corpus.parents) > 20
    assert len(corpus.children) > 40
    assert corpus.metadata.embedding_dimension == 384


def test_corpus_build_is_reproducible_and_versioned() -> None:
    """Same inputs repeat exactly while a version change creates new identities."""

    first = build_advanced_corpus(Settings(_env_file=None), embedding_dimension=384)
    second = build_advanced_corpus(Settings(_env_file=None), embedding_dimension=384)
    changed = build_advanced_corpus(
        Settings(_env_file=None, rag_pipeline_version="advanced-v2"),
        embedding_dimension=384,
    )

    assert first == second
    assert first.metadata.corpus_fingerprint != changed.metadata.corpus_fingerprint
    assert {item.child_id for item in first.children}.isdisjoint(
        {item.child_id for item in changed.children}
    )


def test_evaluation_labels_reference_only_current_parent_ids() -> None:
    """Human judgments cannot silently point at stale or invented parents."""

    corpus = build_advanced_corpus(Settings(_env_file=None), embedding_dimension=384)
    parent_ids = {parent.parent_id for parent in corpus.parents}
    queries = load_evaluation_queries()

    assert len(queries) == 24
    assert all(set(query.relevance_judgments) <= parent_ids for query in queries)
