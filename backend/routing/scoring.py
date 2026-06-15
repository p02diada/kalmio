from dataclasses import dataclass
from typing import Literal

PlanType = Literal["safe", "cheap", "fast", "comfortable"]


@dataclass(frozen=True)
class VehicleContext:
    battery_percent: float
    usable_battery_kwh: float
    consumption_kwh_per_100km: float
    connector: str
    max_charge_kw: float


@dataclass(frozen=True)
class Preferences:
    reserve_min_percent: float
    prefer_fast: bool
    prefer_cheap: bool
    prefer_low_stress: bool
    prefer_services: bool
    prefer_large_hubs: bool
    avoid_single_connector: bool
    max_useful_power_kw: float | None = None


@dataclass(frozen=True)
class StationScore:
    station: dict
    score: float
    reasons: list[str]


def estimate_energy(distance_km: float, vehicle: VehicleContext, safety_factor: float = 1.12) -> float:
    return round(distance_km * vehicle.consumption_kwh_per_100km / 100 * safety_factor, 1)


def score_station(
    station: dict,
    vehicle: VehicleContext,
    preferences: Preferences,
    plan_type: PlanType,
) -> StationScore:
    score = 50.0
    reasons: list[str] = []

    if station["connector"] == vehicle.connector:
        score += 16
        reasons.append("Conector compatible")
    else:
        score -= 100
        reasons.append("Conector incompatible")

    if station["power_kw"] <= vehicle.max_charge_kw * 1.25:
        score += 8
        reasons.append("Potencia compatible")
    if preferences.prefer_fast:
        score += min(station["power_kw"], vehicle.max_charge_kw) / 25
        reasons.append("Potencia ponderada")

    available_connectors = station["available_connectors"]
    connector_count = station.get("connector_count", available_connectors)
    if available_connectors > 0:
        score += min(available_connectors, 6) * 2
        reasons.append("Disponibilidad declarada")
    else:
        score -= 15
        reasons.append("Sin disponibilidad confirmada")

    if connector_count <= 1 and preferences.avoid_single_connector:
        score -= 12
        reasons.append("Pocos conectores")
    if connector_count >= 4 and preferences.prefer_large_hubs:
        score += 6
        reasons.append("Hub grande")

    age = station["availability_age_min"]
    if age is None:
        score -= 6
        reasons.append("Disponibilidad sin marca temporal")
    elif age <= 30:
        score += 10
        reasons.append("Disponibilidad reciente")
    elif age > 60:
        score -= 8
        reasons.append("Dato antiguo")
    if preferences.prefer_low_stress:
        score += station["reliability"] / 12
        if connector_count >= 4:
            score += 4
        reasons.append("Margen conservador")

    score -= station["detour_min"] * (1.2 if plan_type == "fast" else 0.7)

    price = station["price_eur_kwh"]
    if (preferences.prefer_cheap or plan_type == "cheap") and price is not None:
        score -= price * 16
        reasons.append("Precio ponderado")

    if preferences.prefer_services or plan_type == "comfortable":
        service_bonus = 5 * len(station["services"])
        score += service_bonus
        reasons.append("Servicios cercanos")

    return StationScore(station=station, score=round(score, 2), reasons=reasons)
