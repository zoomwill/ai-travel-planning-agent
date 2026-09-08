"""Validated data models for travel requirements and provider results."""

from datetime import date as Date
from datetime import datetime as DateTime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.countries import GuestNationality


class Currency(StrEnum):
    """Currencies explicitly supported by deterministic Phase P03 data."""

    CNY = "CNY"
    USD = "USD"
    JPY = "JPY"
    EUR = "EUR"


class TravelDataSource(StrEnum):
    """Truthful, bounded provenance for one travel-search result."""

    DEMO = "demo"
    DUFFEL_TEST = "duffel_test"
    DUFFEL_LIVE = "duffel_live"
    LITEAPI_SANDBOX = "liteapi_sandbox"
    LITEAPI_PRODUCTION = "liteapi_production"
    DEMO_FALLBACK = "demo_fallback"


class TransportMode(StrEnum):
    """Transport modes available in a route summary."""

    PUBLIC_TRANSIT = "public_transit"
    DRIVING = "driving"
    WALKING = "walking"


class DomainModel(BaseModel):
    """Apply beginner-safe validation defaults to every domain model."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


class TripRequirements(DomainModel):
    """A user's complete, structured request for one trip."""

    origin: str = Field(min_length=1, description="City where the trip starts.")
    destination: str = Field(min_length=1, description="Primary city to visit.")
    start_date: Date = Field(description="First calendar date of the trip.")
    end_date: Date = Field(description="Last calendar date of the trip.")
    budget: Decimal = Field(gt=0, description="Maximum total trip budget.")
    currency: Currency = Field(
        default=Currency.CNY,
        description="Currency used for the trip budget and provider prices.",
    )
    travelers: int = Field(gt=0, description="Number of people traveling.")
    guest_nationality: GuestNationality | None = Field(
        default=None, description="Explicit trip-only ISO alpha-2 nationality for hotel pricing."
    )
    preferences: list[str] = Field(
        default_factory=list,
        description="Optional interests or constraints supplied by the traveler.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "origin": "Shanghai",
                    "destination": "Tokyo",
                    "start_date": "2027-04-10",
                    "end_date": "2027-04-13",
                    "budget": "12000.00",
                    "currency": "CNY",
                    "travelers": 2,
                    "preferences": ["local food", "museums"],
                }
            ]
        }
    )

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        """Reject a trip whose return date precedes its departure date."""

        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class FlightSegment(DomainModel):
    """One operating flight inside a direct or connecting itinerary."""

    flight_number: str = Field(min_length=1, description="Operating carrier flight number.")
    airline: str = Field(min_length=1, description="Full operating carrier name.")
    origin_iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    destination_iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    departure_time: DateTime
    arrival_time: DateTime
    duration_minutes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_time_order(self) -> Self:
        """Reject a segment whose arrival is not after departure."""

        try:
            invalid_order = self.arrival_time <= self.departure_time
        except TypeError as exc:
            raise ValueError("segment times must use compatible time zones") from exc
        if invalid_order:
            raise ValueError("segment arrival_time must be later than departure_time")
        return self


