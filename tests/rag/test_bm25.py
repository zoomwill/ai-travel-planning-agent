"""Deterministic BM25 tokenizer and ranking tests."""

from app.rag.bm25 import BM25SparseIndex, tokenize_for_retrieval
from tests.rag.helpers import make_child


def test_tokenizer_supports_casefolded_english_and_chinese_bigrams() -> None:
    """English words and Chinese characters use one transparent local tokenizer."""

    tokens = tokenize_for_retrieval("Tokyo MUSEUM 东京安静社区")

    assert "tokyo" in tokens
    assert "museum" in tokens
    assert "东京" in tokens
    assert "安静" in tokens


def test_bm25_ranks_english_match_and_applies_city_filter() -> None:
    """A relevant Tokyo child wins and a matching Paris child can be filtered out."""

    children = [
        make_child("a", content="Tokyo vintage shopping in Koenji"),
        make_child("b", city="Paris", content="Paris vintage shopping markets"),
        make_child("c", content="Tokyo railway transfer guide"),
    ]
    index = BM25SparseIndex(children)

    results = index.search(
        "vintage shopping",
        query_variant="vintage shopping",
        top_k=5,
        city="Tokyo",
    )

    assert [item.child_id for item in results] == [children[0].child_id]
    assert results[0].raw_score > 0


def test_bm25_chinese_query_and_ties_are_stable() -> None:
    """Chinese bigrams retrieve matching content and equal scores use child ID."""

    children = [
        make_child("b", content="东京安静社区适合散步"),
        make_child("a", content="东京安静社区适合摄影"),
    ]
    index = BM25SparseIndex(children)

    results = index.search(
        "东京安静社区",
        query_variant="东京安静社区",
        top_k=2,
        city="Tokyo",
    )

    assert len(results) == 2
    assert [item.child_id for item in results] == sorted(item.child_id for item in results)
