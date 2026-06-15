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
    ALLOWED_CONVERSATION_TOOLS,
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
    "LocationDetailCard",
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
            f"assistant-{uuid4().hex[:10]}",
            "AssistantMessage",
            {
                "text": (
                    "No he podido completar esta respuesta con fiabilidad. "
                    "No voy a asumir estaciones, coordenadas, precios ni estado del vehículo."
                )
            },
        ),
        clarifying_block(
            "Para continuar, envíame los datos críticos que tengas.",
            ["origen o ubicación", "destino si hay ruta", "batería actual", "conector"],
        ),
    ]


def run_codex_agent(message: str, history_blocks: list[dict] | None = None) -> list[dict]:
    history_blocks = history_blocks or []
    decision_message = contextualized_prompt(message, history_blocks)
    tool_history: list[dict[str, Any]] = []
    seen_calls: set[str] = set()
    max_tool_calls = getattr(settings, "KALMIO_CODEX_MAX_TOOL_CALLS", 3)

    for _ in range(max_tool_calls + 1):
        decision = request_codex_decision(decision_message, tool_history=tool_history)
        if decision["type"] == "final":
            return validated_or_repaired_final_blocks(
                decision_message,
                decision["blocks"],
                tool_history,
                history_blocks=history_blocks,
            )

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

        if not result.get("ok") and decision["tool"] not in ALLOWED_CONVERSATION_TOOLS:
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
    history_blocks: list[dict] | None = None,
) -> list[dict]:
    blocks = validate_blocks(candidate_blocks)
    issues = a2ui_contract_issues(blocks, tool_history, message, history_blocks=history_blocks)
    if not issues:
        return blocks

    repair_decision = request_codex_decision(
        message,
        tool_history=tool_history,
        repair_issues=issues,
        candidate_blocks=candidate_blocks,
    )
    if repair_decision["type"] != "final":
        return fallback_from_tool_history(
            tool_history,
            "El agente intentó pedir otra herramienta durante la reparación A2UI.",
            message,
        )

    repaired_blocks = validate_blocks(repair_decision["blocks"])
    remaining_issues = a2ui_contract_issues(repaired_blocks, tool_history, message, history_blocks=history_blocks)
    if remaining_issues:
        return fallback_from_tool_history(
            tool_history,
            "El agente no pudo reparar el contrato A2UI: " + "; ".join(remaining_issues),
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


def request_codex_decision(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if tool_history is not None:
        kwargs["tool_history"] = tool_history
    if repair_issues is not None:
        kwargs["repair_issues"] = repair_issues
    if candidate_blocks is not None:
        kwargs["candidate_blocks"] = candidate_blocks
    return run_codex_decision(message, **kwargs)


def codex_prompt(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> str:
    tool_history = tool_history or []
    repair_issues = repair_issues or []
    candidate_blocks = candidate_blocks or []
    known_locations = {
        key: {"label": value[0], "lat": value[1], "lon": value[2]} for key, value in KNOWN_LOCATIONS.items()
    }
    tool_instructions = (
        "Herramientas permitidas. Puedes llamar solo una por respuesta tool_call:\n"
        '- resolve_location: resuelve una ciudad o texto conocido. Args: {"query":"ciudad o texto"}\n'
        "- search_destination_chargers: busca cargadores autorizados alrededor de una ubicación ya resuelta o "
        'coordenadas dadas por el usuario. Args: {"location":{"label":"...","lat":0,"lon":0},"connector":null,'
        '"radius_km":80,"limit":3}\n'
        "- plan_route: calcula ruta y paradas con proveedor y datos autorizados. Args: "
        '{"origin":{"label":"...","lat":0,"lon":0},"destination":{"label":"...","lat":0,"lon":0},'
        '"vehicle":null,"preferences":{"reserve_min_percent":20,"max_useful_power_kw":null},"corridor_radius_km":25}\n'
        "Ubicaciones internas conocidas que puedes usar para argumentos de herramienta, sin inventar otras coordenadas: "
        f"{json.dumps(known_locations, ensure_ascii=False)}.\n"
    )
    behavior_instructions = (
        "Comportamiento EV esperado:\n"
        "- Actúa como copiloto EV: usa el historial útil, acepta correcciones naturales y evita sonar como formulario.\n"
        "- Si el usuario dice que necesita cargar ya y no hay ubicación, pide solo ubicación actual, ciudad/zona o coordenadas. "
        "No pidas destino para una carga urgente.\n"
        "- Si después de una petición urgente el usuario da una ciudad, zona o coordenadas, trátalo como continuación de esa urgencia "
        "y usa herramientas si hay ubicación suficiente.\n"
        "- Si el usuario corrige la ubicación, descarta la ubicación anterior para este turno, conserva batería, conector y preferencias "
        "si siguen teniendo sentido, y vuelve a buscar con la ubicación corregida.\n"
        "- Si el usuario pregunta por un fallo anterior, no contradigas bloques ya validados: si el historial mostró cargadores, dilo y "
        "explica que el problema fue de validación, cobertura, ubicación aproximada o datos autorizados, sin culpar al usuario.\n"
        "- Para una calle, POI o zona concreta, intenta resolver primero la parte conocida con resolve_location. Si no puedes ubicar "
        "la calle exacta, di explícitamente que todavía no puedes ubicar esa calle exacta; ofrece buscar con la ciudad como aproximación "
        "o usar coordenadas. No inventes coordenadas de calles.\n"
        "- Para rutas sin consumo o perfil completo, puedes llamar plan_route para explorar cargadores en ruta, pero no inventes "
        "autonomía, energía ni batería de llegada si la herramienta no las devuelve.\n"
        "- Para hotel/destino con ciudad pero sin hotel exacto, puedes buscar alrededor de la ciudad como aproximación o pedir hotel/zona "
        "si la precisión es crítica. No lo conviertas en ruta salvo que el usuario pida viajar entre origen y destino.\n"
        "- Si search_destination_chargers devuelve stops y decides mostrar UrgentChargeCard o RecommendedStopCard, usa exactamente "
        "stops[0].name y sus métricas trazables; evita placeholders como cargador por confirmar cuando ya hay estaciones.\n"
        "- Si una herramienta permitida falla, responde con una explicación específica al contexto y una siguiente acción mínima; "
        "no fabriques resultados para tapar el fallo.\n"
        "- En urgencia o batería baja, muestra pocos pasos: una recomendación principal, como mucho 2 alternativas, riesgo explícito "
        "y un CTA de navegación si tienes lat/lon trazables. Si conoces la batería, inclúyela en UrgentChargeCard.\n"
        "- Con batería muy baja (aprox. 10% o menos) o el usuario no conoce la zona, prioriza menor riesgo: distancia corta, más conectores/EVSEs, fiabilidad, "
        "potencia compatible y una navegación clara. No listes muchas opciones y marca el riesgo como alto si el margen es crítico.\n"
        "- Si el cargador previsto está ocupado, no repitas ese mismo cargador como plan B. Usa alternativas ya validadas o vuelve a buscar "
        "en la ubicación previa, ordenando por menor riesgo y explicando que la disponibilidad puede cambiar.\n"
        "- Si el usuario está en carretera y quiere poco desvío, piensa en corredor/ruta: pide carretera, destino u origen-destino si faltan. "
        "Si hay origen y destino suficientes, usa plan_route; no reduzcas el caso a una búsqueda urbana cerca de una ciudad cualquiera.\n"
        "- En rutas con solo porcentaje de batería pero sin consumo, capacidad o modelo fiable, puedes mostrar cargadores en ruta, "
        "pero no digas que cumple llegada, reserva mínima, pocas paradas o 'me da' como hecho. Pide modelo/consumo/autonomía para verificarlo.\n"
        "- Si el usuario dice que su coche carga como máximo a X kW o que no necesita ultrarrápidos, pasa X como "
        "preferences.max_useful_power_kw en plan_route si haces esa llamada. Si aun así una estación de más potencia es la mejor por "
        "corredor, fiabilidad o conectores, explícale explícitamente que el cargador ofrece más potencia de la que su coche aprovechará, "
        "que no la eliges por esos kW extra y no presentes la potencia superior como ventaja.\n"
        "- Si el usuario pide una restricción dura de llegada, como llegar con 25% o no llegar justo, trátala como límite que no puedes validar "
        "sin perfil de vehículo; no la presentes como cumplida si plan_route devuelve planningLevel=chargers_only.\n"
        "- Para viajes futuros, recuerda que disponibilidad, tarifas y acceso pueden cambiar antes de la salida.\n"
        "- Si el usuario viaja con niños o pide comodidad, prioriza hubs, servicios, baños, cafetería/restaurante, fiabilidad, dirección clara y baja complejidad. "
        "Si la herramienta no trae servicios suficientes, dilo explícitamente y usa los datos trazables disponibles; no finjas servicios.\n"
        "- En hotel, destino o estancia, si hay ciudad/POI suficiente, puedes buscar cargadores alrededor como aproximación sin convertirlo en ruta. "
        "Si la herramienta devuelve stops, muestra bloques estructurados como DestinationChargingCard/StayPlanningCard y AlternativeStopsList o RecommendedStopCard; no dejes las estaciones solo en texto.\n"
        "- Si el usuario menciona una estancia de varios días, piensa en carga durante la estancia y posible vuelta. Si falta origen para ida/vuelta, pídelo; si no, busca carga en destino.\n"
        "Ejemplos críticos que debes seguir por analogía, no como reglas rígidas:\n"
        "- Usuario: 'Necesito cargar ya' -> pide solo ubicación actual/ciudad/zona/coordenadas; no pidas destino, consumo ni hotel.\n"
        "- Historial: urgencia sin ubicación. Usuario: 'En Córdoba' -> usa Córdoba para buscar cargadores cercanos y devuelve "
        "bloques estructurados con estación trazable y riesgo de disponibilidad/tarifa/acceso.\n"
        "- Historial: 'Estoy en Córdoba con 18% y CCS2'. Usuario: 'Me equivoqué, estoy en Valencia centro' -> vuelve a buscar "
        "en Valencia, conserva battery=18 y conector CCS2 si filtras o explicas el resultado, y no menciones Córdoba como ubicación actual.\n"
        "- Usuario pregunta por 'Paseo de la Victoria de Córdoba' -> si solo puedes resolver Córdoba, di que no puedes ubicar esa calle exacta "
        "todavía y que usas Córdoba como aproximación; si muestras cargadores, deja claro ese límite.\n"
        "- Usuario: 'Voy a dormir en Valencia, busca cargadores cerca del hotel' -> no lo conviertas en ruta; puedes buscar Valencia como "
        "aproximación o pedir hotel/zona para precisión.\n"
        "- Historial: hotel sin cargador y el usuario añade 'Valencia centro' -> busca cargadores en Valencia centro y devuelve "
        "DestinationChargingCard + AlternativeStopsList o RecommendedStopCard con estaciones trazables.\n"
        "- Usuario: 'Voy el finde a Granada y duermo cerca de la Alhambra' -> si conoces Alhambra/Granada, busca cargadores cerca como "
        "destino aproximado y explica que el hotel exacto afinaría la búsqueda.\n"
        "- Usuario: 'El cargador al que iba está ocupado, dame un plan B' tras una recomendación -> usa la siguiente alternativa trazable "
        "y devuelve bloques estructurados, no solo texto.\n"
        "- Usuario: 'Estoy en carretera con 18%, no quiero desviarme mucho' sin ruta ni ubicación -> pregunta por carretera/destino o "
        "coordenadas actuales, porque el corredor es crítico.\n"
        "- Usuario: 'Voy de Zaragoza a Barcelona y quiero llegar con al menos 25%' sin consumo/modelo -> busca cargadores si puedes, "
        "pero di que no puedes validar ese 25% todavía y pide perfil del coche o consumo.\n"
        "- Usuario: 'Mi coche carga máximo a 100 kW, no necesito ultrarrápidos. Voy de Madrid a Valencia' -> usa "
        "preferences.max_useful_power_kw=100 si planificas ruta; si la parada trazable ofrece 240 kW, di que el coche no aprovechará "
        "más de 100 kW y que la recomiendas por ubicación/fiabilidad/conectores, no por ultrapotencia.\n"
    )
    catalog_instructions = (
        "Catálogo A2UI permitido por propósito, no por reglas rígidas de intención:\n"
        "- AssistantMessage: respuesta breve en lenguaje natural, especialmente para aclarar límites o cerrar una respuesta simple.\n"
        "- UserMessage: eco del usuario; normalmente lo añade Django si falta.\n"
        "- TripSummaryCard: resumen de origen, destino, batería y reserva cuando esos datos ya están claros.\n"
        "- RouteSummaryCard: métricas devueltas por plan_route.\n"
        "- RecommendedStopCard: parada recomendada devuelta por una herramienta.\n"
        "- AlternativeRoutesList: alternativas de ruta cuando existan datos de herramienta para ellas.\n"
        "- AlternativeStopsList: lista de cargadores/paradas devueltos por una herramienta.\n"
        "- RiskExplanationCard: incertidumbre, datos ausentes, proveedor no disponible, disponibilidad/tarifa/acceso por confirmar.\n"
        "- CostComparisonCard: solo si una herramienta devuelve costes; ahora normalmente no hay datos de coste.\n"
        "- UrgentChargeCard: plan de carga inmediata con cargador cercano trazable a herramienta y ubicación suficiente.\n"
        "- DestinationChargingCard: contexto de carga en destino, hotel, ciudad o estancia.\n"
        "- StayPlanningCard: plan de varios días cuando el usuario esté organizando una estancia.\n"
        "- MapPreviewCard: vista contextual con origen/destino/parada conocidos; no inventes geometría.\n"
        "- ActionButtons: solo acciones seguras como abrir navegación/mapa, ajustar búsqueda o guardar deshabilitado si no procede.\n"
        "- ClarifyingQuestionCard: faltan datos críticos para decidir con seguridad.\n"
        "- LocationRequestCard: ubicación actual necesaria; debe ofrecer ciudad/coordenadas manuales.\n"
        "- LocationDetailCard: muestra la ubicación usada cuando procede; coordenadas solo de usuario o herramienta.\n"
        "- PreferenceChips: preferencias rápidas sin fingir decisiones ya tomadas.\n"
        "- ErrorFallbackCard: reservado para fallos o componentes no soportados.\n"
    )
    output_instructions = (
        "Devuelve un único objeto JSON compacto, sin markdown, sin texto exterior y sin bloques de código. Formas válidas:\n"
        '{"type":"tool_call","intent":"...","confidence":0.0,"tool":"search_destination_chargers","args":{...},'
        '"rationale":"metadata interna breve"}\n'
        '{"type":"final","intent":"...","confidence":0.0,"blocks":[{"id":"...","type":"AssistantMessage","version":1,'
        '"props":{"text":"..."}}],"metadata":{"rationale":"metadata interna breve"}}\n'
        "intent, confidence, rationale y metadata son opcionales y no se muestran al usuario. "
        f"Tipos A2UI permitidos: {', '.join(sorted(A2UI_COMPONENT_TYPES))}. "
        "Para ClarifyingQuestionCard usa props question y fields. "
        "Para LocationDetailCard usa props label, lat, lon, precision, context y needsConfirmation. "
        "No inventes disponibilidad, precios, estaciones, coordenadas ni estado del vehículo. "
        "No afirmes cargadores o rutas si no vienen de herramientas, datos autorizados o texto explícito del usuario. "
        "Si faltan datos críticos, pregunta. Si el proveedor o los datos autorizados no permiten responder, falla de forma explícita. "
        "Puedes pedir otra herramienta si falta un dato necesario, pero no repitas una llamada ya hecha con los mismos argumentos. "
        "Elige los bloques A2UI que aporten claridad al usuario según la conversación completa. "
        "Cuando tengas resultados de herramientas con estaciones, rutas o métricas, prefiere bloques estructurados para esos hechos verificables "
        "y usa AssistantMessage solo como introducción breve, cierre o aclaración de límites. "
        "Una respuesta simple también es válida si evita sobreafirmar o si no hay datos estructurados suficientes."
    )
    if repair_issues:
        return (
            "Eres el agente conversacional de Kalmio para planificación EV. Tu respuesta final anterior fue rechazada "
            "por el contrato de seguridad/datos A2UI. No pidas herramientas en esta reparación. "
            "Devuelve solo type=final con blocks A2UI válidos; puedes simplificar la UI si no puedes demostrar los datos. "
            "Problemas detectados:\n"
            f"{json.dumps(repair_issues, ensure_ascii=False)}\n"
            "Usa solo datos del historial de herramientas; no inventes estaciones, precios, disponibilidad, coordenadas ni estado del vehículo.\n"
            f"Usuario: {message}\n"
            f"Historial de herramientas: {json.dumps(tool_history, ensure_ascii=False)}\n"
            f"Bloques rechazados: {json.dumps(candidate_blocks, ensure_ascii=False)}\n"
            f"{behavior_instructions}"
            f"{catalog_instructions}"
            f"{output_instructions}"
        )
    if tool_history:
        return (
            "Eres el agente conversacional de Kalmio para planificación EV. Ya se ejecutaron estas herramientas "
            "internas de Django. Decide si necesitas otra herramienta permitida o si ya puedes devolver type=final con A2UI.\n"
            f"Usuario: {message}\n"
            f"Historial de herramientas: {json.dumps(tool_history, ensure_ascii=False)}\n"
            f"{tool_instructions}"
            f"{behavior_instructions}"
            f"{catalog_instructions}"
            f"{output_instructions}"
        )
    return (
        "Eres el agente conversacional de Kalmio, una PWA móvil para planificar viajes y carga EV. "
        "Interpreta la conversación completa y decide intención, herramientas y bloques A2UI; Django solo validará seguridad y datos.\n"
        f"{tool_instructions}"
        f"{behavior_instructions}"
        f"{catalog_instructions}"
        f"{output_instructions}\n"
        f"Usuario: {message}"
    )


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
                    getattr(settings, "KALMIO_CODEX_MODEL", "gpt-5.4-mini"),
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
            intent = parse_intent(message)
            nearest = stops[0] if stops and isinstance(stops[0], dict) else {}
            return [
                location_detail_block(
                    location,
                    context="Ubicación usada para buscar cargadores urgentes",
                    needs_confirmation=True,
                ),
                block(
                    f"urgent-{uuid4().hex[:10]}",
                    "UrgentChargeCard",
                    {
                        "battery": intent.vehicle_fields.get("battery"),
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
            location_detail_block(
                location,
                context="Destino usado para buscar cargadores",
                needs_confirmation=True,
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
    latest_result = latest_tool_result(tool_history)
    level = "alto" if latest_result and not latest_result.get("ok") else "medio"
    return [
        block(
            f"assistant-{uuid4().hex[:10]}",
            "AssistantMessage",
            {
                "text": (
                    "No he podido cerrar una respuesta fiable con los datos validados. "
                    "No voy a completar estaciones, coordenadas, precios ni disponibilidad por mi cuenta."
                )
            },
        ),
        block(
            f"risk-{uuid4().hex[:10]}",
            "RiskExplanationCard",
            {"level": level, "text": user_facing_failure_text(reason)},
        ),
    ]


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


def a2ui_contract_issues(
    blocks: list[dict],
    tool_history: list[dict[str, Any]],
    message: str = "",
    history_blocks: list[dict] | None = None,
) -> list[str]:
    facts = tool_fact_index(tool_history, history_blocks=history_blocks or [])
    facts["vehicle"].update(parse_vehicle_fields(normalize(message)))
    explicit_coordinates = coordinates_from_text(message)
    issues: list[str] = []

    for item in blocks:
        if not isinstance(item, dict):
            issues.append("Todos los bloques A2UI deben ser objetos.")
            continue
        block_type = item.get("type")
        props = item.get("props") if isinstance(item.get("props"), dict) else {}

        if block_type == "AlternativeStopsList":
            issues.extend(alternative_stops_contract_issues(props, facts))
        elif block_type == "RecommendedStopCard":
            issues.extend(required_station_reference_contract_issues("RecommendedStopCard.name", props.get("name"), facts))
            issues.extend(station_reference_contract_issues("RecommendedStopCard.name", props.get("name"), facts))
            issues.extend(station_metric_contract_issues("RecommendedStopCard", props, facts))
        elif block_type == "UrgentChargeCard":
            issues.extend(required_station_reference_contract_issues("UrgentChargeCard.nearest", props.get("nearest"), facts))
            issues.extend(station_reference_contract_issues("UrgentChargeCard.nearest", props.get("nearest"), facts))
            issues.extend(station_metric_contract_issues("UrgentChargeCard", {"name": props.get("nearest"), **props}, facts))
            issues.extend(urgent_battery_contract_issues(props, facts))
        elif block_type == "RouteSummaryCard":
            issues.extend(route_summary_contract_issues(props, facts))
        elif block_type == "LocationDetailCard":
            issues.extend(location_detail_contract_issues(props, facts, explicit_coordinates))
        elif block_type == "MapPreviewCard":
            issues.extend(station_reference_contract_issues("MapPreviewCard.stop", props.get("stop"), facts))
        elif block_type == "ActionButtons":
            issues.extend(action_buttons_contract_issues(props))
        elif block_type == "CostComparisonCard":
            issues.extend(cost_contract_issues(props))
        elif block_type == "RiskExplanationCard":
            issues.extend(risk_explanation_contract_issues(props))

    return dedupe_preserve_order(issues)


def tool_fact_index(tool_history: list[dict[str, Any]], history_blocks: list[dict] | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {"stations": {}, "locations": [], "routes": [], "vehicle": {}}
    add_history_facts(facts, history_blocks or [])
    for entry in tool_history:
        if not isinstance(entry, dict):
            continue
        call = entry.get("call") if isinstance(entry.get("call"), dict) else {}
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        for key in ("location", "origin", "destination"):
            add_location_fact(facts, args.get(key))

        result = entry.get("result")
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        for key in ("location", "origin", "destination"):
            add_location_fact(facts, result.get(key))
        stops = result.get("stops")
        if isinstance(stops, list):
            for stop in stops:
                add_station_fact(facts, stop)
        alternatives = result.get("alternatives")
        if isinstance(alternatives, list):
            for stop in alternatives:
                add_station_fact(facts, stop)
        add_station_fact(facts, result.get("recommendation"))
        if (result.get("tool") or call.get("tool")) == "plan_route":
            facts["routes"].append(result)
    return facts


def add_history_facts(facts: dict[str, Any], history_blocks: list[dict]) -> None:
    for item in history_blocks:
        if not isinstance(item, dict):
            continue
        block_type = item.get("type")
        props = item.get("props") if isinstance(item.get("props"), dict) else {}
        if block_type == "UserMessage":
            text = str(props.get("text") or "")
            facts["vehicle"].update(parse_vehicle_fields(normalize(text)))
        elif block_type == "AlternativeStopsList":
            stops = props.get("stops")
            if isinstance(stops, list):
                for stop in stops:
                    add_station_fact(facts, stop)
        elif block_type == "RecommendedStopCard":
            add_station_fact(facts, props)
        elif block_type == "UrgentChargeCard":
            add_station_fact(
                facts,
                {
                    "name": props.get("nearest"),
                    "distanceKm": props.get("distanceKm"),
                },
            )
        elif block_type == "LocationDetailCard":
            add_location_fact(facts, props)
        elif block_type == "RouteSummaryCard":
            facts["routes"].append(props)


def add_station_fact(facts: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    name = display_text(value.get("name"), "")
    if not name:
        return
    key = station_key(name)
    current = facts["stations"].setdefault(key, {"name": name})
    for field in (
        "powerKw",
        "distanceKm",
        "detourMin",
        "confidence",
        "lat",
        "lon",
        "availableEvses",
        "connectorTypes",
    ):
        if field in value:
            current[field] = value.get(field)


def add_location_fact(facts: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    lat = optional_float(value.get("lat"))
    lon = optional_float(value.get("lon"))
    if lat is None or lon is None:
        return
    facts["locations"].append({"label": display_text(value.get("label"), "Ubicación indicada"), "lat": lat, "lon": lon})


def alternative_stops_contract_issues(props: dict, facts: dict[str, Any]) -> list[str]:
    stops = props.get("stops")
    if not isinstance(stops, list):
        return ["AlternativeStopsList.props.stops debe ser una lista."]
    issues: list[str] = []
    for index, stop in enumerate(stops):
        if not isinstance(stop, dict):
            issues.append(f"AlternativeStopsList.stops[{index}] debe ser un objeto.")
            continue
        name = display_text(stop.get("name"), "")
        if not name:
            issues.append(f"AlternativeStopsList.stops[{index}] necesita name.")
            continue
        issues.extend(station_reference_contract_issues(f"AlternativeStopsList.stops[{index}].name", name, facts))
        issues.extend(station_metric_contract_issues(f"AlternativeStopsList.stops[{index}]", stop, facts))
    return issues


def station_reference_contract_issues(label: str, value: Any, facts: dict[str, Any]) -> list[str]:
    name = display_text(value, "")
    if not name or generic_station_label(name):
        return []
    if not facts["stations"]:
        return [f"{label} menciona una estación sin resultado de herramienta trazable."]
    if station_key(name) not in facts["stations"]:
        return [f"{label} no coincide con ninguna estación devuelta por las herramientas: {name}."]
    return []


def required_station_reference_contract_issues(label: str, value: Any, facts: dict[str, Any]) -> list[str]:
    name = display_text(value, "")
    if facts["stations"] and generic_station_label(name):
        return [f"{label} debe usar una estación trazable cuando hay resultados de herramienta."]
    return []


def station_metric_contract_issues(label: str, props: dict, facts: dict[str, Any]) -> list[str]:
    name = display_text(props.get("name") or props.get("nearest"), "")
    if not name or generic_station_label(name):
        return []
    source = facts["stations"].get(station_key(name))
    if not source:
        return []

    issues: list[str] = []
    for field in ("powerKw", "distanceKm", "detourMin", "lat", "lon", "availableEvses"):
        if field not in props:
            continue
        rendered = props.get(field)
        expected = source.get(field)
        if rendered is None:
            continue
        if expected is None:
            issues.append(f"{label}.{field} no está en el resultado de herramienta para {name}.")
        elif not values_match(rendered, expected):
            issues.append(f"{label}.{field} no coincide con el dato de herramienta para {name}.")
    for price_field in ("price", "priceKwh", "pricePerKwh", "pricePerKwhEur"):
        if props.get(price_field) is not None:
            issues.append(f"{label}.{price_field} no puede mostrarse porque ninguna herramienta devuelve precios.")
    return issues


def urgent_battery_contract_issues(props: dict, facts: dict[str, Any]) -> list[str]:
    expected = facts.get("vehicle", {}).get("battery")
    if expected is None:
        return []
    rendered = props.get("battery")
    if rendered is None:
        return ["UrgentChargeCard.battery debe conservar la batería explícita del conductor."]
    if not values_match(rendered, expected):
        return ["UrgentChargeCard.battery no coincide con la batería explícita del conductor."]
    return []


def route_summary_contract_issues(props: dict, facts: dict[str, Any]) -> list[str]:
    if not facts["routes"]:
        return ["RouteSummaryCard necesita un resultado plan_route trazable."]
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
            issues.append(f"RouteSummaryCard.{field} no está en el resultado plan_route.")
        elif not values_match(rendered, expected):
            issues.append(f"RouteSummaryCard.{field} no coincide con plan_route.")
    return issues


def location_detail_contract_issues(
    props: dict,
    facts: dict[str, Any],
    explicit_coordinates: list[tuple[float, float]],
) -> list[str]:
    lat = optional_float(props.get("lat"))
    lon = optional_float(props.get("lon"))
    if lat is None and lon is None:
        return []
    if lat is None or lon is None:
        return ["LocationDetailCard necesita lat y lon válidos cuando muestra coordenadas."]
    if coordinate_traced(lat, lon, facts["locations"], explicit_coordinates):
        return []
    return ["LocationDetailCard muestra coordenadas que no vienen del usuario ni de una herramienta."]


def action_buttons_contract_issues(props: dict) -> list[str]:
    actions = props.get("actions")
    if not isinstance(actions, list):
        return ["ActionButtons.props.actions debe ser una lista."]
    issues: list[str] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            issues.append(f"ActionButtons.actions[{index}] debe ser un objeto.")
            continue
        label = normalize(str(action.get("label") or ""))
        if any(term in label for term in ("reserv", "pagar", "pago", "booking", "payment", "comprar")):
            issues.append(f"ActionButtons.actions[{index}] pide una acción no soportada por Kalmio.")
        href = action.get("href")
        if href in (None, ""):
            if not action.get("disabled"):
                issues.append(f"ActionButtons.actions[{index}] necesita un href soportado o estar deshabilitada.")
            if action.get("action") or action.get("type"):
                issues.append(f"ActionButtons.actions[{index}] usa un handler que el frontend no soporta.")
            continue
        href_text = str(href).strip().lower()
        if not (href_text.startswith("https://") or href_text.startswith("http://")):
            issues.append(f"ActionButtons.actions[{index}].href debe ser http(s) o vacío.")
        if href_text.startswith("javascript:"):
            issues.append(f"ActionButtons.actions[{index}].href no puede ejecutar scripts.")
    return issues


def cost_contract_issues(props: dict) -> list[str]:
    for field in ("estimatedCostEur", "savingEur", "price", "pricePerKwh"):
        if props.get(field) is not None:
            return ["CostComparisonCard no puede mostrar costes porque ninguna herramienta actual devuelve precios."]
    return []


def risk_explanation_contract_issues(props: dict) -> list[str]:
    text = display_text(props.get("text"), "")
    normalized = normalize(text).strip(" .:")
    if len(normalized) < 20 or normalized in {
        "antes de salir",
        "antes de confiar en ellas",
        "datos",
        "riesgo",
        "aviso",
        "precaucion",
    }:
        return ["RiskExplanationCard.text debe explicar la incertidumbre o el riesgo de forma concreta."]
    return []


def coordinates_from_text(value: str) -> list[tuple[float, float]]:
    coordinates = []
    for match in re.finditer(r"(-?\d{1,2}(?:[.,]\d+)?)\s*,\s*(-?\d{1,3}(?:[.,]\d+)?)", value):
        lat = optional_float(match.group(1))
        lon = optional_float(match.group(2))
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            coordinates.append((lat, lon))
    return coordinates


def coordinate_traced(
    lat: float,
    lon: float,
    tool_locations: list[dict[str, Any]],
    explicit_coordinates: list[tuple[float, float]],
) -> bool:
    for location in tool_locations:
        if close_coordinates(lat, lon, location.get("lat"), location.get("lon")):
            return True
    for explicit_lat, explicit_lon in explicit_coordinates:
        if close_coordinates(lat, lon, explicit_lat, explicit_lon):
            return True
    return False


def close_coordinates(lat: float, lon: float, expected_lat: Any, expected_lon: Any) -> bool:
    other_lat = optional_float(expected_lat)
    other_lon = optional_float(expected_lon)
    if other_lat is None or other_lon is None:
        return False
    return abs(lat - other_lat) <= 0.01 and abs(lon - other_lon) <= 0.01


def values_match(rendered: Any, expected: Any) -> bool:
    rendered_number = optional_float(rendered)
    expected_number = optional_float(expected)
    if rendered_number is not None and expected_number is not None:
        return abs(rendered_number - expected_number) <= 0.1
    return str(rendered).strip() == str(expected).strip()


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def station_key(value: str) -> str:
    return normalize(display_text(value, "")).strip()


def generic_station_label(value: str) -> bool:
    normalized = station_key(value)
    return not normalized or any(term in normalized for term in ("por confirmar", "no disponible", "no calculado"))


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
    state_summary = conversation_state_summary(history_blocks)
    if not transcript:
        return current_message
    state_line = f"{state_summary}\n" if state_summary else ""
    return (
        "Conversación disponible de Kalmio. Usa el historial para resolver referencias y datos parciales; "
        "si el usuario cambia claramente de objetivo, sigue el mensaje actual.\n"
        f"{state_line}"
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


def conversation_state_summary(history_blocks: list[dict]) -> str:
    vehicle_fields: dict[str, Any] = {}
    for text in recent_user_message_texts(history_blocks, limit=8):
        vehicle_fields.update(parse_vehicle_fields(normalize(text)))

    parts = []
    battery = vehicle_fields.get("battery")
    if battery is not None:
        parts.append(f"batería {battery:g}%")
    connector = vehicle_fields.get("connector")
    if connector:
        parts.append(f"conector {connector}")
    if not parts:
        return ""
    return (
        "Datos explícitos previos del conductor que pueden seguir vigentes si el usuario no los corrige: "
        + ", ".join(parts)
        + "."
    )


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
    if block_type == "RecommendedStopCard":
        return (
            "Parada recomendada previa: "
            f"{props.get('name')}, potencia {props.get('powerKw')} kW, "
            f"distancia {props.get('distanceKm')} km, desvío {props.get('detourMin')} min."
        )
    if block_type == "DestinationChargingCard":
        return f"Resultado previo de carga en destino: {props.get('destination')}."
    if block_type == "LocationDetailCard":
        return (
            "Ubicación validada previamente: "
            f"{props.get('label')} ({props.get('lat')}, {props.get('lon')}), "
            f"contexto {props.get('context')}, confirmar {props.get('needsConfirmation')}."
        )
    if block_type == "TripSummaryCard":
        return (
            "Resumen previo de viaje: "
            f"origen {props.get('origin')}, destino {props.get('destination')}, "
            f"batería {props.get('battery')}, reserva {props.get('reserve')}."
        )
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
        location_detail_block(
            location,
            context="Ubicación usada para buscar cargadores urgentes",
            needs_confirmation=True,
        ),
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
            location_detail_block(
                location,
                context="Destino usado para buscar cargadores",
                needs_confirmation=True,
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
        location_detail_block(
            location,
            context="Destino usado para buscar cargadores",
            needs_confirmation=True,
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
    battery = first_float(text, r"(?:al|a|con|en|tengo)\s+(?:un\s+)?(\d{1,3})\s*%")
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


def location_detail_block(
    location: dict[str, Any] | ParsedLocation,
    *,
    context: str,
    needs_confirmation: bool,
) -> dict:
    if isinstance(location, ParsedLocation):
        label = location.label
        lat = location.lat
        lon = location.lon
    else:
        label = display_text(location.get("label") or location.get("name"), "Ubicación indicada")
        lat = location.get("lat")
        lon = location.get("lon")
    return block(
        f"location-detail-{uuid4().hex[:10]}",
        "LocationDetailCard",
        {
            "label": label,
            "lat": lat,
            "lon": lon,
            "precision": "approximate",
            "context": context,
            "needsConfirmation": needs_confirmation,
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
    if block_type == "UrgentChargeCard":
        recommended_stop = props.get("recommendedStop") if isinstance(props.get("recommendedStop"), dict) else {}
        nearest = (
            props.get("nearest")
            or props.get("name")
            or props.get("stationName")
            or props.get("chargerName")
            or recommended_stop.get("name")
            or props.get("station")
            or props.get("charger")
        )
        battery = props.get("battery")
        if battery is None:
            battery = props.get("batteryPercent")
        if battery is None:
            battery = props.get("battery_percent")
        if battery is None:
            battery = props.get("batteryLevel")
        if battery is None:
            battery = props.get("currentBattery")
        distance_km = props.get("distanceKm")
        if distance_km is None:
            distance_km = recommended_stop.get("distanceKm")
        return {
            "battery": battery,
            "nearest": display_text(nearest, "Cargador cercano por confirmar"),
            "distanceKm": distance_km,
        }
    if block_type == "RecommendedStopCard":
        recommended_stop = props.get("recommendedStop") if isinstance(props.get("recommendedStop"), dict) else {}
        name = props.get("name") or recommended_stop.get("name") or props.get("station") or props.get("charger")
        power_kw = props.get("powerKw")
        if power_kw is None:
            power_kw = recommended_stop.get("powerKw")
        distance_km = props.get("distanceKm")
        if distance_km is None:
            distance_km = recommended_stop.get("distanceKm")
        detour_min = props.get("detourMin")
        if detour_min is None:
            detour_min = recommended_stop.get("detourMin")
        return {
            **props,
            "name": display_text(name, "Cargador recomendado"),
            "powerKw": power_kw,
            "distanceKm": distance_km,
            "detourMin": detour_min,
            "confidence": str(props.get("confidence") or recommended_stop.get("confidence") or "media"),
        }
    if block_type == "DestinationChargingCard":
        destination = (
            props.get("destination")
            or props.get("location")
            or props.get("locationLabel")
            or props.get("hotel")
            or props.get("hotelName")
            or props.get("city")
            or props.get("label")
            or props.get("name")
            or "Destino aproximado"
        )
        return {
            "destination": display_text(destination, "Destino aproximado"),
            "needsConfirmation": bool(props.get("needsConfirmation", props.get("approximate", True))),
        }
    if block_type == "StayPlanningCard":
        nights = props.get("nights")
        if nights is None:
            days = optional_float(props.get("days"))
            nights = max(1, int(days) - 1) if days is not None and days >= 1 else None
        if nights is None and props.get("durationText"):
            nights = nights_from_duration_text(str(props.get("durationText")))
        city = (
            props.get("city")
            or props.get("locationLabel")
            or props.get("destination")
            or props.get("location")
            or "Destino"
        )
        primary_stop = props.get("primaryStop") if isinstance(props.get("primaryStop"), dict) else {}
        recommendation = (
            props.get("recommendation")
            or props.get("plan")
            or primary_stop.get("name")
            or "Controlar carga cerca del alojamiento y confirmar antes de depender de ella."
        )
        return {
            "nights": nights,
            "city": display_text(city, "Destino"),
            "recommendation": display_text(recommendation, "Controlar carga cerca del alojamiento."),
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
    if block_type == "LocationDetailCard":
        precision = props.get("precision")
        if precision not in {"exact", "approximate"}:
            precision = "approximate"
        return {
            "label": display_text(
                props.get("label") or props.get("location") or props.get("destination") or props.get("name"),
                "Ubicación indicada",
            ),
            "lat": props.get("lat"),
            "lon": props.get("lon"),
            "precision": precision,
            "context": str(props.get("context") or "Ubicación usada para la búsqueda."),
            "needsConfirmation": bool(props.get("needsConfirmation", precision == "approximate")),
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
    if block_type == "StayPlanningCard":
        extra = []
        primary_stop = props.get("primaryStop") if isinstance(props.get("primaryStop"), dict) else None
        if primary_stop:
            extra.append(
                block(
                    f"stay-stop-{index}-{uuid4().hex[:8]}",
                    "RecommendedStopCard",
                    primary_stop,
                )
            )
        stops = props.get("stops") or props.get("alternatives")
        if isinstance(stops, list):
            extra.append(
                block(
                    f"stay-stops-{index}-{uuid4().hex[:8]}",
                    "AlternativeStopsList",
                    {"stops": stops},
                )
            )
        return extra
    return []


def normalize(value: str) -> str:
    substitutions = str.maketrans("áéíóúüñ", "aeiouun")
    return value.lower().translate(substitutions)


def first_number(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def nights_from_duration_text(value: str) -> int | None:
    normalized = normalize(value)
    number = first_number(normalized)
    if "semana" in normalized:
        return (number or 1) * 7
    if "finde" in normalized or "fin de semana" in normalized:
        return 2
    if "dia" in normalized and number is not None:
        return max(1, number - 1)
    return number