class FlightOption(DomainModel):
    """One outbound one-way flight result; a return flight is not searched."""

    flight_number: str = Field(min_length=1, description="Provider-visible flight identifier.")
    airline: str = Field(min_length=1, description="Name of the operating airline.")
    origin: str = Field(min_length=1, description="Departure city.")
    destination: str = Field(min_length=1, description="Arrival city.")
    departure_time: DateTime = Field(description="Local departure date and time.")
    arrival_time: DateTime = Field(description="Local arrival date and time.")
    duration_minutes: int = Field(gt=0, description="Scheduled journey duration in minutes.")
    price: Decimal = Field(
        gt=0,
        description="Outbound one-way price for the searched travel party; return flight excluded.",
    )
    currency: Currency = Field(description="Currency of the flight price.")
    segments: list[FlightSegment] = Field(
        default_factory=list,
        description="Operating segments; empty only for legacy deterministic demo results.",
    )
    stops: int = Field(default=0, ge=0, description="Number of connections in the itinerary.")
    provider_offer_id: str | None = Field(
        default=None,
        min_length=1,
        description="External search identifier retained for diagnostics, never booking.",
    )
    expires_at: DateTime | None = Field(
        default=None,
        description="Provider-reported offer expiry when supplied.",
    )
    data_source: TravelDataSource = Field(
        default=TravelDataSource.DEMO,
        description="Provider provenance for this result.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "flight_number": "MK318",
                    "airline": "Mock Pacific",
                    "origin": "Shanghai",
                    "destination": "Tokyo",
                    "departure_time": "2027-04-10T08:30:00",
                    "arrival_time": "2027-04-10T11:30:00",
                    "duration_minutes": 180,
                    "price": "1800.00",
                    "currency": "CNY",
                }
            ]
        }
    )

    @model_validator(mode="after")
    def validate_time_order(self) -> Self:
        """Reject an arrival that is not later than departure."""

        try:
            invalid_order = self.arrival_time <= self.departure_time
        except TypeError as exc:
            raise ValueError("departure and arrival must use compatible time zones") from exc
        if invalid_order:
            raise ValueError("arrival_time must be later than departure_time")
        if not self.segments:
            if self.stops != 0:
                raise ValueError("a flight without segment details must report zero stops")
            return self
        if self.stops != len(self.segments) - 1:
            raise ValueError("stops must equal the number of connections between segments")
        first, last = self.segments[0], self.segments[-1]
        if (
            self.flight_number != first.flight_number
            or self.airline != first.airline
            or self.departure_time != first.departure_time
            or self.arrival_time != last.arrival_time
        ):
            raise ValueError("flight summary must match its first and last operating segments")
        for previous, current in zip(self.segments, self.segments[1:], strict=False):
            if (
                previous.destination_iata_code != current.origin_iata_code
                or current.departure_time < previous.arrival_time
            ):
                raise ValueError("flight segments must form a chronological connection")
        return self


class HotelOption(DomainModel):
    """One hotel result with a nightly room price."""

    name: str = Field(min_length=1, description="Hotel display name.")
    city: str = Field(min_length=1, description="City where the hotel is located.")
    rating: float | None = Field(
        default=None,
        ge=0,
        le=5,
        description="Property star rating, or null when the provider has none.",
    )
    review_score: float | None = Field(
        default=None,
        ge=0,
        le=10,
        description="Guest review score on a separate zero-to-ten scale.",
    )
    price_per_night: Decimal = Field(gt=0, description="Room price for one night.")
    total_stay_price: Decimal | None = Field(
        default=None,
        gt=0,
        description="Exact provider stay quote, excluding separately payable property fees.",
    )
    stay_nights: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=366,
        description="Number of nights covered by the stay quote.",
    )
    room_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Provider-supplied room name, when available.",
    )
    board_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Provider-supplied meal plan, when available.",
    )
    refundable: bool | None = Field(
        default=None, description="Provider refundable classification; conditions may apply."
    )
    has_excluded_fees: bool = Field(
        default=False,
        description="Whether additional property fees are explicitly excluded from the stay quote.",
    )
    currency: Currency = Field(description="Currency of the nightly price.")
    distance_to_center_km: float | None = Field(
        default=None,
        ge=0,
        description="Approximate distance from the city center in kilometers.",
    )
    amenities: list[str] = Field(
        default_factory=list,
        description="Facilities advertised for the hotel.",
    )
    provider_hotel_id: str | None = Field(
        default=None,
        min_length=1,
        description="Stable external accommodation identifier, never a booking action.",
    )
    provider_search_result_id: str | None = Field(
        default=None,
        min_length=1,
        description="Volatile search identifier retained only as provider metadata.",
    )
    data_source: TravelDataSource = Field(
        default=TravelDataSource.DEMO,
        description="Provider provenance for this result.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Tokyo Central Hotel",
                    "city": "Tokyo",
                    "rating": 4.5,
                    "price_per_night": "780.00",
                    "currency": "CNY",
                    "distance_to_center_km": 1.2,
                    "amenities": ["Wi-Fi", "breakfast", "laundry"],
                }
            ]
        }
    )

    @model_validator(mode="after")
    def validate_stay_quote(self) -> Self:
        """Keep optional external total, night count and rounded average consistent."""
        if (self.total_stay_price is None) != (self.stay_nights is None):
            raise ValueError("stay total and night count must be provided together")
        if self.total_stay_price is not None and self.stay_nights is not None:
            expected = (self.total_stay_price / self.stay_nights).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if self.price_per_night != expected:
                raise ValueError("nightly average must match the exact stay quote")
        return self


