"""JSON-safe models for deterministic travel-search map-reduce work."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel
from typing_extensions import TypedDict

from app.domain.models import TripRequirements

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

SearchKindValue: TypeAlias = Literal[
    "flights",
    "hotels",
    "attractions",
    "weather",
    "route",
]
SearchStatus: TypeAlias = Literal["ok", "error"]


class SearchKind(StrEnum):
    """The five independent travel-data searches dispatched by P08."""

    FLIGHTS = "flights"
    HOTELS = "hotels"
    ATTRACTIONS = "attractions"
    WEATHER = "weather"
    ROUTE = "route"


SEARCH_KIND_ORDER: tuple[SearchKind, ...] = (
    SearchKind.FLIGHTS,
    SearchKind.HOTELS,
    SearchKind.ATTRACTIONS,
    SearchKind.WEATHER,
    SearchKind.ROUTE,
)


def search_kind_value(kind: SearchKind) -> SearchKindValue:
    """Narrow a StrEnum value to the exact five JSON string literals."""

    if kind is SearchKind.FLIGHTS:
        return "flights"
    if kind is SearchKind.HOTELS:
        return "hotels"
    if kind is SearchKind.ATTRACTIONS:
        return "attractions"
    if kind is SearchKind.WEATHER:
        return "weather"
    return "route"


class SearchTask(TypedDict):
    """One JSON-safe unit of work created before LangGraph fan-out."""

    task_id: str
    kind: SearchKindValue
    request_fingerprint: str
    origin: str
    destination: str


class SearchResultEnvelope(TypedDict):
    """One successful worker result containing JSON-safe domain data."""

    task_id: str
    kind: SearchKindValue
    status: Literal["ok"]
    data: list[JsonObject]


class SearchErrorEnvelope(TypedDict):
    """One safe worker failure without an exception object or traceback."""

    task_id: str
    kind: SearchKindValue
    error_type: str
    safe_message: str
    recoverable: bool


class SearchSummaryEntry(TypedDict):
    """Public aggregate status for one search kind."""

    status: SearchStatus
    count: int


SearchSummary: TypeAlias = dict[SearchKindValue, SearchSummaryEntry]


class SearchWorkerInput(TypedDict):
    """Minimal JSON-safe payload sent to one generic search worker."""

    search_task: SearchTask
    requirements_data: JsonObject


def dump_model_json(model: BaseModel) -> JsonObject:
    """Convert a Pydantic model into values supported by JSON checkpoints."""

    return cast(JsonObject, model.model_dump(mode="json"))


def create_request_fingerprint(requirements: TripRequirements) -> str:
    """Hash a canonical representation of every validated request field."""

    canonical_request = json.dumps(
        dump_model_json(requirements),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()


def create_search_tasks(requirements: TripRequirements) -> list[SearchTask]:
    """Create exactly one deterministic task for each supported search kind."""

    fingerprint = create_request_fingerprint(requirements)
    tasks: list[SearchTask] = []
    for kind in SEARCH_KIND_ORDER:
        task_digest = hashlib.sha256(f"{fingerprint}\x1f{kind.value}".encode()).hexdigest()[:24]
        tasks.append(
            SearchTask(
                task_id=f"{kind.value}-{task_digest}",
                kind=search_kind_value(kind),
                request_fingerprint=fingerprint,
                origin=requirements.origin,
                destination=requirements.destination,
            )
        )
    return tasks
