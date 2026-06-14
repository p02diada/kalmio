from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from charging.selectors import get_nearby_stations
from django.conf import settings
from routing.production_planner import PlanningDataError, plan_route_with_persisted_stations
from routing.providers import Coordinate, RoutingProviderError, get_route_provider
from routing.scoring import Preferences, VehicleContext
from routing.tools import (
    KNOWN_LOCATIONS,
    ConversationToolError,
    ToolCall,
    execute_conversation_tool,
)

A2UI_COMPONENT_TYPES = {
    "AssistantMessage",
    "UserMessage",
    "TripSummaryCard",
    "RouteSummaryCard",
    "RecommendedStopCard",
    "AlternativeRoutesList",
    "AlternativeStopsList",
    "RiskExplanationCard",
    "CostComparisonCard",
    "UrgentChargeCard",
    "DestinationChargingCard",
    "StayPlanningCard",
    "MapPreviewCard",
    "ActionButtons",
    "ClarifyingQuestionCard",
    "LocationRequestCard",
    "PreferenceChips",
    "ErrorFallbackCard",
}


@dataclass(frozen=True)
class ParsedLocation:
    label: str
    lat: float
    lon: float


@dataclass(frozen=True)
class ParsedIntent:
    text: str
    origin: ParsedLocation | None
    destination: ParsedLocation | None
    destination_search: ParsedLocation | None
    vehicle: VehicleContext | None
    vehicle_fields: dict
    preferences: Preferences
    is_route_request: bool
    is_destination_charge_request: bool
    is_urgent_request: bool


class AgentResponseError(RuntimeError):
    pass


def initial_blocks() -> list[dict]:
    return [
        block(
            "assistant-initial",
            "AssistantMessage",
            {
                "text": (
                    "Cuéntame qué necesitas: una ruta completa, cargar cerca de donde estás, "
                    "o cargadores cerca de un hotel o destino. Si falta un dato crítico, te lo pediré."
                )
            },
        ),
        block(
            "preference-starters",
            "PreferenceChips",
            {
                "chips": [
                    "Necesito cargar ya",
                    "Ruta con parada segura",
                    "Cargadores cerca del hotel",
                    "Priorizar servicios",
                ]
            },
        ),
    ]


def run_conversation_agent(message: str, history_blocks: list[dict] | None = None) -> list[dict]:
    mode = getattr(settings, "KALMIO_CONVERSATION_AGENT_MODE", "local")
    if mode == "codex":
        blocks = validate_blocks(run_codex_agent(message, history_blocks=history_blocks))
        if not any(item.get("type") == "UserMessage" for item in blocks):
            blocks.insert(0, block(f"user-{uuid4().hex[:10]}", "UserMessage", {"text": message.strip()}))
        return blocks
    if mode != "local":
        raise AgentResponseError(f"Modo de agente no soportado: {mode}.")
    return validate_blocks(run_local_agent(message, history_blocks=history_blocks))


def run_local_agent(message: str, history_blocks: list[dict] | None = None) -> list[dict]:
    intent = parse_intent(contextualized_message(message, history_blocks or []))
    blocks = [block(f"user-{uuid4().hex[:10]}", "UserMessage", {"text": message.strip()})]

    if intent.is_urgent_request:
        location = intent.origin or intent.destination_search or intent.destination
        if not location:
            blocks.append(
                location_request_block(
                    reason="urgent_charge",
                    title="Necesito tu ubicación",
                    body=(
                        "Para buscar cargadores cercanos sin inventar resultados, "
                        "comparte tu ubicación o escribe una ciudad/coordenadas."
                    ),
                )
            )
            return blocks

        blocks.extend(urgent_charge_blocks(intent, location))
        return blocks

    if intent.is_destination_charge_request and not intent.is_route_request:
        blocks.extend(destination_charge_blocks(intent))
        return blocks

    if intent.is_route_request:
        missing = []
        if not intent.origin:
            missing.append("origen")
        if not intent.destination:
            missing.append("destino")
        if missing:
            blocks.append(
                clarifying_block(
                    "Para decidir si hay que calcular ruta necesito ubicar estos datos.",
                    missing,
                )
            )
            return blocks

        try:
            blocks.extend(route_planning_blocks(intent))
        except RoutingProviderError as exc:
            blocks.append(
                block(
                    f"risk-{uuid4().hex[:10]}",
                    "RiskExplanationCard",
                    {"level": "alto", "text": f"No puedo calcular la ruta ahora: {exc}"},
                )
            )
        except PlanningDataError as exc:
            blocks.append(
                block(
                    f"risk-{uuid4().hex[:10]}",
                    "RiskExplanationCard",
                    {"level": "alto", "text": str(exc)},
                )
            )
        return blocks

    blocks.append(
        clarifying_block(
            "¿Quieres calcular una ruta EV o buscar cargadores cerca de un destino concreto?",
            ["tipo de búsqueda", "ubicación o ruta"],
        )
    )
    return blocks


def conversation_failure_blocks(message: str) -> list[dict]:
    return [
        block(f"user-{uuid4().hex[:10]}", "UserMessage", {"text": message.strip()}),
        block(
            f"risk-{uuid4().hex[:10]}",
            "RiskExplanationCard",
            {
                "level": "alto",
                "text": (
                    "No he podido completar esta comprobación con fiabilidad. "
                    "Puedo intentarlo de nuevo si me das origen, destino, batería actual y conector, "
                    "o buscar primero cargadores cerca de una ciudad concreta."
                ),
            },
        ),
        clarifying_block(
            "Para recuperar la consulta, envíame los datos que tengas y no asumiré los que falten.",
            ["origen o ubicación", "destino si hay ruta", "batería actual", "conector"],
        ),
        block(
            f"chips-{uuid4().hex[:10]}",
            "PreferenceChips",
            {
                "chips": [
                    "Reintentar con origen y destino",
                    "Buscar cargadores cerca de mi ubicación",
                    "Corregir batería o conector",
                ]
            },
        ),
    ]


