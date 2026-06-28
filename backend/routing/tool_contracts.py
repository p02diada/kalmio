from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


TOOL_CONTRACT_CATALOG_ID = "https://kalmio.app/agent/contracts/conversation-tools/v1"
TOOL_CONTRACT_VERSION = "v1"


class ToolContractValidationError(ValueError):
    pass


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocationArg(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(..., min_length=1, max_length=120, description="Etiqueta visible de la ubicación.")
    lat: float = Field(..., ge=-90, le=90, description="Latitud validable, -90 a 90.")
    lon: float = Field(..., ge=-180, le=180, description="Longitud validable, -180 a 180.")

    @model_validator(mode="after")
    def reject_placeholder_coordinates(self) -> "LocationArg":
        if self.lat == 0 and self.lon == 0:
            raise ValueError("Coordenadas placeholder 0,0 no permitidas.")
        return self


class ResolveLocationArgs(ToolModel):
    query: str = Field(..., min_length=1, max_length=240, description="Ciudad, zona, carretera concreta o POI textual.")


class VehicleArg(ToolModel):
    model: str | None = Field(None, max_length=120)
    battery: float | None = Field(None, ge=0, le=100)
    usable_battery_kwh: float | None = Field(None, ge=0.1, le=300)
    consumption_kwh_per_100km: float | None = Field(None, ge=1, le=80)
    connector: str | None = Field(None, max_length=40)
    max_charge_kw: float | None = Field(None, ge=1, le=500)


class PreferencesArg(ToolModel):
    reserve_min_percent: float | None = Field(None, ge=0, le=80)
    prefer_fast: bool | None = None
    prefer_cheap: bool | None = None
    prefer_low_stress: bool | None = None
    prefer_services: bool | None = None
    prefer_large_hubs: bool | None = None
    avoid_single_connector: bool | None = None
    max_useful_power_kw: float | None = Field(None, ge=1, le=500)


class SearchDestinationChargersArgs(ToolModel):
    location: LocationArg
    connector: str | None = Field(None, max_length=40, description="Conector si el usuario lo ha indicado.")
    radius_km: float = Field(80, ge=1, le=100, description="Radio de búsqueda en km.")
    limit: int = Field(3, ge=1, le=6, description="Número máximo de estaciones.")


class PlanRouteArgs(ToolModel):
    origin: LocationArg
    destination: LocationArg
    vehicle: VehicleArg | None = Field(
        None,
        description=(
            "Perfil completo solo si el usuario dio batería, capacidad útil, consumo, conector y potencia máxima. "
            "Con solo modelo comercial o batería de salida, usar null u omitir."
        ),
    )
    preferences: PreferencesArg | None = None
    corridor_radius_km: float = Field(25, ge=1, le=100, description="Radio de corredor en km.")


class ResolvedLocation(ToolModel):
    label: str
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    precision: Literal["known_location", "city_approximation"] | None = None
    query: str | None = None


class ResolveLocationResult(ToolModel):
    ok: bool
    tool: Literal["resolve_location"] | None = None
    location: ResolvedLocation | None = None
    error: str | None = None

    @model_validator(mode="after")
    def require_success_or_error(self) -> "ResolveLocationResult":
        if self.ok and self.location is None:
            raise ValueError("resolve_location ok=true necesita location.")
        if not self.ok and not self.error:
            raise ValueError("resolve_location ok=false necesita error.")
        return self


class StationFact(ToolModel):
    name: str
    stationName: str | None = None
    powerKw: float | None = Field(None, ge=0)
    distanceKm: float | None = Field(None, ge=0)
    detourMin: float | None = None
    connectorTypes: list[str] = Field(default_factory=list)
    availableEvses: int | None = Field(None, ge=0)
    totalEvses: int | None = Field(None, ge=0)
    amenities: list[str] = Field(default_factory=list)
    reliability: float | None = None
    confidence: str | None = None
    scoreReasons: list[str] = Field(default_factory=list)
    address: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    pricePerKwhEur: float | None = Field(None, ge=0)
    currency: str | None = None
    priceIsEstimated: bool | None = None


class SearchDestinationChargersResult(ToolModel):
    ok: bool
    tool: Literal["search_destination_chargers"]
    location: LocationArg
    stops: list[StationFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def require_error_when_empty(self) -> "SearchDestinationChargersResult":
        if self.ok and not self.stops:
            raise ValueError("search_destination_chargers ok=true necesita stops.")
        if not self.ok and not self.error:
            raise ValueError("search_destination_chargers ok=false necesita error.")
        return self


class RouteGeometry(ToolModel):
    type: Literal["LineString"]
    coordinates: list[list[float]]


class PlanRouteResult(ToolModel):
    ok: bool
    tool: Literal["plan_route"]
    planningLevel: Literal["ev_plan", "chargers_only"] | None = None
    origin: LocationArg | None = None
    destination: LocationArg | None = None
    distanceKm: float | None = Field(None, ge=0)
    durationMin: float | None = Field(None, ge=0)
    energyKwh: float | None = Field(None, ge=0)
    arrivalBattery: float | None = Field(None, ge=0, le=100)
    routeGeometry: RouteGeometry | None = None
    corridorRadiusKm: float | None = Field(None, ge=1, le=100)
    recommendation: StationFact | None = None
    alternatives: list[StationFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def require_route_success_fields_or_error(self) -> "PlanRouteResult":
        if self.ok and (
            self.planningLevel is None
            or self.origin is None
            or self.destination is None
            or self.distanceKm is None
            or self.durationMin is None
            or self.recommendation is None
        ):
            raise ValueError("plan_route ok=true necesita ruta, ubicaciones y recomendación.")
        if not self.ok and not self.error:
            raise ValueError("plan_route ok=false necesita error.")
        return self


@dataclass(frozen=True)
class ConversationToolContract:
    name: str
    version: str
    description: str
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    prompt_summary: str

    @property
    def contract_id(self) -> str:
        return f"{TOOL_CONTRACT_CATALOG_ID}/{self.name}"

    def validate_args(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            model = self.args_model.model_validate(value)
        except ValidationError as exc:
            raise ToolContractValidationError(format_validation_error(self.name, "args", exc)) from exc
        return model.model_dump(exclude_none=True)

    def validate_result(self, value: dict[str, Any]) -> dict[str, Any]:
        try:
            model = self.result_model.model_validate(value)
        except ValidationError as exc:
            raise ToolContractValidationError(format_validation_error(self.name, "result", exc)) from exc
        return model.model_dump(exclude_none=True)

    def native_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


def format_validation_error(tool_name: str, side: str, exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "root"
    message = first.get("msg") or str(exc)
    return f"Contrato {TOOL_CONTRACT_VERSION} inválido para {tool_name}.{side}.{loc}: {message}"


CONVERSATION_TOOL_CONTRACTS: dict[str, ConversationToolContract] = {
    "resolve_location": ConversationToolContract(
        name="resolve_location",
        version=TOOL_CONTRACT_VERSION,
        description="Resuelve una ciudad, zona, carretera concreta o POI conocido antes de buscar carga o ruta.",
        args_model=ResolveLocationArgs,
        result_model=ResolveLocationResult,
        prompt_summary='resolve_location(query: string) -> location {label, lat, lon, precision} o error.',
    ),
    "search_destination_chargers": ConversationToolContract(
        name="search_destination_chargers",
        version=TOOL_CONTRACT_VERSION,
        description="Busca puntos de carga autorizados cerca de una ubicación ya resuelta o coordenadas explícitas.",
        args_model=SearchDestinationChargersArgs,
        result_model=SearchDestinationChargersResult,
        prompt_summary=(
            "search_destination_chargers(location {label,lat,lon}, connector?, radius_km=80, limit=3) "
            "-> stops con name/stationName, distanceKm, powerKw, connectorTypes, availableEvses/totalEvses, "
            "amenities, reliability, address, lat/lon y tarifa solo si está verificada."
        ),
    ),
    "plan_route": ConversationToolContract(
        name="plan_route",
        version=TOOL_CONTRACT_VERSION,
        description="Calcula ruta EV con proveedor de rutas y puntos de carga autorizados cuando hay origen y destino.",
        args_model=PlanRouteArgs,
        result_model=PlanRouteResult,
        prompt_summary=(
            "plan_route(origin {label,lat,lon}, destination {label,lat,lon}, vehicle?, preferences?, "
            "corridor_radius_km=25) -> planningLevel, distancia/duración, routeGeometry de proveedor, "
            "recomendación y alternativas trazables."
        ),
    ),
}


def allowed_conversation_tools() -> set[str]:
    return set(CONVERSATION_TOOL_CONTRACTS)


def conversation_tool_contract(tool_name: str) -> ConversationToolContract:
    try:
        return CONVERSATION_TOOL_CONTRACTS[tool_name]
    except KeyError as exc:
        raise ToolContractValidationError(f"Herramienta no registrada en {TOOL_CONTRACT_CATALOG_ID}: {tool_name}") from exc


def conversation_tool_definitions() -> list[dict[str, Any]]:
    return [contract.native_tool_definition() for contract in CONVERSATION_TOOL_CONTRACTS.values()]


def conversation_tool_prompt_summary() -> str:
    lines = [
        f"Contrato de herramientas conversacionales {TOOL_CONTRACT_VERSION} ({TOOL_CONTRACT_CATALOG_ID}).",
        "Puedes llamar solo una herramienta por respuesta tool_call. Shapes completos viven en el contrato versionado; usa este resumen:",
    ]
    for contract in CONVERSATION_TOOL_CONTRACTS.values():
        lines.append(f"- {contract.prompt_summary}")
    return "\n".join(lines) + "\n"


def conversation_tool_trace_metadata(tool_name: str, *, args_valid: bool | None, result_valid: bool | None) -> dict[str, Any]:
    try:
        contract = conversation_tool_contract(tool_name)
    except ToolContractValidationError:
        return {
            "toolContractId": None,
            "toolContractVersion": None,
            "argsValid": args_valid,
            "resultValid": result_valid,
        }
    return {
        "toolContractId": contract.contract_id,
        "toolContractVersion": contract.version,
        "argsValid": args_valid,
        "resultValid": result_valid,
    }
