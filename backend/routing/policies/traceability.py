from __future__ import annotations

from typing import Any


def station_reference_contract_issues(label: str, value: Any, facts: dict[str, Any]) -> list[str]:
    from routing import agent as legacy

    name = legacy.display_text(value, "")
    if not name or legacy.generic_station_label(name):
        return []
    if not facts["stations"]:
        return [f"{label} menciona una estación sin resultado de herramienta trazable."]
    if legacy.station_key(name) not in facts["stations"]:
        return [f"{label} no coincide con ninguna estación devuelta por las herramientas: {name}."]
    return []


def required_station_reference_contract_issues(label: str, value: Any, facts: dict[str, Any]) -> list[str]:
    from routing import agent as legacy

    name = legacy.display_text(value, "")
    if facts["stations"] and legacy.generic_station_label(name):
        return [f"{label} debe usar una estación trazable cuando hay resultados de herramienta."]
    return []


def station_metric_contract_issues(label: str, props: dict, facts: dict[str, Any]) -> list[str]:
    from routing import agent as legacy

    name = legacy.display_text(props.get("name") or props.get("stationName"), "")
    if not name or legacy.generic_station_label(name):
        return []
    source = facts["stations"].get(legacy.station_key(name))
    if not source:
        return []

    issues: list[str] = []
    rendered_values = legacy.station_value_aliases(props)
    for field in ("powerKw", "distanceKm", "detourMin", "lat", "lon", "availableEvses", "totalEvses", "pricePerKwhEur"):
        if field not in rendered_values:
            continue
        rendered = rendered_values.get(field)
        expected = source.get(field)
        if rendered is None:
            continue
        if field == "pricePerKwhEur" and (
            props.get("priceIsEstimated") is True or source.get("priceIsEstimated") is True
        ):
            issues.append(f"{label}.pricePerKwhEur no debe mostrarse porque la tarifa para {name} está marcada como estimada.")
            continue
        if expected is None:
            issues.append(f"{label}.{field} no está en el resultado de herramienta para {name}.")
        elif field in {"lat", "lon"} and not legacy.coordinate_value_matches(rendered, expected):
            issues.append(f"{label}.{field} no coincide con el dato de herramienta para {name}.")
        elif not legacy.values_match(rendered, expected):
            issues.append(f"{label}.{field} no coincide con el dato de herramienta para {name}.")
    return issues


def route_summary_contract_issues(props: dict, facts: dict[str, Any], label: str) -> list[str]:
    from routing import agent as legacy

    if not facts["routes"]:
        return [f"{label} necesita un resultado plan_route trazable."]
    route = facts["routes"][-1]
    issues: list[str] = []
    for field in ("distanceKm", "durationMin", "energyKwh", "arrivalBattery"):
        rendered = props.get(field)
        expected = route.get(field)
        if rendered is None and expected is None:
            continue
        if rendered is None:
            continue
        if expected is None:
            issues.append(f"{label}.{field} no está en el resultado plan_route.")
        elif not legacy.values_match(rendered, expected):
            issues.append(f"{label}.{field} no coincide con plan_route.")
    return issues


def map_preview_contract_issues(
    props: dict,
    facts: dict[str, Any],
    explicit_coordinates: list[tuple[float, float]],
    label: str,
) -> list[str]:
    from routing import agent as legacy

    issues: list[str] = []
    route_geometry = props.get("routeGeometry")
    geometry_precision = props.get("geometryPrecision")
    if geometry_precision == "provider":
        if not facts["routes"]:
            issues.append(f"{label} necesita un resultado plan_route trazable.")
        if not isinstance(route_geometry, dict):
            issues.append(f"{label}.routeGeometry debe venir de plan_route cuando geometryPrecision='provider'.")

    if isinstance(route_geometry, dict):
        expected_geometry = facts["routes"][-1].get("routeGeometry") if facts["routes"] else None
        if expected_geometry is None:
            issues.append(f"{label}.routeGeometry no está en el resultado plan_route.")
        elif not line_string_geometry_matches(route_geometry, expected_geometry):
            issues.append(f"{label}.routeGeometry no coincide con plan_route.")

    for field in ("origin", "destination"):
        point = props.get(field)
        if not isinstance(point, dict):
            continue
        lat = legacy.optional_float(point.get("lat"))
        lon = legacy.optional_float(point.get("lon"))
        if lat is None and lon is None:
            continue
        if lat is None or lon is None:
            issues.append(f"{label}.{field} necesita lat y lon juntos.")
        elif not legacy.coordinate_traced(lat, lon, facts["locations"], explicit_coordinates):
            issues.append(f"{label}.{field} no coincide con una ubicación de herramienta.")

    primary_station = props.get("primaryStation")
    if isinstance(primary_station, dict):
        station_name = primary_station.get("name") or primary_station.get("stationName")
        issues.extend(required_station_reference_contract_issues(f"{label}.primaryStation.name", station_name, facts))
        issues.extend(station_reference_contract_issues(f"{label}.primaryStation.name", station_name, facts))
        issues.extend(station_metric_contract_issues(f"{label}.primaryStation", primary_station, facts))

    stations = props.get("stations")
    if isinstance(stations, list):
        for index, station in enumerate(stations):
            if not isinstance(station, dict):
                issues.append(f"{label}.stations[{index}] debe ser un objeto.")
                continue
            station_name = station.get("name") or station.get("stationName")
            issues.extend(required_station_reference_contract_issues(f"{label}.stations[{index}].name", station_name, facts))
            issues.extend(station_reference_contract_issues(f"{label}.stations[{index}].name", station_name, facts))
            issues.extend(station_metric_contract_issues(f"{label}.stations[{index}]", station, facts))
    return issues


def line_string_geometry_matches(rendered: dict[str, Any], expected: Any) -> bool:
    if not isinstance(expected, dict):
        return False
    if rendered.get("type") != "LineString" or expected.get("type") != "LineString":
        return False
    rendered_coordinates = rendered.get("coordinates")
    expected_coordinates = expected.get("coordinates")
    if not isinstance(rendered_coordinates, list) or not isinstance(expected_coordinates, list):
        return False
    if len(rendered_coordinates) != len(expected_coordinates):
        return False
    for rendered_pair, expected_pair in zip(rendered_coordinates, expected_coordinates):
        if not coordinate_pair_matches(rendered_pair, expected_pair):
            return False
    return True


def coordinate_pair_matches(rendered: Any, expected: Any) -> bool:
    from routing import agent as legacy

    if not isinstance(rendered, list) or not isinstance(expected, list):
        return False
    if len(rendered) != 2 or len(expected) != 2:
        return False
    rendered_lon = legacy.optional_float(rendered[0])
    rendered_lat = legacy.optional_float(rendered[1])
    expected_lon = legacy.optional_float(expected[0])
    expected_lat = legacy.optional_float(expected[1])
    if rendered_lon is None or rendered_lat is None or expected_lon is None or expected_lat is None:
        return False
    return legacy.close_coordinates(rendered_lat, rendered_lon, expected_lat, expected_lon)