class Attraction(DomainModel):
    """One place a traveler could visit."""

    name: str = Field(min_length=1, description="Attraction display name.")
    city: str = Field(min_length=1, description="City containing the attraction.")
    category: str = Field(min_length=1, description="Broad attraction category.")
    description: str = Field(min_length=1, description="Short mock visitor description.")
    estimated_cost: Decimal = Field(ge=0, description="Estimated admission cost per traveler.")
    currency: Currency = Field(description="Currency of the estimated admission cost.")
    opening_hours: str = Field(min_length=1, description="Human-readable mock opening hours.")
    data_source: TravelDataSource = Field(
        default=TravelDataSource.DEMO,
        description="Provider provenance for this result.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Asakusa Heritage Walk",
                    "city": "Tokyo",
                    "category": "culture",
                    "description": "A mock self-guided walk through historic streets.",
                    "estimated_cost": "0.00",
                    "currency": "CNY",
                    "opening_hours": "09:00-18:00",
                }
            ]
        }
    )


class WeatherSummary(DomainModel):
    """Deterministic daily weather data for one city."""

    date: Date = Field(description="Calendar date covered by this summary.")
    city: str = Field(min_length=1, description="City covered by this summary.")
    condition: str = Field(min_length=1, description="Simple mock weather condition.")
    temperature_celsius: float = Field(description="Mock daytime temperature in Celsius.")
    rain_probability: int = Field(
        ge=0,
        le=100,
        description="Mock probability of rain as a percentage.",
    )
    data_source: TravelDataSource = Field(
        default=TravelDataSource.DEMO,
        description="Provider provenance for this result.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "date": "2027-04-10",
                    "city": "Tokyo",
                    "condition": "Sunny",
                    "temperature_celsius": 19.5,
                    "rain_probability": 15,
                }
            ]
        }
    )


class RouteSummary(DomainModel):
    """A simple point-to-point route estimate."""

    origin: str = Field(min_length=1, description="Route starting place.")
    destination: str = Field(min_length=1, description="Route destination.")
    transport_mode: TransportMode = Field(description="Suggested mock transport mode.")
    duration_minutes: int = Field(gt=0, description="Estimated travel duration in minutes.")
    estimated_cost: Decimal = Field(ge=0, description="Estimated route cost.")
    currency: Currency = Field(
        default=Currency.CNY,
        description="Currency of the estimated route cost.",
    )
    data_source: TravelDataSource = Field(
        default=TravelDataSource.DEMO,
        description="Provider provenance for this result.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "origin": "Tokyo Station",
                    "destination": "Asakusa",
                    "transport_mode": "public_transit",
                    "duration_minutes": 24,
                    "estimated_cost": "18.00",
                    "currency": "CNY",
                }
            ]
        }
    )


class DailyItinerary(DomainModel):
    """The planned activities and estimated cost for one day."""

    day_number: int = Field(ge=1, description="One-based day number within the trip.")
    date: Date = Field(description="Calendar date for this itinerary day.")
    title: str = Field(min_length=1, description="Short theme or title for the day.")
    activities: list[str] = Field(
        min_length=1,
        description="Ordered human-readable activities for the day.",
    )
    estimated_cost: Decimal = Field(ge=0, description="Estimated total cost for the day.")
    currency: Currency = Field(description="Currency of the daily estimated cost.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "day_number": 1,
                    "date": "2027-04-10",
                    "title": "Arrival and old Tokyo",
                    "activities": ["Hotel check-in", "Asakusa Heritage Walk"],
                    "estimated_cost": "320.00",
                    "currency": "CNY",
                }
            ]
        }
    )


class TravelDataSources(DomainModel):
    """Provider provenance for each of the five parallel searches."""

    flights: TravelDataSource = TravelDataSource.DEMO
    hotels: TravelDataSource = TravelDataSource.DEMO
    attractions: TravelDataSource = TravelDataSource.DEMO
    weather: TravelDataSource = TravelDataSource.DEMO
    route: TravelDataSource = TravelDataSource.DEMO


