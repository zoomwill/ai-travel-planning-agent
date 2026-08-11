"""Run-scoped values that must not be saved as graph state."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TravelRuntimeContext:
    """Identify the user and the preferences they explicitly asked to remember."""

    user_id: str
    preferences_to_remember: tuple[str, ...] = ()
