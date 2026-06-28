from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from charging.selectors import get_nearby_stations
from django.utils import timezone
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
CHARGER_SEARCH_PURPOSES = {"urgent", "destination", "stay", "near_route_fallback"}
DEFAULT_RADIUS_BY_PURPOSE = {
    "urgent": 25,
    "destination": 80,
    "stay": 80,
    "near_route_fallback": 60,
}


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
    purpose = parse_charger_search_purpose(args.get("purpose"))
    connector = clean_optional_string(args.get("connector"))
    radius_km = bounded_float(
        args.get("radius_km"),
        default=DEFAULT_RADIUS_BY_PURPOSE[purpose],
        minimum=1,
        maximum=100,
    )
    limit = int(bounded_float(args.get("limit"), default=3, minimum=1, maximum=6))
    requested_services = parse_string_list_arg(args.get("requested_services"), max_items=8)
    max_useful_power_kw = bounded_float(args.get("max_useful_power_kw"), default=None, minimum=1, maximum=500)
    require_verified_price = bool(args.get("require_verified_price", False))
    min_total_evses = bounded_float(args.get("min_total_evses"), default=None, minimum=1, maximum=50)
    allow_unvalidated_safety = bool(args.get("allow_unvalidated_safety", True))
    max_data_age_days = bounded_float(args.get("max_data_age_days"), default=None, minimum=0, maximum=3650)
    require_access_notes = bool(args.get("require_access_notes", False))

    stations = get_nearby_stations(
        lat=location["lat"],
        lon=location["lon"],
        radius_km=radius_km,
        connector=connector,
        available_only=False,
    )
    candidates = [
        station_search_payload(
            item,
            purpose=purpose,
            requested_services=requested_services,
            max_useful_power_kw=max_useful_power_kw,
        )
        for item in stations
    ]
    candidates.sort(key=lambda station: station["rankingScore"], reverse=True)
    stops = [
        candidate
        for candidate in candidates
        if station_matches_search_filters(
            candidate,
            requested_services=requested_services,
            require_verified_price=require_verified_price,
            min_total_evses=int(min_total_evses) if min_total_evses is not None else None,
            allow_unvalidated_safety=allow_unvalidated_safety,
            max_data_age_days=max_data_age_days,
            require_access_notes=require_access_notes,
        )
    ][:limit]
    return {
        "ok": bool(stops),
        "tool": "search_destination_chargers",
        "purpose": purpose,
        "location": location,
        "stops": stops,
        "filtersApplied": {
            "connector": connector,
            "radiusKm": radius_km,
            "requestedServices": requested_services,
            "maxUsefulPowerKw": max_useful_power_kw,
            "requireVerifiedPrice": require_verified_price,
            "minTotalEvses": int(min_total_evses) if min_total_evses is not None else None,
            "allowUnvalidatedSafety": allow_unvalidated_safety,
            "maxDataAgeDays": max_data_age_days,
            "requireAccessNotes": require_access_notes,
        },
        "warnings": [
            "Datos procedentes solo de puntos de carga autorizados importados.",
            "Confirma acceso final, tarifa, seguridad del entorno y disponibilidad antes de depender de ellos.",
        ],
        "error": None if stops else "No hay puntos de carga autorizados importados que cumplan la búsqueda cerca de esa ubicación.",
    }


def station_search_payload(
    item,
    *,
    purpose: str,
    requested_services: list[str],
    max_useful_power_kw: float | None,
) -> dict[str, Any]:
    station = item.station
    total_evses = len(list(station.evses.all()))
    effective_power_kw = min(item.max_power_kw, max_useful_power_kw) if max_useful_power_kw else item.max_power_kw
    tariff_payload = station_tariff_payload(station)
    freshness_payload = station_freshness_payload(station)
    access_notes = station_access_notes(station)
    safety_validated = False
    score, reasons = rank_station_for_search(
        purpose=purpose,
        distance_km=item.distance_km,
        power_kw=effective_power_kw,
        power_was_capped=max_useful_power_kw is not None and effective_power_kw < item.max_power_kw,
        available_evses=item.available_evses,
        total_evses=total_evses,
        amenities=station.amenities,
        requested_services=requested_services,
        verified_price="pricePerKwhEur" in tariff_payload,
        reliability=station.reliability.score if hasattr(station, "reliability") else None,
    )
    return {
        "name": station.name,
        "stationName": station.name,
        "powerKw": item.max_power_kw,
        "effectivePowerKw": effective_power_kw,
        "distanceKm": item.distance_km,
        "connectorTypes": item.connector_types,
        "availableEvses": item.available_evses,
        "totalEvses": total_evses,
        "amenities": station.amenities,
        "reliability": station.reliability.score if hasattr(station, "reliability") else None,
        "address": station.address,
        "lat": float(station.latitude),
        "lon": float(station.longitude),
        "safetyValidated": safety_validated,
        "accessNotes": access_notes["notes"],
        "accessNotesVerified": access_notes["verified"],
        "freshness": freshness_payload,
        "rankingScore": round(score, 3),
        "rankingReasons": reasons,
        **tariff_payload,
    }


