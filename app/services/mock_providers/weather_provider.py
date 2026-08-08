"""Deterministic mock weather summaries."""

from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import Final

from app.domain.models import TripRequirements, WeatherSummary
from app.services.mock_providers._shared import stable_code, validate_trip_route

_CITY_BASE_TEMPERATURES: Final[Mapping[str, float]] = MappingProxyType(
    {
        "tokyo": 19.0,
        "shanghai": 21.0,
        "beijing": 18.0,
        "paris": 16.0,
    }
)
_CONDITIONS: Final[tuple[str, ...]] = ("Sunny", "Partly cloudy", "Cloudy", "Light rain")


def get_weather(requirements: TripRequirements) -> list[WeatherSummary]:
    """Return one repeatable weather summary for every trip date."""

    validate_trip_route(requirements, "get_weather")
    day_count = (requirements.end_date - requirements.start_date).days + 1
    city_code = stable_code(requirements.destination)
    base_temperature = _CITY_BASE_TEMPERATURES.get(
        requirements.destination.casefold(),
        float(14 + city_code % 13),
    )

    summaries: list[WeatherSummary] = []
    for offset in range(day_count):
        current_date = requirements.start_date + timedelta(days=offset)
        daily_code = city_code + current_date.toordinal()
        rain_probability = 10 + daily_code % 61
        condition_index = min(rain_probability // 20, len(_CONDITIONS) - 1)
        summaries.append(
            WeatherSummary(
                date=current_date,
                city=requirements.destination,
                condition=_CONDITIONS[condition_index],
                temperature_celsius=base_temperature + (daily_code % 7 - 3) * 0.5,
                rain_probability=rain_probability,
            )
        )
    return summaries