def run_codex_agent(message: str, history_blocks: list[dict] | None = None) -> list[dict]:
    decision_message = contextualized_prompt(message, history_blocks or [])
    tool_history: list[dict[str, Any]] = []
    seen_calls: set[str] = set()
    max_tool_calls = getattr(settings, "KALMIO_CODEX_MAX_TOOL_CALLS", 3)

    for _ in range(max_tool_calls + 1):
        decision = run_codex_decision(decision_message, tool_history=tool_history)
        if decision["type"] == "final":
            return validated_or_repaired_final_blocks(decision_message, decision["blocks"], tool_history)

        call_signature = json.dumps(
            {"tool": decision["tool"], "args": decision["args"]},
            sort_keys=True,
            ensure_ascii=False,
        )
        if call_signature in seen_calls:
            return fallback_from_tool_history(
                tool_history,
                f"Codex repitió la herramienta {decision['tool']} con los mismos argumentos.",
                decision_message,
            )
        if len(tool_history) >= max_tool_calls:
            return fallback_from_tool_history(
                tool_history,
                f"Se alcanzó el máximo de {max_tool_calls} llamadas a herramientas para este turno.",
                decision_message,
            )
        seen_calls.add(call_signature)

        try:
            result = execute_conversation_tool(ToolCall(name=decision["tool"], args=decision["args"]))
        except ConversationToolError as exc:
            result = {"ok": False, "tool": decision["tool"], "error": str(exc)}
        tool_history.append({"call": {"tool": decision["tool"], "args": decision["args"]}, "result": result})

        if not result.get("ok"):
            return fallback_from_tool_history(
                tool_history,
                str(result.get("error") or "La herramienta falló."),
                decision_message,
            )

    return fallback_from_tool_history(tool_history, "Codex no devolvió una respuesta final.", decision_message)


def validated_or_repaired_final_blocks(
    message: str,
    candidate_blocks: list[dict],
    tool_history: list[dict[str, Any]],
) -> list[dict]:
    blocks = validate_blocks(candidate_blocks)
    issues = semantic_a2ui_issues(blocks, tool_history, message)
    if not issues:
        return blocks

    repair_decision = run_codex_decision(
        message,
        tool_history=tool_history,
        repair_issues=issues,
        candidate_blocks=candidate_blocks,
    )
    if repair_decision["type"] != "final":
        return fallback_from_tool_history(
            tool_history,
            "Codex intentó pedir otra herramienta durante la reparación A2UI.",
            message,
        )

    repaired_blocks = validate_blocks(repair_decision["blocks"])
    remaining_issues = semantic_a2ui_issues(repaired_blocks, tool_history, message)
    if remaining_issues:
        return fallback_from_tool_history(
            tool_history,
            "Codex no pudo reparar el contrato A2UI: " + "; ".join(remaining_issues),
            message,
        )
    return repaired_blocks


