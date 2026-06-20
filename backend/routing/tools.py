from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from charging.selectors import get_nearby_stations
from routing.production_planner import PlanningDataError, plan_route_with_persisted_stations
from routing.providers import Coordinate, ProviderRoute, RoutingProviderError, get_route_provider
from routing.scoring import Preferences, VehicleContext


KNOWN_LOCATIONS = {
    "madrid": ("Madrid", 40.4168, -3.7038),
    "valencia": ("Valencia", 39.4699, -0.3763),
    "cordoba": ("Córdoba", 37.8882, -4.7794),
    "sevilla": ("Sevilla", 37.3891, -5.9845),
    "barcelona": ("Barcelona", 41.3874, 2.1686),
    "malaga": ("Málaga", 36.7213, -4.4214),
    "granada": ("Granada", 37.1773, -3.5986),
    "alicante": ("Alicante", 38.3452, -0.4810),
    "bilbao": ("Bilbao", 43.2630, -2.9350),
    "zaragoza": ("Zaragoza", 41.6488, -0.8891),
    "cadiz": ("Cádiz", 36.5271, -6.2886),
    "alhambra": ("Alhambra, Granada", 37.1761, -3.5881),
    "almansa": ("Almansa", 38.8690, -1.0971),
    "alcobendas": ("Alcobendas", 40.5317, -3.6419),
    "alcora": ("Alcora", 39.1230, -0.5025),
}
ALLOWED_CONVERSATION_TOOLS = {"resolve_location", "search_destination_chargers", "plan_route"}


class ConversationToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


def execute_conversation_tool(call: ToolCall) -> dict[str, Any]:
    if call.name == "resolve_location":
        return resolve_location_tool(call.args)
    if call.name == "search_destination_chargers":
        return search_destination_chargers_tool(call.args)
    if call.name == "plan_route":
        return plan_route_tool(call.args)
    raise ConversationToolError(f"Herramienta no permitida: {call.name}")


def resolve_location_tool(args: dict[str, Any]) -> dict[str, Any]:
    raw_query = str(args.get("query") or "").strip()
    query = normalize_location_query(raw_query)
    for key, (label, lat, lon) in KNOWN_LOCATIONS.items():
        if key in query:
            return {
                "ok": True,
                "location": {
                    "label": label,
                    "lat": lat,
                    "lon": lon,
                    "precision": location_resolution_precision(query, key),
                    "query": raw_query,
                },
            }
    return {"ok": False, "error": "No conozco esa ubicación. Pide ciudad o coordenadas exactas."}


def normalize_location_query(value: str) -> str:
    substitutions = str.maketrans("áéíóúüñ", "aeiouun")
    return value.lower().translate(substitutions)


def location_resolution_precision(query: str, matched_key: str) -> str:
    if query.strip(" .,") == matched_key:
        return "known_location"
    if any(term in query for term in ("hotel", "calle", "paseo", "avenida", "plaza", "melia", "alhambra", "atocha")):
        return "city_approximation"
    return "known_location"


def search_destination_chargers_tool(args: dict[str, Any]) -> dict[str, Any]:
    location = parse_location_arg(args.get("location"))
    connector = clean_optional_string(args.get("connector"))
    radius_km = bounded_float(args.get("radius_km"), default=80, minimum=1, maximum=100)
    limit = int(bounded_float(args.get("limit"), default=3, minimum=1, maximum=6))

    stations = get_nearby_stations(
        lat=location["lat"],
        lon=location["lon"],
        radius_km=radius_km,
        connector=connector,
        available_only=False,
    )
    stops = [
        {
            "name": item.station.name,
            "stationName": item.station.name,
            "powerKw": item.max_power_kw,
            "distanceKm": item.distance_km,
            "connectorTypes": item.connector_types,
            "availableEvses": item.available_evses,
            "amenities": item.station.amenities,
            "reliability": item.station.reliability.score if hasattr(item.station, "reliability") else None,
            "address": item.station.address,
            "lat": float(item.station.latitude),
            "lon": float(item.station.longitude),
            **station_tariff_payload(item.station),
        }
        for item in stations[:limit]
    ]
    return {
        "ok": bool(stops),
        "tool": "search_destination_chargers",
        "location": location,
        "stops": stops,
        "warnings": [
            "Datos procedentes solo de puntos de carga autorizados importados.",
            "Confirma acceso final, tarifa y disponibilidad antes de depender de ellos.",
        ],
        "error": None if stops else "No hay puntos de carga autorizados importados cerca de esa ubicación.",
    }


def plan_route_tool(args: dict[str, Any]) -> dict[str, Any]:
    origin = parse_location_arg(args.get("origin"))
    destination = parse_location_arg(args.get("destination"))
    vehicle = parse_vehicle_arg(args.get("vehicle"))
    preferences = parse_preferences_arg(args.get("preferences"))
    corridor_radius_km = bounded_float(args.get("corridor_radius_km"), default=25, minimum=1, maximum=100)

    try:
        route = get_route_provider().route(
            Coordinate(lat=origin["lat"], lon=origin["lon"]),
            Coordinate(lat=destination["lat"], lon=destination["lon"]),
        )
        plan = plan_route_with_persisted_stations(
            origin=Coordinate(lat=origin["lat"], lon=origin["lon"]),
            destination=Coordinate(lat=destination["lat"], lon=destination["lon"]),
            route=route,
            vehicle=vehicle,
            preferences=preferences,
            corridor_radius_km=corridor_radius_km,
        )
    except (RoutingProviderError, PlanningDataError) as exc:
        return {"ok": False, "tool": "plan_route", "error": str(exc)}

    recommendation = station_score_payload(plan.recommendation)
    return {
        "ok": True,
        "tool": "plan_route",
        "planningLevel": plan.planning_level,
        "origin": origin,
        "destination": destination,
        "distanceKm": round(plan.route.distance_km, 1),
        "durationMin": plan.route.duration_min,
        "energyKwh": round(plan.energy_kwh, 1) if plan.energy_kwh is not None else None,
        "arrivalBattery": round(plan.arrival_battery_percent, 1) if plan.arrival_battery_percent is not None else None,
        "routeGeometry": route_geometry_payload(plan.route),
        "corridorRadiusKm": corridor_radius_km,
        "recommendation": recommendation,
        "alternatives": [station_score_payload(item) for item in plan.alternatives],
        "warnings": plan.warnings,
    }