class TravelPlan(DomainModel):
    """A validated deterministic travel plan returned by the planning service."""

    requirements: TripRequirements = Field(description="Requirements this plan must satisfy.")
    flight: FlightOption = Field(description="Selected outbound one-way flight; no return quote.")
    hotel: HotelOption = Field(description="Selected hotel option.")
    daily_itinerary: list[DailyItinerary] = Field(
        min_length=1,
        description="One or more planned travel days.",
    )
    total_cost: Decimal = Field(
        gt=0, description="Plan estimate including outbound airfare only; return flight excluded."
    )
    currency: Currency = Field(description="Currency shared by all plan costs.")
    budget_warning: str | None = Field(
        default=None,
        description="Plain-language warning when the estimate exceeds the requested budget.",
    )
    markdown: str = Field(
        default="",
        description="Human-readable Markdown rendering of the same structured plan.",
    )
    data_sources: TravelDataSources = Field(
        default_factory=TravelDataSources,
        description="Truthful source of each travel-search category.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "requirements": {
                        "origin": "Shanghai",
                        "destination": "Tokyo",
                        "start_date": "2027-04-10",
                        "end_date": "2027-04-13",
                        "budget": "12000.00",
                        "currency": "CNY",
                        "travelers": 2,
                        "preferences": ["local food"],
                    },
                    "flight": {
                        "flight_number": "MK318",
                        "airline": "Mock Pacific",
                        "origin": "Shanghai",
                        "destination": "Tokyo",
                        "departure_time": "2027-04-10T08:30:00",
                        "arrival_time": "2027-04-10T11:30:00",
                        "duration_minutes": 180,
                        "price": "1800.00",
                        "currency": "CNY",
                    },
                    "hotel": {
                        "name": "Tokyo Central Hotel",
                        "city": "Tokyo",
                        "rating": 4.5,
                        "price_per_night": "780.00",
                        "currency": "CNY",
                        "distance_to_center_km": 1.2,
                        "amenities": ["Wi-Fi", "breakfast"],
                    },
                    "daily_itinerary": [
                        {
                            "day_number": 1,
                            "date": "2027-04-10",
                            "title": "Arrival",
                            "activities": ["Hotel check-in"],
                            "estimated_cost": "320.00",
                            "currency": "CNY",
                        }
                    ],
                    "total_cost": "4460.00",
                    "currency": "CNY",
                    "budget_warning": None,
                    "markdown": "# Mock travel plan: Shanghai to Tokyo",
                }
            ]
        }
    )

    @model_validator(mode="after")
    def validate_plan_consistency(self) -> Self:
        """Require consistent currencies and itinerary dates inside the trip."""

        currencies = [
            self.requirements.currency,
            self.flight.currency,
            self.hotel.currency,
            *(day.currency for day in self.daily_itinerary),
        ]
        if any(currency != self.currency for currency in currencies):
            raise ValueError("all plan costs must use the plan currency")
        if self.data_sources.flights != self.flight.data_source:
            raise ValueError("flight source summary must match the selected flight")
        if self.data_sources.hotels != self.hotel.data_source:
            raise ValueError("hotel source summary must match the selected hotel")

        for day in self.daily_itinerary:
            if not self.requirements.start_date <= day.date <= self.requirements.end_date:
                raise ValueError("daily itinerary dates must fall within the trip dates")
        return self


class QualityScore(DomainModel):
    """Reviewer-ready quality scores on a zero-to-one-hundred scale."""

    completeness: float = Field(ge=0, le=100, description="Coverage of required plan details.")
    feasibility: float = Field(ge=0, le=100, description="Practicality of timing and logistics.")
    personalization: float = Field(ge=0, le=100, description="Fit with stated preferences.")
    budget_fit: float = Field(ge=0, le=100, description="Fit with the requested budget.")
    overall_score: float = Field(ge=0, le=100, description="Overall review score.")
    critique: str = Field(description="Concrete revision guidance, or an empty string if none.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "completeness": 92,
                    "feasibility": 86,
                    "personalization": 88,
                    "budget_fit": 90,
                    "overall_score": 89,
                    "critique": "Add transfer time between the airport and hotel.",
                }
            ]
        }
    )


class ToolError(DomainModel):
    """A safe provider error without a traceback or connection internals."""

    tool_name: str = Field(min_length=1, description="Name of the tool or provider that failed.")
    error_type: str = Field(min_length=1, description="Stable machine-readable error category.")
    message: str = Field(min_length=1, description="Safe human-readable error message.")
    recoverable: bool = Field(description="Whether a later retry could reasonably succeed.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tool_name": "search_flights",
                    "error_type": "unsupported_route",
                    "message": "Origin and destination must be different.",
                    "recoverable": False,
                }
            ]
        }
    )
