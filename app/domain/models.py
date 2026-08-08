"""Validated data models for travel requirements and provider results."""

from datetime import date as Date
from datetime import datetime as DateTime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Currency(StrEnum):
    """Currencies explicitly supported by deterministic Phase P03 data."""

    CNY = "CNY"
    USD = "USD"
    JPY = "JPY"
    EUR = "EUR"


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


class FlightOption(DomainModel):
    """One flight result returned by a flight provider."""

    flight_number: str = Field(min_length=1, description="Provider-visible flight identifier.")
    airline: str = Field(min_length=1, description="Name of the operating mock airline.")
    origin: str = Field(min_length=1, description="Departure city.")
    destination: str = Field(min_length=1, description="Arrival city.")
    departure_time: DateTime = Field(description="Local mock departure date and time.")
    arrival_time: DateTime = Field(description="Local mock arrival date and time.")
    duration_minutes: int = Field(gt=0, description="Scheduled journey duration in minutes.")
    price: Decimal = Field(gt=0, description="Mock price for one traveler.")
    currency: Currency = Field(description="Currency of the flight price.")

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
        return self


class HotelOption(DomainModel):
    """One hotel result with a nightly mock price."""

    name: str = Field(min_length=1, description="Hotel display name.")
    city: str = Field(min_length=1, description="City where the hotel is located.")
    rating: float = Field(ge=0, le=5, description="Mock guest rating from zero to five.")
    price_per_night: Decimal = Field(gt=0, description="Mock room price for one night.")
    currency: Currency = Field(description="Currency of the nightly price.")
    distance_to_center_km: float = Field(
        ge=0,
        description="Approximate distance from the city center in kilometers.",
    )
    amenities: list[str] = Field(
        default_factory=list,
        description="Facilities advertised by the mock hotel.",
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


class Attraction(DomainModel):
    """One place a traveler could visit."""

    name: str = Field(min_length=1, description="Attraction display name.")
    city: str = Field(min_length=1, description="City containing the attraction.")
    category: str = Field(min_length=1, description="Broad attraction category.")
    description: str = Field(min_length=1, description="Short mock visitor description.")
    estimated_cost: Decimal = Field(ge=0, description="Estimated admission cost per traveler.")
    currency: Currency = Field(description="Currency of the estimated admission cost.")
    opening_hours: str = Field(min_length=1, description="Human-readable mock opening hours.")

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


class TravelPlan(DomainModel):
    """A validated final-plan shape for future planning phases."""

    requirements: TripRequirements = Field(description="Requirements this plan must satisfy.")
    flight: FlightOption = Field(description="Selected flight option.")
    hotel: HotelOption = Field(description="Selected hotel option.")
    daily_itinerary: list[DailyItinerary] = Field(
        min_length=1,
        description="One or more planned travel days.",
    )
    total_cost: Decimal = Field(gt=0, description="Estimated total cost of the plan.")
    currency: Currency = Field(description="Currency shared by all plan costs.")

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
