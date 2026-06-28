from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


EVIDENCE_LEDGER_CONTRACT_ID = "https://kalmio.app/agent/contracts/tool-evidence-ledger/v1"
EVIDENCE_LEDGER_CONTRACT_VERSION = "v1"


class StationEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    powerKw: float | None = None
    distanceKm: float | None = None
    detourMin: float | None = None
    confidence: str | None = None
    lat: float | None = None
    lon: float | None = None
    availableEvses: float | int | None = None
    totalEvses: float | int | None = None
    connectorTypes: list[Any] | None = None
    pricePerKwhEur: float | None = None
    currency: str | None = None
    priceIsEstimated: bool | None = None
    amenities: list[Any] | None = None
    address: str | None = None


class LocationEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str
    lat: float
    lon: float


class ApproximateLocationEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str
    resolvedLabel: str


class RouteEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")


class ToolFactLedger(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_id: str = EVIDENCE_LEDGER_CONTRACT_ID
    contract_version: str = EVIDENCE_LEDGER_CONTRACT_VERSION
    stations: dict[str, StationEvidence] = Field(default_factory=dict)
    locations: list[LocationEvidence] = Field(default_factory=list)
    approximateLocations: list[ApproximateLocationEvidence] = Field(default_factory=list)
    routes: list[dict[str, Any]] = Field(default_factory=list)
    routePreferences: list[dict[str, Any]] = Field(default_factory=list)
    vehicle: dict[str, Any] = Field(default_factory=dict)
    stationSearches: int = 0

    @classmethod
    def from_policy_facts(cls, facts: dict[str, Any]) -> "ToolFactLedger":
        stations = {
            str(key): StationEvidence.model_validate(value)
            for key, value in (facts.get("stations") or {}).items()
            if isinstance(value, dict) and value.get("name")
        }
        locations = [
            LocationEvidence.model_validate(value)
            for value in facts.get("locations") or []
            if isinstance(value, dict) and value.get("lat") is not None and value.get("lon") is not None
        ]
        approximate_locations = [
            ApproximateLocationEvidence.model_validate(value)
            for value in facts.get("approximateLocations") or []
            if isinstance(value, dict) and value.get("query") and value.get("resolvedLabel")
        ]
        routes = [value for value in facts.get("routes") or [] if isinstance(value, dict)]
        route_preferences = [value for value in facts.get("routePreferences") or [] if isinstance(value, dict)]
        vehicle = facts.get("vehicle") if isinstance(facts.get("vehicle"), dict) else {}
        return cls(
            stations=stations,
            locations=locations,
            approximateLocations=approximate_locations,
            routes=routes,
            routePreferences=route_preferences,
            vehicle=dict(vehicle),
            stationSearches=int(facts.get("stationSearches") or 0),
        )

    def as_policy_facts(self) -> dict[str, Any]:
        return {
            "stations": {
                key: value.model_dump(exclude_none=True)
                for key, value in self.stations.items()
            },
            "locations": [value.model_dump(exclude_none=True) for value in self.locations],
            "approximateLocations": [
                value.model_dump(exclude_none=True)
                for value in self.approximateLocations
            ],
            "routes": self.routes,
            "routePreferences": self.routePreferences,
            "vehicle": self.vehicle,
            "stationSearches": self.stationSearches,
        }


def build_tool_fact_ledger(
    tool_history: list[dict[str, Any]],
    *,
    history_blocks: list[dict] | None = None,
) -> ToolFactLedger:
    from routing.agent import tool_fact_index

    return ToolFactLedger.from_policy_facts(
        tool_fact_index(tool_history, history_blocks=history_blocks or [])
    )
