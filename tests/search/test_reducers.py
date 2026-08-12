"""Pure reducer tests for parallel result ordering, replay, and retries."""

from copy import deepcopy

from app.search.models import SearchErrorEnvelope, SearchKindValue, SearchResultEnvelope
from app.search.reducers import merge_search_results, merge_tool_errors


def result(
    task_id: str,
    kind: SearchKindValue,
    name: str,
) -> SearchResultEnvelope:
    """Build a small JSON-safe successful envelope."""

    return SearchResultEnvelope(
        task_id=task_id,
        kind=kind,
        status="ok",
        data=[{"name": name}],
    )


def error(task_id: str, kind: SearchKindValue) -> SearchErrorEnvelope:
    """Build a small JSON-safe failure envelope."""

    return SearchErrorEnvelope(
        task_id=task_id,
        kind=kind,
        error_type="provider_error",
        safe_message="Search unavailable.",
        recoverable=True,
    )


def test_result_merge_is_order_independent_and_fixed_by_kind() -> None:
    """Completion order cannot change final state ordering."""

    flights = result("flight-1", "flights", "F1")
    weather = result("weather-1", "weather", "W1")

    assert merge_search_results([weather], [flights]) == merge_search_results([flights], [weather])
    assert [item["kind"] for item in merge_search_results([weather], [flights])] == [
        "flights",
        "weather",
    ]


def test_result_retry_does_not_duplicate_or_mutate_inputs() -> None:
    """The same task result remains one item across retries and replay."""

    item = result("flight-1", "flights", "F1")
    left = [item]
    before = deepcopy(left)

    merged = merge_search_results(left, [deepcopy(item), deepcopy(item)])

    assert merged == [item]
    assert left == before


def test_conflicting_duplicate_choice_is_stable_in_both_orders() -> None:
    """Even an unexpected conflicting retry is resolved deterministically."""

    first = result("flight-1", "flights", "B")
    second = result("flight-1", "flights", "A")

    assert merge_search_results([first], [second]) == merge_search_results([second], [first])


def test_tool_error_reducer_is_order_independent_and_deduplicates() -> None:
    """Parallel safe errors follow the same stable replay rules."""

    hotel = error("hotel-1", "hotels")
    route = error("route-1", "route")

    first = merge_tool_errors([route, hotel], [deepcopy(hotel)])
    second = merge_tool_errors([hotel], [route])

    assert first == second
    assert [item["kind"] for item in first] == ["hotels", "route"]
