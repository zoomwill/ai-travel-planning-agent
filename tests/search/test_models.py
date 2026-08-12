"""Tests for deterministic, JSON-safe P08 search tasks."""

import json
from datetime import date
from decimal import Decimal

from app.domain.models import Currency, TripRequirements
from app.search.models import (
    SEARCH_KIND_ORDER,
    create_request_fingerprint,
    create_search_tasks,
)


def make_requirements(destination: str = "Tokyo") -> TripRequirements:
    """Build one complete request with a configurable destination."""

    return TripRequirements(
        origin="Shanghai",
        destination=destination,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        budget=Decimal("10000.00"),
        currency=Currency.CNY,
        travelers=1,
        preferences=["photography"],
    )


def test_exactly_five_tasks_are_created_in_fixed_order() -> None:
    """Prepare data contains one task for every supported search kind."""

    tasks = create_search_tasks(make_requirements())

    assert [task["kind"] for task in tasks] == [kind.value for kind in SEARCH_KIND_ORDER]
    assert len({task["task_id"] for task in tasks}) == 5


def test_same_request_has_identical_fingerprint_and_task_ids() -> None:
    """A replay of the same validated request produces the same work identity."""

    first = create_search_tasks(make_requirements())
    second = create_search_tasks(make_requirements())

    assert first == second
    assert len({task["request_fingerprint"] for task in first}) == 1


def test_different_request_changes_fingerprint_and_all_task_ids() -> None:
    """Paris work cannot overwrite Tokyo work under the same stable IDs."""

    tokyo = create_search_tasks(make_requirements("Tokyo"))
    paris = create_search_tasks(make_requirements("Paris"))

    assert create_request_fingerprint(make_requirements("Tokyo")) != (
        create_request_fingerprint(make_requirements("Paris"))
    )
    assert {task["task_id"] for task in tokyo}.isdisjoint(task["task_id"] for task in paris)


def test_tasks_are_standard_json_serializable() -> None:
    """No provider, client, date, Decimal, or Pydantic object enters task state."""

    encoded = json.dumps(create_search_tasks(make_requirements()), sort_keys=True)

    assert "flights" in encoded
    assert "Tokyo" in encoded
