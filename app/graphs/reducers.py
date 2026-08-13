"""Small pure reducers for single-writer graph fields that need explicit reset."""

from typing import TypeVar

ValueT = TypeVar("ValueT")


def replace_state_value(left: ValueT, right: ValueT) -> ValueT:
    """Return the new value without mutating either reducer input."""

    del left
    return right
