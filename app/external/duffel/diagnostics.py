"""Safe local-only Duffel configuration diagnostics."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.config import Settings


class TravelDataStatus(BaseModel):
    """Public travel-data status with no token-derived details."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["demo", "duffel", "external"]
    provider: Literal["deterministic_demo", "duffel", "mixed"]
    configured: bool
    environment: Literal["test", "live"] | None
    external_kinds: list[Literal["flights", "hotels"]]
    demo_kinds: list[Literal["flights", "hotels", "attractions", "weather", "route"]]
    fallback_enabled: bool
    stays_access_state: Literal["not_applicable", "not_checked"]
    flight_provider: Literal["demo", "duffel"]
    flight_environment: Literal["test", "live"] | None
    flight_configured: bool
    hotel_provider: Literal["demo", "liteapi", "duffel_stays"]
    hotel_environment: Literal["test", "live", "sandbox", "production"] | None
    hotel_configured: bool
    flight_fallback_enabled: bool
    hotel_fallback_enabled: bool
    location_provider: Literal["duffel", "not_required"]


def build_travel_data_status(settings: Settings) -> TravelDataStatus:
    """Describe configuration without probing Duffel or examining token prefixes."""

    flight = settings.selected_flight_provider
    hotel = settings.selected_hotel_provider
    hotel_configured = (
        settings.liteapi_is_configured
        if hotel == "liteapi"
        else settings.duffel_is_configured
        if hotel == "duffel_stays"
        else True
    )
    common = dict(
        flight_provider=flight,
        hotel_provider=hotel,
        flight_environment=settings.duffel_env if flight == "duffel" else None,
        hotel_environment=(
            settings.liteapi_env
            if hotel == "liteapi"
            else settings.duffel_env
            if hotel == "duffel_stays"
            else None
        ),
        flight_configured=settings.duffel_is_configured if flight == "duffel" else True,
        hotel_configured=hotel_configured,
        flight_fallback_enabled=settings.duffel_allow_demo_fallback,
        hotel_fallback_enabled=(
            settings.liteapi_allow_demo_fallback
            if hotel == "liteapi"
            else settings.duffel_allow_demo_fallback
        ),
        location_provider="duffel" if settings.needs_duffel else "not_required",
    )
    if settings.travel_data_mode == "demo":
        return TravelDataStatus(
            **common,
            mode="demo",
            provider="deterministic_demo",
            configured=True,
            environment=None,
            external_kinds=[],
            demo_kinds=["flights", "hotels", "attractions", "weather", "route"],
            fallback_enabled=settings.duffel_allow_demo_fallback,
            stays_access_state="not_applicable",
        )
    return TravelDataStatus(
        **common,
        mode=settings.travel_data_mode,
        provider="duffel" if settings.travel_data_mode == "duffel" else "mixed",
        configured=settings.external_configuration_error is None,
        environment=settings.duffel_env if settings.travel_data_mode == "duffel" else None,
        external_kinds=(["flights"] if flight != "demo" else [])
        + (["hotels"] if hotel != "demo" else []),
        demo_kinds=(["flights"] if flight == "demo" else [])
        + (["hotels"] if hotel == "demo" else [])
        + ["attractions", "weather", "route"],
        fallback_enabled=settings.duffel_allow_demo_fallback
        or (hotel == "liteapi" and settings.liteapi_allow_demo_fallback),
        stays_access_state="not_checked" if hotel == "duffel_stays" else "not_applicable",
    )
