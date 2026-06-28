from __future__ import annotations

from typing import Any
from urllib.parse import unquote


def action_button_sequence_contract_issues(blocks: list[dict]) -> list[str]:
    issues: list[str] = []
    for index, block in enumerate(blocks[:-1]):
        if not isinstance(block, dict) or block.get("type") != "StationList":
            continue
        next_block = blocks[index + 1]
        if isinstance(next_block, dict) and next_block.get("type") == "ActionButtons":
            issues.append(
                "ActionButtons no debe ir inmediatamente después de StationList: en móvil queda ambiguo "
                "si los botones pertenecen a toda la lista o a una estación concreta. Usa StationPreviewCard "
                "con acciones para una estación primaria, o muestra StationList sin botones globales."
            )
    return issues


def action_buttons_contract_issues(
    props: dict,
    facts: dict[str, Any] | None = None,
    explicit_coordinates: list[tuple[float, float]] | None = None,
) -> list[str]:
    from routing import agent as legacy

    facts = facts or {"stations": {}, "locations": []}
    explicit_coordinates = explicit_coordinates or []
    actions = props.get("actions")
    if not isinstance(actions, list):
        return ["ActionButtons.props.actions debe ser una lista."]
    issues: list[str] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            issues.append(f"ActionButtons.actions[{index}] debe ser un objeto.")
            continue
        label = legacy.normalize(str(action.get("label") or ""))
        if any(term in label for term in ("reserv", "pagar", "pago", "booking", "payment", "comprar")):
            issues.append(f"ActionButtons.actions[{index}] pide una acción no soportada por Kalmio.")
        if label == "usar este punto":
            issues.append(
                f"ActionButtons.actions[{index}] usa un label ambiguo; usa 'Elegir esta parada' o 'Elegir este punto de carga'."
            )
        if action.get("action") or action.get("type"):
            issues.append(f"ActionButtons.actions[{index}] usa un handler que el frontend no soporta.")

        has_supported_action = False

        event = action.get("event")
        if event is not None:
            if not isinstance(event, dict) or not str(event.get("name") or "").strip():
                issues.append(f"ActionButtons.actions[{index}].event necesita name.")
            else:
                has_supported_action = True

        function_call = action.get("functionCall")
        if function_call is not None:
            if not isinstance(function_call, dict):
                issues.append(f"ActionButtons.actions[{index}].functionCall debe ser un objeto.")
            elif function_call.get("call") != "openUrl":
                issues.append(f"ActionButtons.actions[{index}].functionCall no está registrado.")
            else:
                args = function_call.get("args") if isinstance(function_call.get("args"), dict) else {}
                url = str(args.get("url") or "").strip().lower()
                if not (url.startswith("https://") or url.startswith("http://")):
                    issues.append(f"ActionButtons.actions[{index}].functionCall.args.url debe ser http(s).")
                elif url.startswith("javascript:"):
                    issues.append(f"ActionButtons.actions[{index}].functionCall.args.url no puede ejecutar scripts.")
                else:
                    has_supported_action = True
                    issues.extend(
                        action_coordinate_contract_issues(
                            f"ActionButtons.actions[{index}].functionCall.args.url",
                            label,
                            legacy.coordinates_from_text(unquote(url)),
                            facts,
                            explicit_coordinates,
                        )
                    )

        if isinstance(event, dict):
            context = event.get("context") if isinstance(event.get("context"), dict) else {}
            lat = legacy.optional_float(context.get("lat"))
            lon = legacy.optional_float(context.get("lon"))
            if lat is not None and lon is not None:
                issues.extend(
                    action_coordinate_contract_issues(
                        f"ActionButtons.actions[{index}].event.context",
                        label,
                        [(lat, lon)],
                        facts,
                        explicit_coordinates,
                    )
                )

        href = action.get("href")
        if href not in (None, ""):
            issues.append(f"ActionButtons.actions[{index}].href no forma parte del contrato A2UI de Kalmio.")

        if not has_supported_action and not action.get("disabled"):
            issues.append(f"ActionButtons.actions[{index}] necesita event, functionCall.openUrl, o estar deshabilitada.")
    return issues


def action_coordinate_contract_issues(
    label: str,
    action_label: str,
    coordinates: list[tuple[float, float]],
    facts: dict[str, Any],
    explicit_coordinates: list[tuple[float, float]],
) -> list[str]:
    from routing import agent as legacy

    issues: list[str] = []
    if not coordinates:
        return issues
    station = station_referenced_by_action_label(action_label, facts)
    for lat, lon in coordinates:
        if station is not None:
            if not legacy.close_station_coordinates(lat, lon, station.get("lat"), station.get("lon")):
                issues.append(f"{label} usa coordenadas que no coinciden con la estación trazable '{station['name']}'.")
            continue
        if not legacy.coordinate_traced_by_any_fact(lat, lon, facts, explicit_coordinates):
            issues.append(f"{label} usa coordenadas que no vienen del usuario, estación, origen, destino ni herramienta.")
    return issues


def station_referenced_by_action_label(action_label: str, facts: dict[str, Any]) -> dict[str, Any] | None:
    from routing import agent as legacy

    normalized_label = legacy.normalize(action_label)
    for station in facts.get("stations", {}).values():
        station_name = legacy.display_text(station.get("name"), "")
        normalized_station = legacy.station_key(station_name)
        if normalized_station and normalized_station in normalized_label:
            return station
    return None
