"""Official Places resolver tests; no LLM or private airport table is involved."""

import httpx
import pytest

from app.external.duffel.errors import DuffelError
from app.external.duffel.locations import DuffelLocationResolver
from tests.external.duffel.helpers import make_client, place


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "name", "code"),
    [
        ("Cleveland", "Cleveland", "CLE"),
        ("Tokyo", "Tokyo", "TYO"),
        ("Paris", "Paris", "PAR"),
        ("CLE", "Cleveland Hopkins", "CLE"),
    ],
)
async def test_resolves_city_or_iata_from_provider_results(
    query: str, name: str, code: str
) -> None:
    result = place(name, code, latitude=35.0, longitude=139.0)
    if query == "CLE":
        result["type"] = "airport"

    client = make_client(lambda _: httpx.Response(200, json={"data": [result]}))
    resolved = await DuffelLocationResolver(client).resolve(query)
    await client.aclose()

    assert resolved.iata_code == code
    assert (resolved.latitude, resolved.longitude) == (35.0, 139.0)


@pytest.mark.asyncio
async def test_unknown_location_is_rejected() -> None:
    client = make_client(lambda _: httpx.Response(200, json={"data": []}))
    with pytest.raises(DuffelError, match="duffel_location_not_found"):
        await DuffelLocationResolver(client).resolve("Unknown Place")
    await client.aclose()


@pytest.mark.asyncio
async def test_ambiguous_exact_city_is_rejected() -> None:
    values = [
        place("Paris", "PAR", latitude=48.85, longitude=2.35),
        place("Paris", "PRX", latitude=33.66, longitude=-95.55),
    ]
    client = make_client(lambda _: httpx.Response(200, json={"data": values}))
    with pytest.raises(DuffelError, match="duffel_location_not_found"):
        await DuffelLocationResolver(client).resolve("Paris")
    await client.aclose()


@pytest.mark.asyncio
async def test_city_coordinates_can_be_derived_from_official_airports() -> None:
    value = place("Tokyo", "TYO", latitude=35.0, longitude=139.0)
    value["latitude"] = None
    value["longitude"] = None
    value["airports"] = [
        {"name": "Haneda", "iata_code": "HND", "latitude": 35.55, "longitude": 139.78},
        {"name": "Narita", "iata_code": "NRT", "latitude": 35.77, "longitude": 140.39},
    ]
    client = make_client(lambda _: httpx.Response(200, json={"data": [value]}))
    resolved = await DuffelLocationResolver(client).resolve("Tokyo")
    await client.aclose()

    assert resolved.iata_codes == ("TYO", "HND", "NRT")
    assert resolved.latitude == pytest.approx(35.66)


@pytest.mark.asyncio
async def test_nullable_airports_list_is_valid_for_an_airport_place() -> None:
    value = place(
        "Cleveland Hopkins",
        "CLE",
        latitude=41.41,
        longitude=-81.85,
        place_type="airport",
    )
    assert value["airports"] is None
    client = make_client(lambda _: httpx.Response(200, json={"data": [value]}))
    resolved = await DuffelLocationResolver(client).resolve("CLE")
    await client.aclose()

    assert resolved.iata_codes == ("CLE",)
