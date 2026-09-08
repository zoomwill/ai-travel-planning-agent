"""Travel-domain models shared by services and future planning phases."""

from app.domain.models import (
    Attraction,
    Currency,
    DailyItinerary,
    FlightOption,
    FlightSegment,
    HotelOption,
    QualityScore,
    RouteSummary,
    ToolError,
    TransportMode,
    TravelDataSource,
    TravelDataSources,
    TravelPlan,
    TripRequirements,
    WeatherSummary,
)

__all__ = [
    "Attraction",
    "Currency",
    "DailyItinerary",
    "FlightOption",
    "FlightSegment",
    "HotelOption",
    "QualityScore",
    "RouteSummary",
    "ToolError",
    "TransportMode",
    "TravelPlan",
    "TravelDataSource",
    "TravelDataSources",
    "TripRequirements",
    "WeatherSummary",
]