def run_codex_decision(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    payload = call_codex_json(
        codex_prompt(
            message,
            tool_history=tool_history or [],
            repair_issues=repair_issues or [],
            candidate_blocks=candidate_blocks or [],
        )
    )
    return parse_codex_decision(payload)


def codex_prompt(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> str:
    tool_history = tool_history or []
    repair_issues = repair_issues or []
    candidate_blocks = candidate_blocks or []
    tool_instructions = (
        "Herramientas permitidas, solo con estos nombres y argumentos JSON:\n"
        '- resolve_location: {"query":"ciudad o texto"}\n'
        '- search_destination_chargers: {"location":{"label":"...","lat":0,"lon":0},"connector":null,"radius_km":80,"limit":3}\n'
        '- plan_route: {"origin":{"label":"...","lat":0,"lon":0},"destination":{"label":"...","lat":0,"lon":0},'
        '"vehicle":null,"preferences":{"reserve_min_percent":20},"corridor_radius_km":25}\n'
        "Ubicaciones conocidas para no inventar coordenadas: "
        + json.dumps(
            {key: {"label": value[0], "lat": value[1], "lon": value[2]} for key, value in KNOWN_LOCATIONS.items()},
            ensure_ascii=False,
        )
        + ".\n"
    )
    output_instructions = (
        "Devuelve solo JSON, sin markdown. Formas válidas:\n"
        '{"type":"tool_call","tool":"search_destination_chargers","args":{...}}\n'
        '{"type":"final","blocks":[{"id":"...","type":"AssistantMessage","version":1,"props":{"text":"..."}}]}\n'
        "Tipos A2UI permitidos: "
        f"{', '.join(sorted(A2UI_COMPONENT_TYPES))}. "
        "Para aclaraciones usa ClarifyingQuestionCard con props question y fields. "
        "Si falta ubicación actual para una petición cercana o urgente, usa LocationRequestCard en vez de inventar coordenadas. "
        "Si el usuario pide cargadores cerca de un hotel, destino o ciudad conocida y tienes ciudad o coordenadas, "
        "llama search_destination_chargers con esa ubicación y marca la respuesta final como aproximada/necesita confirmación. "
        "Solo pregunta por el hotel exacto si no hay ninguna ciudad, coordenada o ubicación conocida. "
        "Si el usuario pide una ruta y hay origen y destino conocidos, llama plan_route. "
        "No inventes disponibilidad, precios, estaciones, coordenadas ni estado del vehículo. "
        "Si una herramienta devuelve datos, usa solo esos datos. "
        "Si search_destination_chargers devuelve ok=true, no respondas solo con texto: incluye DestinationChargingCard, "
        "AlternativeStopsList con las paradas devueltas y RiskExplanationCard. "
        "Si plan_route devuelve ok=true, no respondas solo con texto: incluye RouteSummaryCard y RecommendedStopCard. "
        "Puedes pedir otra herramienta si falta un dato necesario, pero no repitas una llamada ya hecha con los mismos argumentos."
    )
    if repair_issues:
        return (
            "Eres el agente local de Kalmio. Tu respuesta final anterior fue rechazada por el contrato A2UI. "
            "No pidas herramientas en esta reparación. Devuelve solo type=final con blocks A2UI válidos. "
            "Elige tú la UI que más valor aporte al usuario, pero debe cumplir estos problemas detectados:\n"
            f"{json.dumps(repair_issues, ensure_ascii=False)}\n"
            f"{semantic_contract_prompt(tool_history, message)}\n"
            "Usa solo datos del historial de herramientas; no inventes estaciones, precios, disponibilidad, coordenadas ni estado del vehículo.\n"
            f"Usuario: {message}\n"
            f"Historial de herramientas: {json.dumps(tool_history, ensure_ascii=False)}\n"
            f"Bloques rechazados: {json.dumps(candidate_blocks, ensure_ascii=False)}\n"
            f"{output_instructions}"
        )
    if tool_history:
        return (
            "Eres el agente local de Kalmio. Ya se ejecutaron estas herramientas internas de Django. "
            "Decide si necesitas otra herramienta permitida o si ya puedes devolver type=final con A2UI.\n"
            f"Usuario: {message}\n"
            f"Historial de herramientas: {json.dumps(tool_history, ensure_ascii=False)}\n"
            f"{output_instructions}"
        )
    return f"Eres el agente local de Kalmio.\n{tool_instructions}{output_instructions}\nUsuario: {message}"


def semantic_contract_prompt(tool_history: list[dict[str, Any]], message: str = "") -> str:
    tool_result = latest_successful_tool_result(tool_history)
    if not tool_result:
        return ""
    if parse_intent(message).is_urgent_request and tool_result.get("tool") == "search_destination_chargers":
        return (
            "Contrato obligatorio para una petición urgente con search_destination_chargers ok=true:\n"
            "- Usa UrgentChargeCard, AlternativeStopsList y RiskExplanationCard; no uses DestinationChargingCard.\n"
            "- UrgentChargeCard debe mostrar el cargador cercano más plausible con nearest y distanceKm de la herramienta.\n"
            "- RiskExplanationCard debe explicar que disponibilidad, tarifa y acceso se deben confirmar antes de depender del cargador."
        )
    if tool_result.get("tool") == "search_destination_chargers":
        location = tool_result.get("location") if isinstance(tool_result.get("location"), dict) else {}
        return (
            "Contrato obligatorio para search_destination_chargers ok=true:\n"
            f'- DestinationChargingCard props debe ser {{"destination": "{location.get("label") or "Destino"}", "needsConfirmation": true}}.\n'
            f'- AlternativeStopsList props.stops debe contener estas paradas de la herramienta, sin inventar ni omitir: {json.dumps(tool_result.get("stops", []), ensure_ascii=False)}.\n'
            '- RiskExplanationCard props debe ser {"level": "medio", "text": "Muestro cargadores autorizados importados cerca del destino. Confirma acceso final, tarifa y disponibilidad antes de depender de ellos."}.'
        )
    if tool_result.get("tool") == "plan_route":
        return (
            "Contrato obligatorio para plan_route ok=true:\n"
            "- RouteSummaryCard debe usar distanceKm, durationMin, energyKwh y arrivalBattery devueltos por la herramienta.\n"
            "- RecommendedStopCard debe usar la recomendación devuelta por la herramienta."
        )
    return ""


def call_codex_json(prompt: str) -> dict[str, Any]:
    prompt = (
        "Responde únicamente con un objeto JSON válido. No incluyas markdown ni explicaciones fuera del JSON.\n"
        f"{prompt}"
    )
    try:
        with tempfile.NamedTemporaryFile("r+", suffix=".json") as output:
            result = subprocess.run(
                [
                    getattr(settings, "KALMIO_CODEX_COMMAND", "codex"),
                    "--ask-for-approval",
                    "never",
                    "exec",
                    "--ephemeral",
                    "--sandbox",
                    "read-only",
                    "-m",
                    getattr(settings, "KALMIO_CODEX_MODEL", "gpt-5-nano"),
                    "-o",
                    output.name,
                    prompt,
                ],
                cwd=settings.BASE_DIR.parent,
                text=True,
                capture_output=True,
                timeout=getattr(settings, "KALMIO_CODEX_TIMEOUT_SECONDS", 20),
            )
            output.seek(0)
            raw_output = output.read().strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AgentResponseError(f"Codex local no disponible: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "sin detalle"
        raise AgentResponseError(f"Codex local falló: {detail}")

    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise AgentResponseError("Codex local no devolvió JSON válido.") from exc
    if not isinstance(payload, dict):
        raise AgentResponseError("Codex local no devolvió un objeto JSON.")
    return payload


def parse_codex_decision(payload: dict[str, Any]) -> dict[str, Any]:
    decision_type = str(payload.get("type") or payload.get("kind") or payload.get("action") or "").strip()
    if not decision_type and isinstance(payload.get("blocks"), list):
        decision_type = "final"
    if decision_type in {"final", "ask"}:
        blocks = payload.get("blocks")
        if not isinstance(blocks, list):
            raise AgentResponseError("Codex local no devolvió bloques para la respuesta final.")
        return {"type": "final", "blocks": blocks}
    if decision_type in {"tool_call", "tool"} or isinstance(payload.get("tool_call"), dict):
        tool_payload = payload.get("tool_call") if isinstance(payload.get("tool_call"), dict) else payload
        tool = str(tool_payload.get("tool") or tool_payload.get("name") or "").strip()
        args = tool_payload.get("args") if isinstance(tool_payload.get("args"), dict) else {}
        if not tool:
            raise AgentResponseError("Codex pidió una herramienta sin nombre.")
        return {"type": "tool_call", "tool": tool, "args": args}
    raise AgentResponseError("Codex local devolvió una decisión no soportada.")


def blocks_from_tool_result(tool_result: dict[str, Any], message: str = "") -> list[dict]:
    tool = tool_result.get("tool")
    if not tool_result.get("ok"):
        return [
            block(
                f"risk-{uuid4().hex[:10]}",
                "RiskExplanationCard",
                {
                    "level": "alto",
                    "text": user_facing_failure_text(
                        str(tool_result.get("error") or "La herramienta no pudo devolver datos reales.")
                    ),
                },
            )
        ]
    if tool == "search_destination_chargers":
        location = tool_result.get("location") if isinstance(tool_result.get("location"), dict) else {}
        stops = tool_result.get("stops") if isinstance(tool_result.get("stops"), list) else []
        if parse_intent(message).is_urgent_request:
            nearest = stops[0] if stops and isinstance(stops[0], dict) else {}
            return [
                block(
                    f"urgent-{uuid4().hex[:10]}",
                    "UrgentChargeCard",
                    {
                        "battery": None,
                        "nearest": str(nearest.get("name") or "Cargador cercano por confirmar"),
                        "distanceKm": nearest.get("distanceKm"),
                    },
                ),
                block(
                    f"stops-{uuid4().hex[:10]}",
                    "AlternativeStopsList",
                    {"stops": stops},
                ),
                block(
                    f"risk-{uuid4().hex[:10]}",
                    "RiskExplanationCard",
                    {
                        "level": "medio",
                        "text": (
                            "Muestro cargadores autorizados importados cerca de la ubicación indicada. "
                            "Confirma acceso final, tarifa y disponibilidad antes de depender de ellos."
                        ),
                    },
                ),
            ]
        return [
            block(
                f"destination-{uuid4().hex[:10]}",
                "DestinationChargingCard",
                {"destination": str(location.get("label") or "Destino"), "needsConfirmation": True},
            ),
            block(
                f"stops-{uuid4().hex[:10]}",
                "AlternativeStopsList",
                {"stops": tool_result.get("stops") if isinstance(tool_result.get("stops"), list) else []},
            ),
            block(
                f"risk-{uuid4().hex[:10]}",
                "RiskExplanationCard",
                {"level": "medio", "text": "Muestro solo cargadores autorizados devueltos por la herramienta interna."},
            ),
        ]
    if tool == "plan_route":
        recommendation = tool_result.get("recommendation") if isinstance(tool_result.get("recommendation"), dict) else {}
        return [
            block(
                f"route-{uuid4().hex[:10]}",
                "RouteSummaryCard",
                {
                    "distanceKm": tool_result.get("distanceKm"),
                    "durationMin": tool_result.get("durationMin"),
                    "energyKwh": tool_result.get("energyKwh"),
                    "arrivalBattery": tool_result.get("arrivalBattery"),
                },
            ),
            block(
                f"stop-{uuid4().hex[:10]}",
                "RecommendedStopCard",
                {
                    "name": str(recommendation.get("name") or "Cargador recomendado"),
                    "powerKw": recommendation.get("powerKw") or 0,
                    "detourMin": recommendation.get("detourMin") or 0,
                    "confidence": recommendation.get("confidence") or "media",
                },
            ),
        ]
    return [block(f"assistant-{uuid4().hex[:10]}", "AssistantMessage", {"text": "Herramienta ejecutada."})]


def fallback_from_tool_history(tool_history: list[dict[str, Any]], reason: str, message: str = "") -> list[dict]:
    latest_result = latest_successful_tool_result(tool_history) or latest_tool_result(tool_history)
    blocks = blocks_from_tool_result(latest_result, message) if latest_result else []
    blocks.append(
        block(
            f"risk-{uuid4().hex[:10]}",
            "RiskExplanationCard",
            {"level": "medio", "text": user_facing_failure_text(reason)},
        )
    )
    return blocks


def user_facing_failure_text(reason: str) -> str:
    normalized = normalize(reason)
    if "herramienta no permitida" in normalized:
        return "No puedo hacer esa acción desde el chat. Puedo ayudarte a calcular una ruta, buscar cargadores autorizados o pedir los datos que falten."
    if "proveedor" in normalized or "ruta" in normalized:
        return "No he podido validar la ruta ahora mismo. Reinténtalo con origen y destino concretos, o busca primero cargadores cerca de una ciudad."
    if "datos" in normalized or "cargadores" in normalized:
        return "No he podido validar cargadores suficientes con datos autorizados. Puedo intentarlo con otra ubicación o un radio más amplio."
    return "No he podido completar esta respuesta con fiabilidad. Reintenta con menos datos ambiguos o corrige origen, destino, batería y conector."


def latest_tool_result(tool_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(tool_history):
        result = entry.get("result")
        if isinstance(result, dict):
            return result
    return None


def latest_successful_tool_result(tool_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(tool_history):
        result = entry.get("result")
        if isinstance(result, dict) and result.get("ok"):
            return result
    return None


def semantic_a2ui_issues(blocks: list[dict], tool_history: list[dict[str, Any]], message: str = "") -> list[str]:
    if parse_intent(message).is_urgent_request:
        return urgent_charge_a2ui_issues(blocks)
    tool_result = latest_successful_tool_result(tool_history)
    if not tool_result:
        return []
    if tool_result.get("tool") == "search_destination_chargers":
        return destination_charging_a2ui_issues(blocks, tool_result)
    if tool_result.get("tool") == "plan_route":
        return route_a2ui_issues(blocks)
    return []


def urgent_charge_a2ui_issues(blocks: list[dict]) -> list[str]:
    issues = []
    if blocks_of_type(blocks, "DestinationChargingCard"):
        issues.append("Una petición urgente no debe renderizar DestinationChargingCard.")
    if not blocks_of_type(blocks, "UrgentChargeCard") and not blocks_of_type(blocks, "LocationRequestCard"):
        issues.append("Una petición urgente debe renderizar UrgentChargeCard o LocationRequestCard.")
    if blocks_of_type(blocks, "UrgentChargeCard") and not blocks_of_type(blocks, "RiskExplanationCard"):
        issues.append("Una petición urgente con recomendación debe incluir RiskExplanationCard.")
    return issues


def destination_charging_a2ui_issues(blocks: list[dict], tool_result: dict[str, Any]) -> list[str]:
    issues = []
    destination_cards = blocks_of_type(blocks, "DestinationChargingCard")
    stop_lists = blocks_of_type(blocks, "AlternativeStopsList")
    risk_cards = blocks_of_type(blocks, "RiskExplanationCard")
    location = tool_result.get("location") if isinstance(tool_result.get("location"), dict) else {}
    location_label = str(location.get("label") or "").strip()

    if not destination_cards:
        issues.append("Falta DestinationChargingCard para contextualizar la carga en destino.")
    else:
        destination = str((destination_cards[0].get("props") or {}).get("destination") or "").strip()
        if not destination or destination == "Destino aproximado":
            issues.append("DestinationChargingCard debe incluir el destino resuelto por la herramienta.")
        if location_label and location_label.lower() not in destination.lower():
            issues.append("DestinationChargingCard debe referirse al destino resuelto por la herramienta.")
        if not (destination_cards[0].get("props") or {}).get("needsConfirmation"):
            issues.append("DestinationChargingCard debe marcar needsConfirmation=true para búsquedas aproximadas por ciudad/hotel.")

    tool_stop_names = {
        str(stop.get("name")).strip()
        for stop in tool_result.get("stops", [])
        if isinstance(stop, dict) and stop.get("name")
    }
    rendered_stop_names = {
        str(stop.get("name")).strip()
        for stop_list in stop_lists
        for stop in (stop_list.get("props") or {}).get("stops", [])
        if isinstance(stop, dict) and stop.get("name")
    }
    if tool_stop_names and not stop_lists:
        issues.append("Falta AlternativeStopsList para mostrar las paradas devueltas por search_destination_chargers.")
    elif tool_stop_names:
        unknown_names = sorted(rendered_stop_names - tool_stop_names)
        missing_names = sorted(tool_stop_names - rendered_stop_names)
        if unknown_names:
            issues.append("AlternativeStopsList contiene paradas que no salieron de la herramienta: " + ", ".join(unknown_names))
        if missing_names:
            issues.append("AlternativeStopsList debe usar las paradas devueltas por la herramienta: " + ", ".join(missing_names))

    if not risk_cards:
        issues.append("Falta RiskExplanationCard para explicar límites de disponibilidad, tarifa o acceso.")
    else:
        risk_text = str((risk_cards[0].get("props") or {}).get("text") or "").strip().lower()
        if len(risk_text) < 24 or not any(term in risk_text for term in ["disponibilidad", "tarifa", "acceso", "confirm"]):
            issues.append("RiskExplanationCard debe explicar límites concretos de disponibilidad, tarifa, acceso o confirmación.")
    return issues


def route_a2ui_issues(blocks: list[dict]) -> list[str]:
    issues = []
    if not blocks_of_type(blocks, "RouteSummaryCard"):
        issues.append("Falta RouteSummaryCard para resumir la ruta calculada por la herramienta.")
    if not blocks_of_type(blocks, "RecommendedStopCard"):
        issues.append("Falta RecommendedStopCard para mostrar la parada recomendada por la herramienta.")
    return issues


def blocks_of_type(blocks: list[dict], block_type: str) -> list[dict]:
    return [item for item in blocks if isinstance(item, dict) and item.get("type") == block_type]


def contextualized_message(message: str, history_blocks: list[dict]) -> str:
    current_message = message.strip()
    if not current_message:
        return current_message

    current_intent = parse_intent(current_message)
    if current_intent.is_route_request or current_intent.is_destination_charge_request or current_intent.is_urgent_request:
        return current_message

    previous_messages = recent_user_message_texts(history_blocks, limit=8)
    if not previous_messages:
        return current_message
    return " ".join([*previous_messages, current_message])


def contextualized_prompt(message: str, history_blocks: list[dict]) -> str:
    current_message = message.strip()
    transcript = conversation_transcript(history_blocks)
    if not transcript:
        return current_message
    return (
        "Conversación disponible de Kalmio. Usa el historial para resolver referencias y datos parciales; "
        "si el usuario cambia claramente de objetivo, sigue el mensaje actual.\n"
        f"{transcript}\n"
        f"Mensaje actual del usuario: {current_message}"
    )


def conversation_transcript(history_blocks: list[dict], limit: int = 80) -> str:
    entries = []
    for item in history_blocks[-limit:]:
        if not isinstance(item, dict):
            continue
        block_type = item.get("type")
        props = item.get("props") if isinstance(item.get("props"), dict) else {}
        summary = summarize_block_for_context(block_type, props)
        if summary:
            entries.append(summary)
    return "\n".join(entries)


def summarize_block_for_context(block_type: str, props: dict) -> str:
    if block_type == "UserMessage":
        text = str(props.get("text") or "").strip()
        return f"Usuario: {text}" if text else ""
    if block_type == "AssistantMessage":
        text = str(props.get("text") or "").strip()
        return f"Asistente: {text}" if text else ""
    if block_type == "LocationRequestCard":
        title = str(props.get("title") or "Necesito ubicación").strip()
        body = str(props.get("body") or "").strip()
        return f"Asistente pidió ubicación: {title}. {body}".strip()
    if block_type == "ClarifyingQuestionCard":
        question = str(props.get("question") or "").strip()
        fields = props.get("fields") if isinstance(props.get("fields"), list) else []
        fields_text = ", ".join(str(field) for field in fields if field)
        return f"Asistente pidió aclaración: {question} Campos: {fields_text}".strip()
    if block_type == "UrgentChargeCard":
        return (
            "Resultado previo de carga urgente: "
            f"cargador cercano {props.get('nearest')}, distancia {props.get('distanceKm')} km, "
            f"batería {props.get('battery')}."
        )
    if block_type == "DestinationChargingCard":
        return f"Resultado previo de carga en destino: {props.get('destination')}."
    if block_type == "RouteSummaryCard":
        return (
            "Resultado previo de ruta: "
            f"{props.get('distanceKm')} km, {props.get('durationMin')} min, "
            f"llegada {props.get('arrivalBattery')}%."
        )
    if block_type == "AlternativeStopsList":
        stops = props.get("stops") if isinstance(props.get("stops"), list) else []
        stop_names = [str(stop.get("name")) for stop in stops if isinstance(stop, dict) and stop.get("name")]
        if stop_names:
            return "Cargadores mostrados: " + ", ".join(stop_names[:5])
    if block_type == "RiskExplanationCard":
        text = str(props.get("text") or "").strip()
        return f"Aviso mostrado: {text}" if text else ""
    return ""


def recent_user_message_texts(history_blocks: list[dict], limit: int = 3) -> list[str]:
    messages: list[str] = []
    for item in reversed(history_blocks):
        if not isinstance(item, dict) or item.get("type") != "UserMessage":
            continue
        props = item.get("props") if isinstance(item.get("props"), dict) else {}
        text = str(props.get("text") or "").strip()
        if text:
            messages.append(text)
        if len(messages) >= limit:
            break
    return list(reversed(messages))


def urgent_charge_blocks(intent: ParsedIntent, location: ParsedLocation) -> list[dict]:
    stations = get_nearby_stations(
        lat=location.lat,
        lon=location.lon,
        radius_km=80,
        connector=intent.vehicle_fields.get("connector"),
        available_only=False,
    )
    if not stations:
        return [
            block(
                f"risk-{uuid4().hex[:10]}",
                "RiskExplanationCard",
                {
                    "level": "alto",
                    "text": (
                        f"No hay cargadores autorizados importados cerca de {location.label}. "
                        "No voy a inventar estaciones; comparte otra ubicación o coordenadas más precisas."
                    ),
                },
            ),
            location_request_block(
                reason="urgent_charge",
                title="Prueba con otra ubicación cercana",
                body=(
                    "No encuentro cargadores autorizados importados alrededor de esa ubicación. "
                    "Comparte una ubicación más precisa o una ciudad cercana y volveré a comprobarlo."
                ),
            ),
        ]

    nearest = stations[0]
    top = stations[:3]
    return [
        block(
            f"urgent-{uuid4().hex[:10]}",
            "UrgentChargeCard",
            {
                "battery": intent.vehicle_fields.get("battery"),
                "nearest": nearest.station.name,
                "distanceKm": nearest.distance_km,
            },
        ),
        block(
            f"stops-{uuid4().hex[:10]}",
            "AlternativeStopsList",
            {
                "stops": [
                    {
                        "name": item.station.name,
                        "powerKw": item.max_power_kw,
                        "distanceKm": item.distance_km,
                    }
                    for item in top
                ]
            },
        ),
        block(
            f"risk-{uuid4().hex[:10]}",
            "RiskExplanationCard",
            {
                "level": "medio",
                "text": (
                    "Muestro cargadores autorizados importados cerca de la ubicación indicada. "
                    "Confirma acceso final, tarifa y disponibilidad antes de depender de ellos."
                ),
            },
        ),
    ]


def destination_charge_blocks(intent: ParsedIntent) -> list[dict]:
    location = intent.destination_search or intent.destination or intent.origin
    if location is None:
        return [
            clarifying_block(
                "Puedo buscar cargadores cerca de un hotel o destino, pero necesito una ciudad conocida o coordenadas.",
                ["ciudad o coordenadas", "conector si lo sabes"],
            )
        ]

    stations = get_nearby_stations(
        lat=location.lat,
        lon=location.lon,
        radius_km=80,
        connector=intent.vehicle_fields.get("connector"),
        available_only=False,
    )
    if not stations:
        return [
            block(
                f"destination-{uuid4().hex[:10]}",
                "DestinationChargingCard",
                {"destination": location.label, "needsConfirmation": True},
            ),
            block(
                f"risk-{uuid4().hex[:10]}",
                "RiskExplanationCard",
                {
                    "level": "alto",
                    "text": "No hay cargadores autorizados importados cerca de ese destino. No voy a inventar estaciones.",
                },
            ),
        ]

    top = stations[:3]
    return [
        block(
            f"destination-{uuid4().hex[:10]}",
            "DestinationChargingCard",
            {"destination": location.label, "needsConfirmation": True},
        ),
        block(
            f"stops-{uuid4().hex[:10]}",
            "AlternativeStopsList",
            {
                "stops": [
                    {
                        "name": item.station.name,
                        "powerKw": item.max_power_kw,
                        "distanceKm": item.distance_km,
                    }
                    for item in top
                ]
            },
        ),
        block(
            f"risk-{uuid4().hex[:10]}",
            "RiskExplanationCard",
            {
                "level": "medio",
                "text": "Muestro cargadores autorizados importados cerca del destino. Confirma acceso final, tarifa y disponibilidad antes de depender de ellos.",
            },
        ),
    ]


def route_planning_blocks(intent: ParsedIntent) -> list[dict]:
    if intent.origin is None or intent.destination is None:
        return []

    origin = Coordinate(lat=intent.origin.lat, lon=intent.origin.lon)
    destination = Coordinate(lat=intent.destination.lat, lon=intent.destination.lon)
    route = get_route_provider().route(origin, destination)
    plan = plan_route_with_persisted_stations(
        origin=origin,
        destination=destination,
        route=route,
        vehicle=intent.vehicle,
        preferences=intent.preferences,
        corridor_radius_km=25,
    )

    station = plan.recommendation.station
    blocks = [
        block(
            f"assistant-{uuid4().hex[:10]}",
            "AssistantMessage",
            {
                "text": (
                    "He decidido calcular ruta porque hay origen y destino. "
                    if intent.vehicle
                    else "He decidido explorar cargadores en ruta. Sin datos completos del coche no calculo autonomía."
                )
            },
        ),
        block(
            f"trip-{uuid4().hex[:10]}",
            "TripSummaryCard",
            {
                "origin": intent.origin.label,
                "destination": intent.destination.label,
                "battery": intent.vehicle_fields.get("battery"),
                "reserve": intent.preferences.reserve_min_percent,
            },
        ),
        block(
            f"route-{uuid4().hex[:10]}",
            "RouteSummaryCard",
            {
                "distanceKm": round(plan.route.distance_km, 1),
                "durationMin": plan.route.duration_min,
                "energyKwh": round_optional(plan.energy_kwh),
                "arrivalBattery": round_optional(plan.arrival_battery_percent),
            },
        ),
        block(
            f"stop-{uuid4().hex[:10]}",
            "RecommendedStopCard",
            {
                "name": station["name"],
                "powerKw": station["power_kw"],
                "detourMin": station["detour_min"],
                "confidence": "media",
            },
        ),
    ]
    if plan.alternatives:
        blocks.append(
            block(
                f"alternatives-{uuid4().hex[:10]}",
                "AlternativeStopsList",
                {
                    "stops": [
                        {
                            "name": alternative.station["name"],
                            "powerKw": alternative.station["power_kw"],
                            "distanceKm": alternative.station["distance_to_route_km"],
                        }
                        for alternative in plan.alternatives
                    ]
                },
            )
        )
    for warning in plan.warnings:
        blocks.append(block(f"risk-{uuid4().hex[:10]}", "RiskExplanationCard", {"level": "medio", "text": warning}))
    blocks.extend(
        [
            block(
                f"map-{uuid4().hex[:10]}",
                "MapPreviewCard",
                {"origin": intent.origin.label, "destination": intent.destination.label, "stop": station["name"]},
            ),
            block(
                f"actions-{uuid4().hex[:10]}",
                "ActionButtons",
                {
                    "actions": [
                        {
                            "label": "Abrir cargador en Maps",
                            "href": f"https://www.google.com/maps/search/?api=1&query={station['lat']},{station['lon']}",
                        },
                        {
                            "label": "Guardar plan",
                            "href": "",
                            "disabled": True,
                            "reason": "Disponible solo cuando el plan EV completo esté persistido en una cuenta.",
                        },
                    ]
                },
            ),
        ]
    )
    return blocks


def parse_intent(message: str) -> ParsedIntent:
    normalized = normalize(message)
    origin, destination = parse_route_locations(normalized)
    destination_search = parse_single_location(normalized)
    vehicle_fields = parse_vehicle_fields(normalized)
    vehicle = vehicle_from_fields(vehicle_fields)
    preferences = parse_preferences(normalized)

    is_destination_charge_request = bool(
        re.search(r"\b(hotel|alojamiento|destino|cerca|cercanos|cargadores cerca)\b", normalized)
    )
    is_near_me_request = bool(
        re.search(r"\bcerca de mi\b(?!\s+(hotel|alojamiento|destino|ciudad|parking))", normalized)
    )
    is_urgent_request = bool(
        re.search(r"\b(cargar ya|urgente|bateria baja|batería baja)\b", normalized) or is_near_me_request
    )
    has_explicit_route_language = bool(
        re.search(r"\b(ruta|viaj|viaje|ir desde|voy desde)\b", normalized)
        or re.search(r"(?:de|desde)\s+[a-z0-9 .-]+?\s+(?:a|hasta|hacia)\s+[a-z0-9 .-]+", normalized)
    )
    is_route_request = bool(has_explicit_route_language or (destination and re.search(r"\b(voy|ir|llegar)\b", normalized)))
    if is_destination_charge_request and not has_explicit_route_language:
        is_route_request = False

    return ParsedIntent(
        text=message,
        origin=origin,
        destination=destination,
        destination_search=destination_search,
        vehicle=vehicle,
        vehicle_fields=vehicle_fields,
        preferences=preferences,
        is_route_request=is_route_request,
        is_destination_charge_request=is_destination_charge_request,
        is_urgent_request=is_urgent_request,
    )


def parse_route_locations(text: str) -> tuple[ParsedLocation | None, ParsedLocation | None]:
    match = re.search(r"(?:de|desde)\s+([a-z0-9 .-]+?)\s+(?:a|hasta|hacia)\s+([a-z0-9 .-]+)", text)
    if match:
        return resolve_location(match.group(1)), resolve_location(match.group(2))

    destination_match = re.search(r"(?:a|hasta|hacia)\s+([a-z0-9 .-]{2,60})", text)
    destination = resolve_location(destination_match.group(1)) if destination_match else None
    origin_match = re.search(r"(?:de|desde)\s+([a-z0-9 .-]{2,60})", text)
    origin = resolve_location(origin_match.group(1)) if origin_match else None
    return origin, destination


def parse_single_location(text: str) -> ParsedLocation | None:
    coordinate = parse_coordinate_pair(text)
    if coordinate:
        return coordinate
    return resolve_location(text)


def parse_coordinate_pair(text: str) -> ParsedLocation | None:
    match = re.search(r"(-?\d{1,2}(?:[.,]\d+)?)\s*,\s*(-?\d{1,3}(?:[.,]\d+)?)", text)
    if not match:
        return None
    lat = float(match.group(1).replace(",", "."))
    lon = float(match.group(2).replace(",", "."))
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return None
    return ParsedLocation("Ubicación indicada", lat, lon)


def resolve_location(value: str) -> ParsedLocation | None:
    normalized = normalize(value)
    for key, location in KNOWN_LOCATIONS.items():
        if key in normalized:
            label, lat, lon = location
            return ParsedLocation(label, lat, lon)
    return None


def parse_vehicle_fields(text: str) -> dict:
    fields = {}
    battery = first_float(text, r"(?:al|a|con|en)\s*(\d{1,3})\s*%")
    if battery is not None and 0 <= battery <= 100:
        fields["battery"] = battery
    usable = first_float(text, r"(?:bateria util|capacidad|bateria).*?(\d+(?:[,.]\d+)?)\s*(?:kwh)?")
    if usable is not None:
        fields["usable_battery_kwh"] = usable
    consumption = first_float(text, r"(?:consumo|media).*?(\d+(?:[,.]\d+)?)\s*kwh\/?100\s*km")
    if consumption is not None:
        fields["consumption_kwh_per_100km"] = consumption
    power = first_float(text, r"(?:potencia|maxima|max|carga).*?(\d+(?:[,.]\d+)?)\s*kw")
    if power is not None:
        fields["max_charge_kw"] = power
    connector = parse_connector(text)
    if connector:
        fields["connector"] = connector
    return fields


def vehicle_from_fields(fields: dict) -> VehicleContext | None:
    required = {"battery", "usable_battery_kwh", "consumption_kwh_per_100km", "connector", "max_charge_kw"}
    if not required.issubset(fields):
        return None
    return VehicleContext(
        battery_percent=fields["battery"],
        usable_battery_kwh=fields["usable_battery_kwh"],
        consumption_kwh_per_100km=fields["consumption_kwh_per_100km"],
        connector=fields["connector"],
        max_charge_kw=fields["max_charge_kw"],
    )


def parse_preferences(text: str) -> Preferences:
    reserve = first_float(text, r"(?:reserva minima|reserva|minimo|no bajar de|no quiero bajar del)\s*(\d{1,2})\s*%")
    return Preferences(
        reserve_min_percent=min(max(reserve if reserve is not None else 20, 0), 80),
        prefer_fast=bool(re.search(r"\b(rapida|rapido|rapidez)\b", text)),
        prefer_cheap=bool(re.search(r"\b(barata|barato|economica|economico)\b", text)),
        prefer_low_stress=not bool(re.search(r"\b(rapida|rapido)\b", text)),
        avoid_single_connector=True,
        prefer_services=bool(re.search(r"\b(servicios|comer|bano|baño|restaurante|hotel)\b", text)),
        prefer_large_hubs=True,
    )


def parse_connector(text: str) -> str | None:
    if re.search(r"\bccs2\b|\bccs-2\b|\bccs\s+2\b", text):
        return "CCS2"
    if "chademo" in text:
        return "CHAdeMO"
    if re.search(r"\btype2\b|\btype 2\b|\btipo 2\b", text):
        return "Type2"
    return None


def first_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def round_optional(value: float | None) -> float | None:
    return round(value, 1) if isinstance(value, (int, float)) else None


def clarifying_block(question: str, fields: list[str]) -> dict:
    return block(f"clarify-{uuid4().hex[:10]}", "ClarifyingQuestionCard", {"question": question, "fields": fields})


def location_request_block(reason: str, title: str, body: str) -> dict:
    return block(
        f"location-{uuid4().hex[:10]}",
        "LocationRequestCard",
        {
            "reason": reason,
            "title": title,
            "body": body,
            "precision": "approximate",
            "manualFields": ["ciudad", "latitud", "longitud"],
        },
    )


def block(block_id: str, block_type: str, props: dict) -> dict:
    return {"id": block_id, "type": block_type, "version": 1, "props": props}


def validate_blocks(blocks: list[dict]) -> list[dict]:
    valid = []
    for index, item in enumerate(blocks):
        if not isinstance(item, dict):
            raise AgentResponseError("El agente devolvió un bloque inválido.")
        block_type = item.get("type")
        if block_type not in A2UI_COMPONENT_TYPES:
            valid.append(
                block(
                    f"invalid-{index}-{uuid4().hex[:8]}",
                    "ErrorFallbackCard",
                    {
                        "originalType": str(block_type),
                        "message": "El agente pidió un componente fuera del catálogo A2UI permitido.",
                    },
                )
            )
            continue
        props = item.get("props")
        original_props = props if isinstance(props, dict) else {}
        normalized_props = normalize_block_props(block_type, original_props)
        valid.append(
            {
                "id": str(item.get("id") or f"block-{index}-{uuid4().hex[:8]}"),
                "type": block_type,
                "version": int(item.get("version") or 1),
                "props": normalized_props,
            }
        )
        valid.extend(extra_blocks_from_props(block_type, original_props, index))
    return valid


def normalize_block_props(block_type: str, props: dict) -> dict:
    if block_type == "ClarifyingQuestionCard":
        question = props.get("question") or props.get("text") or props.get("message") or ""
        fields = props.get("fields")
        if not isinstance(fields, list):
            fields = []
            for item in props.get("questions") or props.get("options") or []:
                if isinstance(item, dict):
                    label = item.get("label") or item.get("text") or item.get("id")
                    if label:
                        fields.append(str(label))
                elif item:
                    fields.append(str(item))
        return {"question": str(question), "fields": fields}
    if block_type == "DestinationChargingCard":
        destination = (
            props.get("destination")
            or props.get("location")
            or props.get("city")
            or props.get("label")
            or props.get("name")
            or "Destino aproximado"
        )
        return {
            "destination": display_text(destination, "Destino aproximado"),
            "needsConfirmation": bool(props.get("needsConfirmation", props.get("approximate", True))),
        }
    if block_type == "RiskExplanationCard":
        text_value = props.get("text") or props.get("message") or props.get("description")
        if not text_value and isinstance(props.get("items"), list):
            text_value = " ".join(str(item) for item in props["items"] if item)
        if not text_value:
            text_value = props.get("title") or "Hay incertidumbre que debes confirmar antes de depender de este resultado."
        return {"level": str(props.get("level") or "medio"), "text": str(text_value)}
    if block_type == "LocationRequestCard":
        reason = props.get("reason")
        if reason not in {"urgent_charge", "nearby_chargers", "route_origin"}:
            reason = "nearby_chargers"
        precision = props.get("precision")
        if precision not in {"exact", "approximate"}:
            precision = "approximate"
        manual_fields = props.get("manualFields")
        if not isinstance(manual_fields, list):
            manual_fields = ["ciudad", "latitud", "longitud"]
        return {
            "reason": reason,
            "title": str(props.get("title") or "Necesito tu ubicación"),
            "body": str(
                props.get("body")
                or "Comparte tu ubicación o escribe una ciudad/coordenadas para continuar sin inventar resultados."
            ),
            "precision": precision,
            "manualFields": [str(item) for item in manual_fields if item],
        }
    return props


def display_text(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        for key in ("label", "name", "title", "text", "value"):
            nested = value.get(key)
            if nested:
                return display_text(nested, fallback)
        return fallback
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    match = re.search(r"['\"]label['\"]\s*:\s*['\"]([^'\"]+)", text)
    return match.group(1) if match else text


def extra_blocks_from_props(block_type: str, props: dict, index: int) -> list[dict]:
    if block_type == "DestinationChargingCard" and isinstance(props.get("stops"), list):
        return [
            block(
                f"stops-{index}-{uuid4().hex[:8]}",
                "AlternativeStopsList",
                {"stops": props["stops"]},
            )
        ]
    return []


def normalize(value: str) -> str:
    substitutions = str.maketrans("áéíóúüñ", "aeiouun")
    return value.lower().translate(substitutions)
