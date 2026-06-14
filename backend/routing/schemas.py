from datetime import datetime

from ninja import Field, Schema


class CoordinateSchema(Schema):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class RoutePlanRequest(Schema):
    origin: CoordinateSchema
    destination: CoordinateSchema
    origin_label: str = Field("Origen", min_length=1, max_length=160)
    destination_label: str = Field("Destino", min_length=1, max_length=160)
    corridor_radius_km: float = Field(25, gt=0, le=100)


class RoutePlanVehicle(Schema):
    model: str = Field(..., min_length=1, max_length=120)
    battery: float = Field(..., ge=0, le=100)
    usable_battery_kwh: float = Field(..., gt=0)
    consumption_kwh_per_100km: float = Field(..., gt=0)
    connector: str = Field(..., min_length=1, max_length=40)
    max_charge_kw: float = Field(..., gt=0)


class RoutePlanPreferences(Schema):
    reserve_min_percent: float = Field(20, ge=0, le=80)
    prefer_fast: bool = False
    prefer_cheap: bool = False
    prefer_low_stress: bool = True
    avoid_single_connector: bool = True
    prefer_services: bool = True
    prefer_large_hubs: bool = True


class ConversationRoutePlanRequest(RoutePlanRequest):
    vehicle: RoutePlanVehicle | None = None
    preferences: RoutePlanPreferences = Field(default_factory=RoutePlanPreferences)


class ConversationMessageRequest(Schema):
    text: str = Field(..., min_length=1, max_length=1200)


class A2UIBlock(Schema):
    id: str = Field(..., min_length=1, max_length=120)
    type: str = Field(..., min_length=1, max_length=80)
    version: int = Field(1, ge=1)
    props: dict


class ConversationMessageResponse(Schema):
    blocks: list[A2UIBlock]


class RoutePlanStation(Schema):
    id: int
    external_id: str
    name: str
    power_kw: int
    connector: str
    available_connectors: int
    distance_to_route_km: float
    estimated_access_min: int
    price_eur_kwh: float | None = None
    price_is_estimated: bool
    latitude: float
    longitude: float
    score: float
    reasons: list[str]


class RoutePlanResponse(Schema):
    id: str | None = None
    created_at: datetime | None = None
    planning_level: str
    origin_label: str
    destination_label: str
    distance_km: float
    duration_min: int
    energy_kwh: float | None = None
    arrival_battery_percent: float | None = None
    recommendation: RoutePlanStation
    alternatives: list[RoutePlanStation]
    warnings: list[str]


class RoutePlanError(Schema):
    detail: str