def route_geometry_payload(route: ProviderRoute) -> dict[str, Any]:
    return {
        "type": "LineString",
        "coordinates": [[point.lon, point.lat] for point in route.geometry],
    }


def station_score_payload(score) -> dict[str, Any]:
    payload = {
        "name": score.station["name"],
        "stationName": score.station["name"],
        "powerKw": score.station["power_kw"],
        "distanceKm": score.station["distance_to_route_km"],
        "detourMin": score.station["detour_min"],
        "confidence": "media",
        "availableEvses": score.station.get("available_connectors"),
        "connectorCount": score.station.get("connector_count"),
        "amenities": score.station.get("services", []),
        "reliability": score.station.get("reliability"),
        "scoreReasons": score.reasons,
        "lat": score.station["lat"],
        "lon": score.station["lon"],
        "priceIsEstimated": score.station.get("price_is_estimated"),
    }
    if score.station.get("price_eur_kwh") is not None and score.station.get("price_is_estimated") is not True:
        payload["pricePerKwhEur"] = score.station.get("price_eur_kwh")
        payload["currency"] = "EUR"
    return payload


def station_tariff_payload(station) -> dict[str, Any]:
    tariff = station.tariffs.first()
    if not tariff:
        return {}
    payload: dict[str, Any] = {"priceIsEstimated": tariff.is_estimated}
    if not tariff.is_estimated:
        payload["pricePerKwhEur"] = float(tariff.price_per_kwh)
        payload["currency"] = tariff.currency
    return payload


def parse_location_arg(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConversationToolError("La herramienta necesita una ubicación estructurada.")
    raw_label = value.get("label")
    label = str(raw_label or "Ubicación indicada").strip()[:120]
    lat = bounded_float(value.get("lat"), default=None, minimum=-90, maximum=90)
    lon = bounded_float(value.get("lon"), default=None, minimum=-180, maximum=180)
    if lat is None or lon is None:
        raise ConversationToolError("La herramienta necesita latitud y longitud válidas.")
    if lat == 0 and lon == 0:
        raise ConversationToolError("La herramienta recibió coordenadas placeholder 0,0; pide origen o destino reales.")
    if raw_label is not None and not str(raw_label).strip():
        raise ConversationToolError("La herramienta necesita una etiqueta de ubicación real, no vacía.")
    return {"label": label, "lat": lat, "lon": lon}


def parse_vehicle_arg(value: Any) -> VehicleContext | None:
    if not isinstance(value, dict):
        return None
    battery = bounded_float(value.get("battery"), default=None, minimum=0, maximum=100)
    usable_battery_kwh = bounded_float(value.get("usable_battery_kwh"), default=None, minimum=0.1, maximum=300)
    consumption_kwh_per_100km = bounded_float(
        value.get("consumption_kwh_per_100km"),
        default=None,
        minimum=1,
        maximum=80,
    )
    connector = str(value.get("connector") or "").strip()[:40]
    max_charge_kw = bounded_float(value.get("max_charge_kw"), default=None, minimum=1, maximum=500)
    if (
        battery is None
        or usable_battery_kwh is None
        or consumption_kwh_per_100km is None
        or not connector
        or max_charge_kw is None
    ):
        return None
    return VehicleContext(
        battery_percent=battery,
        usable_battery_kwh=usable_battery_kwh,
        consumption_kwh_per_100km=consumption_kwh_per_100km,
        connector=connector,
        max_charge_kw=max_charge_kw,
    )


def parse_preferences_arg(value: Any) -> Preferences:
    data = value if isinstance(value, dict) else {}
    return Preferences(
        reserve_min_percent=bounded_float(data.get("reserve_min_percent"), default=20, minimum=0, maximum=80) or 20,
        prefer_fast=bool(data.get("prefer_fast", False)),
        prefer_cheap=bool(data.get("prefer_cheap", False)),
        prefer_low_stress=bool(data.get("prefer_low_stress", True)),
        avoid_single_connector=bool(data.get("avoid_single_connector", True)),
        prefer_services=bool(data.get("prefer_services", True)),
        prefer_large_hubs=bool(data.get("prefer_large_hubs", True)),
        max_useful_power_kw=bounded_float(data.get("max_useful_power_kw"), default=None, minimum=1, maximum=500),
    )


def clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:40] if text else None


def bounded_float(value: Any, *, default: float | None, minimum: float, maximum: float) -> float | None:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConversationToolError("Argumento numérico inválido.") from exc
    if number < minimum or number > maximum:
        raise ConversationToolError(f"Argumento numérico fuera de rango [{minimum}, {maximum}].")
    return number
