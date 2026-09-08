"""MCP implementation of the existing asynchronous SearchBackend boundary."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import NoReturn, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.domain.models import (
    Attraction,
    Currency,
    FlightOption,
    HotelOption,
    RouteSummary,
    TravelDataSource,
    TripRequirements,
    WeatherSummary,
)
from app.mcp_tools.errors import MCPToolLayerError
from app.mcp_tools.models import MCPToolRequest, MCPToolResponse, MCPTripRequirements
from app.mcp_tools.protocol import SEARCH_KIND_TO_TOOL, ToolName
from app.search.models import SearchKind, create_request_fingerprint, create_search_tasks

DomainResult = TypeVar("DomainResult", bound=BaseModel)


class MCPInvoker(Protocol):
    """Narrow invoker boundary used by the MCP backend and offline tests."""

    async def invoke(self, tool_name: str, request: MCPToolRequest) -> MCPToolResponse:
        """Return one validated tool response envelope."""


class MCPTravelSearchBackend:
    """Translate SearchBackend calls to five named MCP tools."""

    def __init__(
        self,
        invoker: MCPInvoker,
        configured_external_source: TravelDataSource = TravelDataSource.DEMO,
        *,
        sources: dict[SearchKind, TravelDataSource] | None = None,
        flight_limit: int = 20,
        hotel_limit: int = 20,
        fallback_kinds: frozenset[SearchKind] = frozenset(),
    ) -> None:
        self._invoker = invoker
        self._configured_external_source = configured_external_source
        self._sources = sources
        self._flight_limit = flight_limit
        self._hotel_limit = hotel_limit
        self._fallback_kinds = fallback_kinds

    def source_for(self, kind: SearchKind) -> TravelDataSource:
        """Return configured provenance before an MCP response is available."""

        if self._sources is not None:
            return self._sources[kind]
        if kind in {SearchKind.FLIGHTS, SearchKind.HOTELS}:
            return self._configured_external_source
        return TravelDataSource.DEMO

    async def search_flights(self, requirements: TripRequirements) -> list[FlightOption]:
        """Call the HTTP flight tool and validate every domain result."""

        response = await self._invoke(SearchKind.FLIGHTS, requirements)
        return self._validate_list(response, FlightOption, limit=self._flight_limit)

    async def search_hotels(self, requirements: TripRequirements) -> list[HotelOption]:
        """Call the HTTP hotel tool and validate every domain result."""

        response = await self._invoke(SearchKind.HOTELS, requirements)
        return self._validate_list(response, HotelOption, limit=self._hotel_limit)

    async def search_attractions(self, requirements: TripRequirements) -> list[Attraction]:
        """Call the HTTP attraction tool and validate every domain result."""

        response = await self._invoke(SearchKind.ATTRACTIONS, requirements)
        return self._validate_list(response, Attraction)

    async def get_weather(self, requirements: TripRequirements) -> list[WeatherSummary]:
        """Call the STDIO weather tool and validate every domain result."""

        response = await self._invoke(SearchKind.WEATHER, requirements)
        return self._validate_list(response, WeatherSummary)

    async def get_route(self, origin: str, destination: str) -> RouteSummary:
        """Call the STDIO route tool while preserving the existing backend protocol."""

        route_requirements = TripRequirements(
            origin=origin,
            destination=destination,
            start_date=date(2000, 1, 1),
            end_date=date(2000, 1, 1),
            budget=Decimal("1"),
            currency=Currency.CNY,
            travelers=1,
        )
        response = await self._invoke(
            SearchKind.ROUTE,
            route_requirements,
            route_origin=origin,
            route_destination=destination,
        )
        return self._validate_one(response, RouteSummary)

    async def _invoke(
        self,
        kind: SearchKind,
        requirements: TripRequirements,
        *,
        route_origin: str | None = None,
        route_destination: str | None = None,
    ) -> MCPToolResponse:
        """Build deterministic request metadata and invoke the mapped tool."""

        task = next(task for task in create_search_tasks(requirements) if task["kind"] == kind)
        request = MCPToolRequest(
            task_id=task["task_id"],
            request_fingerprint=create_request_fingerprint(requirements),
            requirements=MCPTripRequirements.from_domain(requirements),
            route_origin=route_origin,
            route_destination=route_destination,
        )
        tool_name: ToolName = SEARCH_KIND_TO_TOOL[kind]
        response = await self._invoker.invoke(tool_name, request)
        if (
            response.tool_name != tool_name
            or response.task_id != request.task_id
            or response.request_fingerprint != request.request_fingerprint
        ):
            raise MCPToolLayerError(
                "mcp_invalid_response",
                "The MCP response metadata did not match the backend request.",
                recoverable=False,
            )
        if not response.ok:
            if response.error is None:
                raise MCPToolLayerError(
                    "mcp_invalid_response",
                    "The MCP tool returned an invalid failure envelope.",
                    recoverable=False,
                )
            error_type = response.error.error_type
            if error_type == "provider_error":
                error_type = "mcp_tool_failed"
            elif error_type == "invalid_request":
                error_type = "mcp_invalid_response"
            raise MCPToolLayerError(
                error_type,
                response.error.safe_message,
                recoverable=response.error.recoverable,
            )
        expected_source = self.source_for(kind)
        if response.source != expected_source and not (
            response.source is TravelDataSource.DEMO_FALLBACK and kind in self._fallback_kinds
        ):
            raise MCPToolLayerError(
                "mcp_invalid_response",
                "MCP source does not match the selected provider.",
                recoverable=False,
            )
        return response

    @staticmethod
    def _validate_list(
        response: MCPToolResponse,
        model_type: type[DomainResult],
        *,
        limit: int | None = None,
    ) -> list[DomainResult]:
        """Validate one JSON list back into the existing domain model type."""

        if not isinstance(response.data, list):
            raise MCPToolLayerError(
                "mcp_invalid_response",
                "The MCP tool returned an invalid result collection.",
                recoverable=False,
            )
        try:
            models = [model_type.model_validate(item) for item in response.data[:limit]]
            if any(getattr(item, "data_source", None) != response.source for item in models):
                raise MCPToolLayerError(
                    "mcp_invalid_response",
                    "MCP result provenance is inconsistent.",
                    recoverable=False,
                )
            return models
        except ValidationError as exc:
            raise MCPToolLayerError(
                "mcp_invalid_response",
                "The MCP tool returned invalid travel data.",
                recoverable=False,
            ) from exc

    @staticmethod
    def _validate_one(
        response: MCPToolResponse,
        model_type: type[DomainResult],
    ) -> DomainResult:
        """Validate one JSON object back into the existing domain model type."""

        try:
            return model_type.model_validate(response.data)
        except ValidationError as exc:
            raise MCPToolLayerError(
                "mcp_invalid_response",
                "The MCP tool returned invalid travel data.",
                recoverable=False,
            ) from exc


class UnavailableMCPTravelSearchBackend:
    """Fail safely when MCP discovery did not produce an invokable registry."""

    def source_for(self, kind: SearchKind) -> TravelDataSource:
        """Return demo only as a safe pre-response default."""

        del kind
        return TravelDataSource.DEMO

    @staticmethod
    def _raise() -> NoReturn:
        raise MCPToolLayerError(
            "mcp_discovery_failed",
            "The MCP travel tools are not initialized.",
            recoverable=True,
        )

    async def search_flights(self, requirements: TripRequirements) -> list[FlightOption]:
        """Return no fabricated fallback when flight MCP is unavailable."""

        del requirements
        self._raise()

    async def search_hotels(self, requirements: TripRequirements) -> list[HotelOption]:
        """Return no fabricated fallback when hotel MCP is unavailable."""

        del requirements
        self._raise()

    async def search_attractions(self, requirements: TripRequirements) -> list[Attraction]:
        """Return no fabricated fallback when attraction MCP is unavailable."""

        del requirements
        self._raise()

    async def get_weather(self, requirements: TripRequirements) -> list[WeatherSummary]:
        """Return no fabricated fallback when weather MCP is unavailable."""

        del requirements
        self._raise()

    async def get_route(self, origin: str, destination: str) -> RouteSummary:
        """Return no fabricated fallback when route MCP is unavailable."""

        del origin, destination
        self._raise()
