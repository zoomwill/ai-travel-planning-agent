"""Tests for bounded deterministic Multi-Query expansion."""

import pytest

from app.rag.models import QueryBundle
from app.rag.multi_query import DeterministicTravelQueryExpander


@pytest.mark.asyncio
async def test_original_query_is_first_and_preferences_enter_variants() -> None:
    """Current and remembered preferences appear without inventing another city."""

    expander = DeterministicTravelQueryExpander(variant_count=4)
    bundle = QueryBundle(
        original_query="东京安静的街头摄影地点",
        destination="Tokyo",
        current_preferences=["photography"],
        remembered_preferences=["avoid crowds"],
        metadata_filter={"city": "Tokyo"},
    )

    variants = await expander.expand(bundle)

    assert variants[0] == bundle.original_query
    assert len(variants) == 4
    assert any("photography" in item for item in variants)
    assert any("avoid crowds" in item for item in variants)
    assert all("Paris" not in item for item in variants)


@pytest.mark.asyncio
async def test_variants_are_deduplicated_and_bounded() -> None:
    """Repeated destination-only variants collapse without padding fake queries."""

    expander = DeterministicTravelQueryExpander(variant_count=2)
    bundle = QueryBundle(original_query="Tokyo", destination="Tokyo")

    variants = await expander.expand(bundle)

    assert variants[0] == "Tokyo"
    assert len(variants) <= 2
    assert len({item.casefold() for item in variants}) == len(variants)
