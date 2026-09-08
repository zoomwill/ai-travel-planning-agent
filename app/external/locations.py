"""One shared location boundary for all external travel providers."""

from typing import Protocol

from app.external.duffel.locations import ResolvedLocation


class LocationResolver(Protocol):
    """Resolve user text to provider-backed facts; never ask an LLM to guess."""

    async def resolve(self, query: str) -> ResolvedLocation:
        """Return an authoritative location usable by flights and hotels."""
