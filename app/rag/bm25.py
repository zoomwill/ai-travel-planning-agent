"""Deterministic English and Chinese BM25 sparse retrieval for P10."""

import re
from collections.abc import Sequence

from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from app.rag.models import ChildChunk, RetrievalCandidate

_LATIN_TOKEN = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")


def tokenize_for_retrieval(text: str) -> list[str]:
    """Casefold Latin tokens and add characters plus bigrams for Chinese runs."""

    normalized = text.casefold()
    tokens = _LATIN_TOKEN.findall(normalized)
    for run in _CJK_RUN.findall(normalized):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


class BM25SparseIndex:
    """Build BM25Okapi once from a stable child manifest and rank by child ID ties."""

    def __init__(self, children: Sequence[ChildChunk]) -> None:
        if not children:
            raise ValueError("BM25 requires at least one child chunk")
        self._children = tuple(children)
        self._tokenized = [tokenize_for_retrieval(child.content) for child in children]
        self._token_sets = [set(tokens) for tokens in self._tokenized]
        self._index = BM25Okapi(self._tokenized)

    @property
    def child_count(self) -> int:
        """Return the fixed number of indexed manifest children."""

        return len(self._children)

    def search(
        self,
        query: str,
        *,
        query_variant: str,
        top_k: int,
        city: str | None,
    ) -> list[RetrievalCandidate]:
        """Return positive-score sparse candidates with an optional exact city filter."""

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        tokens = tokenize_for_retrieval(query)
        if not tokens:
            return []
        scores = self._index.get_scores(tokens)
        matches = [
            (float(scores[index]), child)
            for index, child in enumerate(self._children)
            if set(tokens) & self._token_sets[index]
            and (city is None or child.city.casefold() == city.casefold())
        ]
        matches.sort(key=lambda item: (-item[0], item[1].child_id))
        return [
            RetrievalCandidate(
                child_id=child.child_id,
                parent_id=child.parent_id,
                source=child.source,
                city=child.city,
                content=child.content,
                retrieval_method="sparse",
                query_variant=query_variant,
                rank=rank,
                raw_score=score,
            )
            for rank, (score, child) in enumerate(matches[:top_k], start=1)
        ]
