"""Typed projections of LiteAPI v3 rates; unused provider fields are ignored."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
)


def _number(value: object) -> Decimal:
    """Require a JSON number, excluding booleans and non-finite values."""

    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float)):
        raise ValueError("expected a JSON monetary number")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("expected a finite monetary number")
    return number


Amount = Annotated[Decimal, BeforeValidator(_number), Field(gt=0, le=1_000_000_000)]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=200)]


class ProviderModel(BaseModel):
    """Tolerate vendor additions while strictly validating every consumed field."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Money(ProviderModel):
    """One exact offer/rate amount and ISO currency code."""

    amount: Amount
    currency: str = Field(strict=True, pattern=r"^[A-Z]{3}$")


class TaxOrFee(ProviderModel):
    """Consume only the included flag; never copy unbounded provider remarks."""

    included: StrictBool


class RetailRate(ProviderModel):
    """Single-room total, with an optional fee disclosure list."""

    total: list[Money] = Field(min_length=1)
    taxesAndFees: list[TaxOrFee] | None = None


class CancellationPolicy(ProviderModel):
    """Keep only the provider's refundable classification, not executable policy text."""

    refundableTag: Literal["RFN", "NRFN"] | None = None


class Rate(ProviderModel):
    """One room rate; occupancy and booking identifiers remain outside the domain."""

    retailRate: RetailRate
    adultCount: StrictInt | None = Field(default=None, ge=1)
    childCount: StrictInt | None = Field(default=None, ge=0)
    name: Text | None = None
    boardName: Text | None = None
    cancellationPolicies: CancellationPolicy | None = None


class Offer(ProviderModel):
    """One offer grouping rates; P17 accepts exactly one room."""

    rates: list[Rate] = Field(min_length=1)
    offerRetailRate: Money | None = None


class HotelRates(ProviderModel):
    """Rates joined to hotel metadata using the property ID."""

    hotelId: Text
    roomTypes: list[Offer]


class Coordinates(ProviderModel):
    """Optional provider-backed coordinates, never inferred."""

    latitude: StrictFloat = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: StrictFloat = Field(ge=-180, le=180, allow_inf_nan=False)


class HotelDetails(ProviderModel):
    """Bounded hotel display fields from the top-level hotels array."""

    id: Text
    name: Text
    starRating: StrictFloat | None = Field(default=None, ge=0, le=5, allow_inf_nan=False)
    rating: StrictFloat | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)
    hotelFacilities: list[Text] | None = None
    location: Coordinates | None = None


class HotelRatesResponse(ProviderModel):
    """Documented rates envelope, including optional environment attestation."""

    data: list[HotelRates]
    hotels: list[HotelDetails] = Field(default_factory=list)
    sandbox: StrictBool | None = None
