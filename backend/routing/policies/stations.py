from __future__ import annotations

from typing import Any

from routing.policies.traceability import station_metric_contract_issues, station_reference_contract_issues


def station_list_contract_issues(props: dict, facts: dict[str, Any]) -> list[str]:
    from routing import agent as legacy

    stations = props.get("stations")
    if not isinstance(stations, list):
        return ["StationList.props.stations debe ser una lista."]
    if not stations and not facts.get("stationSearches"):
        return ["StationList.stations está vacío sin una búsqueda o ruta de herramienta trazable."]
    issues: list[str] = []
    for index, station in enumerate(stations):
        if not isinstance(station, dict):
            issues.append(f"StationList.stations[{index}] debe ser un objeto.")
            continue
        name = legacy.display_text(station.get("name") or station.get("stationName"), "")
        if not name:
            issues.append(f"StationList.stations[{index}] necesita name.")
            continue
        issues.extend(station_reference_contract_issues(f"StationList.stations[{index}].name", name, facts))
        issues.extend(station_metric_contract_issues(f"StationList.stations[{index}]", station, facts))
    return issues
