from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.utils import timezone

from charging.models import Station
from charging.selectors import haversine_km, stations_queryset
from routing.providers import Coordinate, ProviderRoute
from routing.scoring import PlanType, Preferences, StationScore, VehicleContext, estimate_energy, score_station

PlanningLevel = Literal["ev_plan", "chargers_only"]


@dataclass(frozen=True)
class ProductionPlanResult:
    planning_level: PlanningLevel
    plan_type: PlanType
    route: ProviderRoute
    recommendation: StationScore
    alternatives: list[StationScore]
    energy_kwh: float | None
    arrival_battery_percent: float | None
    warnings: list[str]


class PlanningDataError(RuntimeError):
    pass


def plan_route_with_persisted_stations(
    *,
    origin: Coordinate,
    destination: Coordinate,
    route: ProviderRoute,
    vehicle: VehicleContext | None,
    preferences: Preferences,
    plan_type: PlanType = "safe",
    corridor_radius_km: float = 25,
    limit: int = 3,
) -> ProductionPlanResult:
    if vehicle is None:
        candidates = score_chargers_near_route(
            route=route,
            preferences=preferences,
            plan_type=plan_type,
            corridor_radius_km=corridor_radius_km,
        )
        if not candidates:
            raise PlanningDataError("No hay estaciones autorizadas cargadas cerca del corredor de ruta.")

        return ProductionPlanResult(
            planning_level="chargers_only",
            plan_type=plan_type,
            route=route,
            recommendation=candidates[0],
            alternatives=candidates[1:limit],
            energy_kwh=None,
            arrival_battery_percent=None,
            warnings=[
                "Sin datos de autonomía, solo mostramos cargadores en ruta. No calculamos llegada estimada ni paradas óptimas.",
            ],
        )

    energy_kwh = estimate_energy(route.distance_km, vehicle)
    available_kwh = vehicle.usable_battery_kwh * vehicle.battery_percent / 100
    reserve_kwh = vehicle.usable_battery_kwh * preferences.reserve_min_percent / 100
    arrival_battery = round(max(0, (available_kwh - energy_kwh) / vehicle.usable_battery_kwh * 100), 1)
    warnings: list[str] = []

    if available_kwh - energy_kwh < reserve_kwh:
        warnings.append("La ruta completa necesita carga para respetar la reserva mínima.")

    candidates = score_persisted_stations(
        route=route,
        vehicle=vehicle,
        preferences=preferences,
        plan_type=plan_type,
        corridor_radius_km=corridor_radius_km,
    )
    if not candidates:
        raise PlanningDataError("No hay estaciones compatibles cargadas cerca del corredor de ruta.")

    return ProductionPlanResult(
        planning_level="ev_plan",
        plan_type=plan_type,
        route=route,
        recommendation=candidates[0],
        alternatives=candidates[1:limit],
        energy_kwh=energy_kwh,
        arrival_battery_percent=arrival_battery,
        warnings=warnings,
    )


def score_persisted_stations(
    *,
    route: ProviderRoute,
    vehicle: VehicleContext,
    preferences: Preferences,
    plan_type: PlanType,
    corridor_radius_km: float,
) -> list[StationScore]:
    sampled_route = sample_route_points(route.geometry)
    scored: list[StationScore] = []

    for station in stations_queryset().filter(
        evses__connectors__connector_type__iexact=vehicle.connector,
        evses__max_power_kw__gte=max(1, int(vehicle.max_charge_kw * 0.35)),
    ):
        distance_to_route = min(
            haversine_km(point.lat, point.lon, float(station.latitude), float(station.longitude))
            for point in sampled_route
        )
        if distance_to_route > corridor_radius_km:
            continue

        candidate = station_to_score_payload(station, vehicle.connector, distance_to_route)
        scored.append(score_station(candidate, vehicle, preferences, plan_type))

    return sorted(scored, key=lambda item: item.score, reverse=True)


def score_chargers_near_route(
    *,
    route: ProviderRoute,
    preferences: Preferences,
    plan_type: PlanType,
    corridor_radius_km: float,
) -> list[StationScore]:
    sampled_route = sample_route_points(route.geometry)
    scored: list[StationScore] = []

    for station in stations_queryset():
        distance_to_route = min(
            haversine_km(point.lat, point.lon, float(station.latitude), float(station.longitude))
            for point in sampled_route
        )
        if distance_to_route > corridor_radius_km:
            continue

        candidate = station_to_exploration_payload(station, distance_to_route)
        scored.append(score_exploration_station(candidate, preferences, plan_type))

    return sorted(scored, key=lambda item: item.score, reverse=True)


