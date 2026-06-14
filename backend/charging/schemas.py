from ninja import Schema


class StationSummary(Schema):
    id: int
    external_id: str
    name: str
    operator: str
    latitude: float
    longitude: float
    distance_km: float | None = None
    max_power_kw: int
    connector_types: list[str]
    available_evses: int
    price_per_kwh: float | None = None
    currency: str = "EUR"
    amenities: list[str]
    reliability_score: int | None = None


class StationDetail(StationSummary):
    address: str
    evses: list[dict]
    warnings: list[str]
