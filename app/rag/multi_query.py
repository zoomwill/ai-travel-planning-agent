"""Injectable deterministic Multi-Query expansion without an LLM."""

from typing import Protocol

from app.rag.models import QueryBundle


class QueryExpander(Protocol):
    """Replaceable async boundary for future validated LLM query expansion."""

    async def expand(self, query_bundle: QueryBundle) -> list[str]:
        """Return bounded query variants in stable order."""


class DeterministicTravelQueryExpander:
    """Combine only user-supplied destination and preferences into variants."""

    def __init__(self, *, variant_count: int) -> None:
        if not 1 <= variant_count <= 8:
            raise ValueError("variant_count must be between 1 and 8")
        self._variant_count = variant_count

    async def expand(self, query_bundle: QueryBundle) -> list[str]:
        """Keep the original first and de-duplicate normalized variants."""

        destination = query_bundle.destination or ""
        current = " ".join(query_bundle.current_preferences)
        remembered = " ".join(query_bundle.remembered_preferences)
        candidates = [
            query_bundle.original_query,
            " ".join(part for part in (destination, current, "travel recommendations") if part),
            " ".join(part for part in (destination, remembered, "travel recommendations") if part),
            " ".join(
                part for part in (destination, current, remembered, "local travel guide") if part
            ),
        ]
        variants: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            cleaned = " ".join(candidate.split())
            normalized = cleaned.casefold()
            if not cleaned or normalized in seen:
                continue
            seen.add(normalized)
            variants.append(cleaned)
            if len(variants) == self._variant_count:
                break
        return variants