def station_to_exploration_payload(station: Station, distance_to_route_km: float) -> dict:
    evses = list(station.evses.all())
    connectors = [connector_obj for evse in evses for connector_obj in evse.connectors.all()]
    tariff = station.tariffs.first()
    available_evses = [evse for evse in evses if evse.status == "available"]
    max_power_kw = max((connector_obj.max_power_kw for connector_obj in connectors), default=0)
    reliability_score = station.reliability.score if hasattr(station, "reliability") else 50
    connector_type = strongest_connector_type(connectors)

    return {
        "id": station.id,
        "name": station.name,
        "connector": connector_type,
        "power_kw": max_power_kw,
        "available_connectors": len(available_evses),
        "connector_count": len(evses),
        "availability_age_min": latest_availability_age_min(evses),
        "reliability": reliability_score,
        "detour_min": estimated_access_minutes(distance_to_route_km),
        "price_eur_kwh": float(tariff.price_per_kwh) if tariff else None,
        "services": station.amenities,
        "lat": float(station.latitude),
        "lon": float(station.longitude),
        "external_id": station.external_id,
        "distance_to_route_km": round(distance_to_route_km, 2),
        "price_is_estimated": tariff.is_estimated if tariff else True,
    }


def score_exploration_station(station: dict, preferences: Preferences, plan_type: PlanType) -> StationScore:
    score = 45.0
    reasons = ["Cargador en el corredor"]
    effective_power_kw = min(station["power_kw"], preferences.max_useful_power_kw or station["power_kw"])

    if effective_power_kw >= 150:
        score += 10
        reasons.append("Alta potencia")
    elif effective_power_kw >= 50:
        score += 5
        reasons.append("Carga rápida")
    if preferences.max_useful_power_kw and station["power_kw"] > preferences.max_useful_power_kw * 1.25:
        reasons.append("Potencia por encima del máximo útil no sobreponderada")

    available_connectors = station["available_connectors"]
    connector_count = station.get("connector_count", available_connectors)
    if available_connectors > 0:
        score += min(available_connectors, 6) * 2
        reasons.append("Disponibilidad declarada")
    else:
        score -= 12
        reasons.append("Sin disponibilidad confirmada")

    if connector_count <= 1 and preferences.avoid_single_connector:
        score -= 8
        reasons.append("Pocos puntos de carga")
    if connector_count >= 4 and preferences.prefer_large_hubs:
        score += 6
        reasons.append("Hub grande")

    age = station["availability_age_min"]
    if age is None:
        score -= 5
        reasons.append("Disponibilidad sin marca temporal")
    elif age <= 30:
        score += 8
        reasons.append("Disponibilidad reciente")
    elif age > 60:
        score -= 6
        reasons.append("Dato antiguo")

    if preferences.prefer_low_stress:
        score += station["reliability"] / 14
        reasons.append("Fiabilidad ponderada")

    score -= station["detour_min"] * (1.2 if plan_type == "fast" else 0.7)

    price = station["price_eur_kwh"]
    if (preferences.prefer_cheap or plan_type == "cheap") and price is not None:
        score -= price * 10
        reasons.append("Precio ponderado")

    if preferences.prefer_services or plan_type == "comfortable":
        score += 4 * len(station["services"])
        reasons.append("Servicios cercanos")

    return StationScore(station=station, score=round(score, 2), reasons=reasons)


def strongest_connector_type(connectors: list) -> str:
    if not connectors:
        return "unknown"
    strongest = max(connectors, key=lambda connector: connector.max_power_kw)
    return strongest.connector_type


def station_to_score_payload(station: Station, connector: str, distance_to_route_km: float) -> dict:
    evses = list(station.evses.all())
    connectors = [connector_obj for evse in evses for connector_obj in evse.connectors.all()]
    matching_connectors = [
        connector_obj for connector_obj in connectors if connector_obj.connector_type.upper() == connector.upper()
    ]
    matching_evses = [
        evse
        for evse in evses
        if any(connector_obj.connector_type.upper() == connector.upper() for connector_obj in evse.connectors.all())
    ]
    tariff = station.tariffs.first()

    available_evses = [evse for evse in matching_evses if evse.status == "available"]
    max_power_kw = max((connector_obj.max_power_kw for connector_obj in matching_connectors), default=0)
    reliability_score = station.reliability.score if hasattr(station, "reliability") else 50

    return {
        "id": station.id,
        "name": station.name,
        "connector": connector,
        "power_kw": max_power_kw,
        "available_connectors": len(available_evses),
        "connector_count": len(matching_evses),
        "availability_age_min": latest_availability_age_min(matching_evses),
        "reliability": reliability_score,
        "detour_min": estimated_access_minutes(distance_to_route_km),
        "price_eur_kwh": float(tariff.price_per_kwh) if tariff else None,
        "services": station.amenities,
        "lat": float(station.latitude),
        "lon": float(station.longitude),
        "external_id": station.external_id,
        "distance_to_route_km": round(distance_to_route_km, 2),
        "price_is_estimated": tariff.is_estimated if tariff else True,
    }


def latest_availability_age_min(evses: list) -> int | None:
    latest_observed_at = None
    for evse in evses:
        for snapshot in evse.availability_snapshots.all():
            if latest_observed_at is None or snapshot.observed_at > latest_observed_at:
                latest_observed_at = snapshot.observed_at

    if latest_observed_at is None:
        return None

    return max(0, round((timezone.now() - latest_observed_at).total_seconds() / 60))


def sample_route_points(points: list[Coordinate], max_points: int = 40) -> list[Coordinate]:
    if not points:
        raise PlanningDataError("La ruta no incluye geometría para buscar estaciones.")
    if len(points) <= max_points:
        return points

    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def estimated_access_minutes(distance_to_route_km: float) -> int:
    return round(distance_to_route_km * 2.4)