def rank_station_for_search(
    *,
    purpose: str,
    distance_km: float,
    power_kw: float,
    power_was_capped: bool,
    available_evses: int,
    total_evses: int,
    amenities: list[str],
    requested_services: list[str],
    verified_price: bool,
    reliability: int | None,
) -> tuple[float, list[str]]:
    weights = {
        "urgent": {"distance": 3.0, "power": 1.3, "hub": 1.4, "services": 0.3, "price": 0.2, "reliability": 0.7},
        "destination": {"distance": 1.9, "power": 0.8, "hub": 0.8, "services": 1.5, "price": 0.8, "reliability": 0.7},
        "stay": {"distance": 1.4, "power": 0.7, "hub": 1.2, "services": 1.7, "price": 0.9, "reliability": 0.8},
        "near_route_fallback": {"distance": 1.5, "power": 1.0, "hub": 1.5, "services": 0.7, "price": 0.5, "reliability": 0.8},
    }[purpose]
    service_matches = len(set(normalized_service_codes(amenities)) & set(requested_services))
    service_denominator = max(len(requested_services), 1)
    service_score = service_matches / service_denominator if requested_services else min(len(amenities), 3) / 3
    score = (
        weights["distance"] * max(0, 1 - min(distance_km, 50) / 50)
        + weights["power"] * min(power_kw, 250) / 250
        + weights["hub"] * min(total_evses, 8) / 8
        + weights["services"] * service_score
        + weights["price"] * (1 if verified_price else 0)
        + weights["reliability"] * ((reliability or 0) / 100)
        + min(available_evses, 4) * 0.12
    )
    reasons = [f"purpose:{purpose}"]
    if requested_services:
        reasons.append(f"requested_services:{service_matches}/{len(requested_services)}")
    if verified_price:
        reasons.append("verified_price")
    if total_evses >= 4:
        reasons.append("hub_size")
    if power_kw:
        reasons.append("useful_power_capped" if power_was_capped else "power")
    return score, reasons


def station_matches_search_filters(
    station: dict[str, Any],
    *,
    requested_services: list[str],
    require_verified_price: bool,
    min_total_evses: int | None,
    allow_unvalidated_safety: bool,
    max_data_age_days: float | None,
    require_access_notes: bool,
) -> bool:
    if requested_services and not set(requested_services).issubset(set(normalized_service_codes(station.get("amenities")))):
        return False
    if require_verified_price and "pricePerKwhEur" not in station:
        return False
    if min_total_evses is not None and int(station.get("totalEvses") or 0) < min_total_evses:
        return False
    if not allow_unvalidated_safety and station.get("safetyValidated") is not True:
        return False
    if require_access_notes and station.get("accessNotesVerified") is not True:
        return False
    if max_data_age_days is not None:
        age_days = ((station.get("freshness") or {}).get("ageDays"))
        if age_days is None or age_days > max_data_age_days:
            return False
    return True


def parse_charger_search_purpose(value: Any) -> str:
    purpose = str(value or "destination").strip()
    if purpose not in CHARGER_SEARCH_PURPOSES:
        raise ConversationToolError("purpose debe ser urgent, destination, stay o near_route_fallback.")
    return purpose


def parse_string_list_arg(value: Any, *, max_items: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConversationToolError("Argumento de lista inválido.")
    return normalized_service_codes(value)[:max_items]


def normalized_service_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    codes = []
    for item in value:
        text = str(item or "").strip().lower().replace("-", "_").replace(" ", "_")[:40]
        if text and text not in codes:
            codes.append(text)
    return codes


def station_freshness_payload(station) -> dict[str, Any]:
    timestamps = [station.updated_at]
    timestamps.extend(tariff.updated_at for tariff in station.tariffs.all())
    timestamps.extend(
        snapshot.observed_at
        for evse in station.evses.all()
        for snapshot in evse.availability_snapshots.all()[:1]
    )
    last_updated = max((timestamp for timestamp in timestamps if timestamp), default=None)
    age_days = None
    if last_updated:
        age_days = round((timezone.now() - last_updated).total_seconds() / timedelta(days=1).total_seconds(), 2)
    return {
        "lastUpdated": last_updated.isoformat() if last_updated else None,
        "ageDays": age_days,
        "source": "authorized_import",
    }


def station_access_notes(station) -> dict[str, Any]:
    notes = str(getattr(station.data_source, "notes", "") or "").strip()
    if notes:
        return {"notes": notes[:240], "verified": True}
    return {"notes": "Acceso final no verificado por la herramienta; confirmar en el operador o al llegar.", "verified": False}


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
        "totalEvses": score.station.get("connector_count"),
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
