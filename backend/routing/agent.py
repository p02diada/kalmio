from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import unquote
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
from routing.instrumentation import (
    agent_trace_turn,
    elapsed_ms,
    estimate_deepseek_cost,
    normalize_usage,
    record_trace_event,
    tool_result_summary,
    to_plain,
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


DecisionRequester = Callable[..., dict[str, Any]]


def initial_blocks() -> list[dict]:
    return [
        block(
            "assistant-initial",
            "AssistantMessage",
            {
                "text": (
                    "Cuéntame qué necesitas: una ruta completa, cargar cerca de donde estás, "
                    "o una parada de carga cerca de un hotel o destino. Si falta un dato crítico, te lo pediré."
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
                    "Parada cerca del hotel",
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
    if mode == "deepseek":
        blocks = validate_blocks(run_deepseek_agent(message, history_blocks=history_blocks))
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
                        "Para buscar una parada de carga cercana sin inventar resultados, "
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
            "¿Quieres calcular una ruta EV o buscar una parada de carga cerca de un destino concreto?",
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
    with agent_trace_turn("codex"):
        return run_provider_agent(
            message,
            history_blocks=history_blocks,
            request_decision=request_codex_decision,
            max_tool_calls=getattr(settings, "KALMIO_CODEX_MAX_TOOL_CALLS", 3),
        )


def run_deepseek_agent(message: str, history_blocks: list[dict] | None = None) -> list[dict]:
    with agent_trace_turn("deepseek"):
        return run_provider_agent(
            message,
            history_blocks=history_blocks,
            request_decision=request_deepseek_decision,
            max_tool_calls=getattr(settings, "KALMIO_DEEPSEEK_MAX_TOOL_CALLS", 3),
        )


def run_provider_agent(
    message: str,
    *,
    history_blocks: list[dict] | None,
    request_decision: DecisionRequester,
    max_tool_calls: int,
) -> list[dict]:
    history_blocks = history_blocks or []
    decision_message = contextualized_prompt(message, history_blocks)
    tool_history: list[dict[str, Any]] = []
    seen_calls: set[str] = set()

    for _ in range(max_tool_calls + 1):
        decision = request_decision(decision_message, tool_history=tool_history)
        if decision["type"] == "final":
            return validated_or_repaired_final_blocks(
                decision_message,
                decision["blocks"],
                tool_history,
                history_blocks=history_blocks,
                request_decision=request_decision,
            )

        call_signature = json.dumps(
            {"tool": decision["tool"], "args": decision["args"]},
            sort_keys=True,
            ensure_ascii=False,
        )
        if call_signature in seen_calls:
            return final_or_fallback_after_blocked_tool_call(
                decision_message,
                decision,
                tool_history,
                history_blocks=history_blocks,
                request_decision=request_decision,
                guardrail_name="repeated_tool_call",
                reason=f"El agente repitió la herramienta {decision['tool']} con los mismos argumentos.",
            )
        if len(tool_history) >= max_tool_calls:
            return final_or_fallback_after_blocked_tool_call(
                decision_message,
                decision,
                tool_history,
                history_blocks=history_blocks,
                request_decision=request_decision,
                guardrail_name="tool_budget_exhausted",
                reason=f"Se alcanzó el máximo de {max_tool_calls} llamadas a herramientas para este turno.",
            )
        seen_calls.add(call_signature)

        tool_started = time.perf_counter()
        try:
            result = execute_conversation_tool(ToolCall(name=decision["tool"], args=decision["args"]))
        except ConversationToolError as exc:
            result = {"ok": False, "tool": decision["tool"], "error": str(exc)}
        finally:
            tool_duration_ms = elapsed_ms(tool_started)
        record_trace_event(
            event="internal_tool_call",
            name=decision["tool"],
            status="ok" if result.get("ok") else "error",
            duration_ms=tool_duration_ms,
            metadata=tool_result_summary(result),
            request_payload=decision["args"],
            response_payload=result,
        )
        tool_history.append({"call": {"tool": decision["tool"], "args": decision["args"]}, "result": result})

        if not result.get("ok") and decision["tool"] not in ALLOWED_CONVERSATION_TOOLS:
            return fallback_from_tool_history(
                tool_history,
                str(result.get("error") or "La herramienta falló."),
                decision_message,
            )

    return fallback_from_tool_history(tool_history, "El agente no devolvió una respuesta final.", decision_message)


def final_or_fallback_after_blocked_tool_call(
    message: str,
    decision: dict[str, Any],
    tool_history: list[dict[str, Any]],
    *,
    history_blocks: list[dict],
    request_decision: DecisionRequester,
    guardrail_name: str,
    reason: str,
) -> list[dict]:
    record_trace_event(
        event="agent_guardrail",
        name=guardrail_name,
        status="warning",
        metadata={
            "reason": reason,
            "tool": decision.get("tool"),
            "toolHistoryCount": len(tool_history),
            "recovery": "final_only_retry",
        },
        request_payload=decision,
    )
    final_decision = request_decision(
        message,
        tool_history=tool_history,
        repair_issues=[
            reason,
            (
                "No pidas otra herramienta en esta respuesta. Devuelve type=final usando solo el historial "
                "de herramientas ya ejecutadas o explica claramente por qué esos datos no bastan."
            ),
        ],
        candidate_blocks=[],
    )
    if final_decision["type"] != "final":
        return fallback_from_tool_history(tool_history, reason, message)
    return validated_or_repaired_final_blocks(
        message,
        final_decision["blocks"],
        tool_history,
        history_blocks=history_blocks,
        request_decision=request_decision,
    )


def validated_or_repaired_final_blocks(
    message: str,
    candidate_blocks: list[dict],
    tool_history: list[dict[str, Any]],
    history_blocks: list[dict] | None = None,
    request_decision: DecisionRequester | None = None,
) -> list[dict]:
    request_decision = request_decision or request_codex_decision
    blocks = validate_blocks(candidate_blocks)
    issues = a2ui_contract_issues(blocks, tool_history, message, history_blocks=history_blocks)
    if not issues:
        return blocks

    repair_decision = request_decision(
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


def run_deepseek_decision(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    prompt = codex_prompt(
        message,
        tool_history=tool_history or [],
        repair_issues=repair_issues or [],
        candidate_blocks=candidate_blocks or [],
    )
    return call_deepseek_decision(prompt, allow_tools=not repair_issues)


def request_deepseek_decision(
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
    return run_deepseek_decision(message, **kwargs)


def call_deepseek_decision(prompt: str, *, allow_tools: bool = True) -> dict[str, Any]:
    message = call_deepseek_chat_completion(prompt, allow_tools=allow_tools)
    return parse_openai_compatible_decision(message)


def call_deepseek_chat_completion(prompt: str, *, allow_tools: bool) -> Any:
    api_key = getattr(settings, "KALMIO_DEEPSEEK_API_KEY", "")
    if not api_key:
        raise AgentResponseError("DeepSeek no está configurado: falta KALMIO_DEEPSEEK_API_KEY o DEEPSEEK_API_KEY.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AgentResponseError("El SDK openai no está instalado. Ejecuta pip install -r requirements.txt.") from exc

    client = OpenAI(
        api_key=api_key,
        base_url=getattr(settings, "KALMIO_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout=getattr(settings, "KALMIO_DEEPSEEK_TIMEOUT_SECONDS", 30),
    )
    model = getattr(settings, "KALMIO_DEEPSEEK_MODEL", "deepseek-v4-flash")
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Responde solo con JSON válido para respuestas finales. "
                    "Si usas herramientas, puedes emitir tool calls nativas o el objeto JSON type=tool_call indicado."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": getattr(settings, "KALMIO_DEEPSEEK_MAX_TOKENS", 1800),
        "stream": False,
        "extra_body": {
            "thinking": {
                "type": "enabled" if getattr(settings, "KALMIO_DEEPSEEK_THINKING", False) else "disabled"
            }
        },
    }
    if getattr(settings, "KALMIO_DEEPSEEK_THINKING", False):
        request["reasoning_effort"] = getattr(settings, "KALMIO_DEEPSEEK_REASONING_EFFORT", "high")
    else:
        request["temperature"] = getattr(settings, "KALMIO_DEEPSEEK_TEMPERATURE", 0)

    if allow_tools and getattr(settings, "KALMIO_DEEPSEEK_USE_NATIVE_TOOLS", True):
        request["tools"] = deepseek_tool_definitions()
        request["tool_choice"] = "auto"

    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**request)
    except Exception as exc:
        record_trace_event(
            event="llm_api_call",
            name="chat.completions.create",
            status="error",
            provider="deepseek",
            model=model,
            duration_ms=elapsed_ms(started),
            metadata=deepseek_request_metadata(request),
            request_payload=request,
            error=str(exc),
        )
        raise AgentResponseError(f"DeepSeek no pudo devolver una decisión: {exc}") from exc

    choices = getattr(response, "choices", None)
    if not choices:
        record_trace_event(
            event="llm_api_call",
            name="chat.completions.create",
            status="error",
            provider="deepseek",
            model=model,
            duration_ms=elapsed_ms(started),
            usage=normalize_usage(getattr(response, "usage", None)),
            metadata=deepseek_request_metadata(request),
            request_payload=request,
            response_payload=to_plain(response),
            error="Respuesta sin choices.",
        )
        raise AgentResponseError("DeepSeek no devolvió ninguna elección.")
    message = getattr(choices[0], "message", None)
    if message is None:
        record_trace_event(
            event="llm_api_call",
            name="chat.completions.create",
            status="error",
            provider="deepseek",
            model=model,
            duration_ms=elapsed_ms(started),
            usage=normalize_usage(getattr(response, "usage", None)),
            metadata=deepseek_request_metadata(request),
            request_payload=request,
            response_payload=to_plain(response),
            error="Respuesta sin message.",
        )
        raise AgentResponseError("DeepSeek no devolvió un mensaje de decisión.")
    usage = normalize_usage(getattr(response, "usage", None))
    record_trace_event(
        event="llm_api_call",
        name="chat.completions.create",
        status="ok",
        provider="deepseek",
        model=model,
        duration_ms=elapsed_ms(started),
        usage=usage,
        cost=estimate_deepseek_cost(usage),
        metadata={
            **deepseek_request_metadata(request),
            "finishReason": attr_or_key(choices[0], "finish_reason"),
            "toolCallCount": len(attr_or_key(message, "tool_calls") or []),
        },
        request_payload=request,
        response_payload=to_plain(message),
    )
    return message


def deepseek_request_metadata(request: dict[str, Any]) -> dict[str, Any]:
    messages = request.get("messages") if isinstance(request.get("messages"), list) else []
    prompt_chars = sum(len(str(message.get("content") or "")) for message in messages if isinstance(message, dict))
    tools = request.get("tools") if isinstance(request.get("tools"), list) else []
    extra_body = request.get("extra_body") if isinstance(request.get("extra_body"), dict) else {}
    thinking = extra_body.get("thinking") if isinstance(extra_body.get("thinking"), dict) else {}
    return {
        "messageCount": len(messages),
        "promptChars": prompt_chars,
        "maxTokens": request.get("max_tokens"),
        "nativeTools": bool(tools),
        "toolCount": len(tools),
        "thinking": thinking.get("type"),
        "responseFormat": request.get("response_format"),
    }


def deepseek_tool_definitions() -> list[dict[str, Any]]:
    location_schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "Etiqueta visible de la ubicación."},
            "lat": {"type": "number", "description": "Latitud validable, -90 a 90."},
            "lon": {"type": "number", "description": "Longitud validable, -180 a 180."},
        },
        "required": ["label", "lat", "lon"],
        "additionalProperties": False,
    }
    return [
        {
            "type": "function",
            "function": {
                "name": "resolve_location",
                "description": "Resuelve una ciudad, zona o POI conocido antes de buscar paradas de carga o calcular ruta.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Ciudad, zona, hotel o POI textual."}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_destination_chargers",
                "description": "Busca puntos de carga autorizados cerca de una ubicación ya resuelta o coordenadas explícitas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": location_schema,
                        "connector": {"type": "string", "description": "Conector si el usuario lo ha indicado."},
                        "radius_km": {"type": "number", "description": "Radio entre 1 y 100 km."},
                        "limit": {"type": "integer", "description": "Número de estaciones, entre 1 y 6."},
                    },
                    "required": ["location"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "plan_route",
                "description": "Calcula ruta EV con proveedor de rutas y puntos de carga autorizados cuando hay origen y destino.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": location_schema,
                        "destination": location_schema,
                        "vehicle": {
                            "type": "object",
                            "description": "Datos del vehículo solo si el usuario los ha dado explícitamente.",
                            "properties": {
                                "model": {"type": "string"},
                                "battery": {"type": "number"},
                                "usable_battery_kwh": {"type": "number"},
                                "consumption_kwh_per_100km": {"type": "number"},
                                "connector": {"type": "string"},
                                "max_charge_kw": {"type": "number"},
                            },
                            "additionalProperties": False,
                        },
                        "preferences": {
                            "type": "object",
                            "properties": {
                                "reserve_min_percent": {"type": "number"},
                                "prefer_fast": {"type": "boolean"},
                                "prefer_cheap": {"type": "boolean"},
                                "prefer_low_stress": {"type": "boolean"},
                                "prefer_services": {"type": "boolean"},
                                "prefer_large_hubs": {"type": "boolean"},
                                "avoid_single_connector": {"type": "boolean"},
                                "max_useful_power_kw": {"type": "number"},
                            },
                            "additionalProperties": False,
                        },
                        "corridor_radius_km": {"type": "number", "description": "Radio de corredor entre 1 y 100 km."},
                    },
                    "required": ["origin", "destination"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def parse_openai_compatible_decision(message: Any) -> dict[str, Any]:
    tool_calls = attr_or_key(message, "tool_calls") or []
    if tool_calls:
        tool_call = tool_calls[0]
        function = attr_or_key(tool_call, "function") or {}
        tool = str(attr_or_key(function, "name") or "").strip()
        args = parse_tool_arguments(attr_or_key(function, "arguments"))
        if not tool:
            raise AgentResponseError("DeepSeek pidió una herramienta sin nombre.")
        return {"type": "tool_call", "tool": tool, "args": args}

    content = chat_content_text(attr_or_key(message, "content"))
    payload = try_decode_json_candidate(content)
    if not isinstance(payload, dict):
        raise AgentResponseError("DeepSeek no devolvió un objeto JSON válido.")
    return parse_codex_decision(payload)


def parse_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or str(value).strip() == "":
        return {}
    payload = try_decode_json_candidate(str(value))
    if isinstance(payload, dict):
        return payload
    raise AgentResponseError("DeepSeek pidió una herramienta con argumentos JSON inválidos.")


def chat_content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            text = attr_or_key(item, "text") or attr_or_key(item, "content")
            if text:
                parts.append(str(text))
        return "\n".join(parts).strip()
    return "" if value is None else str(value).strip()


def attr_or_key(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def codex_prompt(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> str:
    tool_history = tool_history or []
    repair_issues = repair_issues or []
    candidate_blocks = candidate_blocks or []
    known_locations = "; ".join(
        f"{label}({lat:.4f},{lon:.4f})" for label, lat, lon in KNOWN_LOCATIONS.values()
    )
    tool_instructions = (
        "Herramientas permitidas. Puedes llamar solo una por respuesta tool_call:\n"
        '- resolve_location: resuelve una ciudad o texto conocido. Args: {"query":"ciudad o texto"}\n'
        "- search_destination_chargers: busca puntos de carga autorizados alrededor de una ubicación ya resuelta o "
        'coordenadas dadas por el usuario. Args: {"location":{"label":"...","lat":0,"lon":0},"connector":null,'
        '"radius_km":80,"limit":3}\n'
        "- plan_route: calcula ruta y paradas con proveedor y datos autorizados. Args: "
        '{"origin":{"label":"...","lat":0,"lon":0},"destination":{"label":"...","lat":0,"lon":0},'
        '"vehicle":null,"preferences":{"reserve_min_percent":20,"max_useful_power_kw":null},"corridor_radius_km":25}\n'
        "Nunca llames herramientas con label vacío, lat/lon 0,0, placeholders o ubicaciones no dadas/resueltas; pregunta antes.\n"
        "Ubicaciones internas conocidas para argumentos de herramienta, sin inventar otras coordenadas: "
        f"{known_locations}.\n"
    )
    behavior_instructions = (
        "Comportamiento EV esperado:\n"
        "- Usa el historial útil, acepta correcciones naturales y no suenes como formulario.\n"
        "- Presenta las recomendaciones como paradas o lugares útiles para el viaje; usa name/stationName como punto de carga trazable y placeName solo si sale de herramienta o del usuario. No inventes lugares, servicios ni POIs.\n"
        "- Carga urgente sin ubicación: pide solo ubicación actual, ciudad/zona o coordenadas. No pidas destino para una carga urgente.\n"
        "- Tras una urgencia, una ciudad/zona/coordenadas es continuación de la urgencia; usa herramientas si hay ubicación suficiente.\n"
        "- Si el usuario corrige la ubicación, descarta la anterior, conserva batería, conector y preferencias si siguen teniendo sentido y busca con la nueva.\n"
        "- Si pregunta por un fallo anterior, no contradigas bloques ya validados; explica validación, cobertura, aproximación o datos autorizados.\n"
        "- Calle/POI/zona: intenta resolver la parte conocida con resolve_location. Si no puedes ubicar esa calle exacta, dilo y ofrece ciudad aproximada o coordenadas; no inventes coordenadas.\n"
        "- Ruta sin consumo/modelo: puedes usar plan_route para explorar paradas de carga, pero no inventes autonomía, energía ni llegada. Si plan_route devuelve planningLevel=chargers_only, dilo.\n"
        "- Hotel/destino/estancia: si hay ciudad/POI suficiente y el usuario necesita cargar durante la estancia, llama search_destination_chargers directamente; no devuelvas solo un botón para buscar. Una ciudad conocida ya es ubicación suficiente para una búsqueda aproximada; no esperes hotel/zona exacta para la primera búsqueda, puedes pedir refinamiento después de mostrar resultados trazados. No lo conviertas en ruta salvo que pidan origen-destino.\n"
        "- Si el usuario menciona ida y vuelta, volver, regreso o fechas de salida/vuelta, reconoce contexto de viaje redondo. Si falta origen para planificar ida/vuelta, pregunta por el origen antes de pedir hotel/zona.\n"
        "- Si resolve_location recibe un hotel, calle o POI pero solo devuelve una ciudad/zona, no afirmes que conoces el lugar exacto; di que usas esa ciudad/zona como aproximación o pide coordenadas/dirección exacta.\n"
        "- Si search_destination_chargers devuelve stops, usa nombres y métricas exactas trazables; no uses placeholders cuando hay estaciones. Puedes llamar a esos resultados paradas, pero el punto de carga mostrado debe seguir siendo trazable.\n"
        "- Si ya hay stops con potencia/distancia/disponibilidad y el usuario pide comparar potencia o alternativas, responde con esos resultados; no repitas la misma búsqueda sin cambiar ubicación, radio, conector o criterio material.\n"
        "- Si una herramienta permitida falla, explica el fallo en contexto y pide una acción mínima; no fabriques datos.\n"
        "- Batería baja: pocas opciones, riesgo explícito, y CTA de navegación solo con lat/lon trazables. Si conoces batería, consérvala.\n"
        "- Punto de carga ocupado: no lo repitas como plan B; usa alternativas trazables o vuelve a buscar con la ubicación previa.\n"
        "- En carretera y poco desvío: pide carretera/destino u origen-destino si faltan; no lo reduzcas a búsqueda urbana arbitraria.\n"
        "- Si el coche carga máximo a X kW, pasa X como preferences.max_useful_power_kw; si recomiendas un cargador de más potencia, di que el coche no aprovechará más de 100 kW cuando X=100 y no presentes la potencia superior como ventaja.\n"
        "- Restricción dura de llegada: sin perfil de vehículo no la presentes como cumplida; pide modelo/consumo/autonomía.\n"
        "- Viajes futuros: disponibilidad, tarifas y acceso pueden cambiar. Niños/comodidad: menciona servicios solo como comodidad potencial si la herramienta los trae; no uses claims absolutos como ideal, perfecto, seguro o apto para niños salvo que el dato venga explícitamente trazado.\n"
        "- Estancias de varios días: piensa en carga durante estancia y vuelta; si hay viaje redondo y falta origen, pídelo; si solo pide carga en destino y hay ubicación suficiente, busca en destino. Tras una búsqueda para estancia de varios días, incluye StayPlanningCard para el contexto de estancia junto a los puntos de carga trazados.\n"
        "- Rutas baratas, reservas duras, carga justa o comparativas rápida/barata necesitan origen, destino y datos de vehículo/batería para calcular; si faltan, pregunta por esos datos y no inventes tarifas, kWh ni llegada.\n"
        "Ejemplos críticos por analogía, no reglas rígidas: 'Necesito cargar ya' -> pide ubicación, no destino; 'En Córdoba' tras urgencia -> busca Córdoba; "
        "'Paseo de la Victoria de Córdoba' -> si solo resuelves Córdoba, explica la aproximación; "
        "'Voy a dormir en Valencia, busca cargadores cerca del hotel' -> llama search_destination_chargers con Valencia como aproximación y explica que el hotel exacto refina; "
        "'Valencia centro' tras hotel -> DestinationChargingCard + AlternativeStopsList o RecommendedStopCard; "
        "'Voy a Granada y duermo cerca de la Alhambra' -> llama search_destination_chargers con Alhambra/Granada aproximado; "
        "'Me voy 3 días a Córdoba y me quedo en el hotel Meliá' -> llama search_destination_chargers con Córdoba como aproximación, no ActionButtons; "
        "'Voy una semana a Cádiz y necesito cargar durante la estancia' -> llama search_destination_chargers con Cádiz como aproximación e incluye StayPlanningCard, no preguntes primero por hotel/zona; "
        "'Quiero la ruta más barata, pero sin bajar del 20%' sin origen/destino -> no llames plan_route, pregunta origen, destino y datos de vehículo/batería; "
        "'Voy a Córdoba el viernes y vuelvo el domingo' -> pregunta por origen para planificar ida/vuelta antes de buscar solo alojamiento; "
        "'Zaragoza a Barcelona con 25%' sin consumo/modelo -> no valides ese 25%; "
        "'Mi coche carga máximo a 100 kW, no necesito ultrarrápidos' -> usa preferences.max_useful_power_kw=100.\n"
    )
    catalog_instructions = (
        "Catálogo A2UI permitido por propósito, no por reglas rígidas de intención:\n"
        "AssistantMessage texto breve; TripSummaryCard ruta clara; RouteSummaryCard solo plan_route; "
        "RecommendedStopCard/AlternativeStopsList solo paradas de carga respaldadas por estaciones de herramientas; en esos bloques name/stationName debe ser la estación trazable y placeName solo un lugar confirmado; RiskExplanationCard incertidumbre concreta; "
        "CostComparisonCard solo costes de herramienta; UrgentChargeCard carga inmediata trazable; "
        "DestinationChargingCard hotel/destino/ciudad; StayPlanningCard estancia; MapPreviewCard sin inventar geometría; "
        "ActionButtons usa event para backend/agente, functionCall.openUrl para abrir mapas, o disabled con reason; "
        "ClarifyingQuestionCard faltan datos críticos; "
        "LocationRequestCard pide ubicación; LocationDetailCard coordenadas de usuario/herramienta; PreferenceChips preferencias; ErrorFallbackCard reservado.\n"
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
        "Para ActionButtons usa actions con event {name, context} o functionCall {call:'openUrl', args:{url:'https://...'}}; "
        "no uses handlers arbitrarios. "
        "No inventes disponibilidad, precios, estaciones, coordenadas ni estado del vehículo. "
        "No uses ActionButtons para sustituir una herramienta de búsqueda cuando ya tienes ciudad/POI suficiente. "
        "No llames plan_route con coordenadas vacías o 0,0; si faltan origen/destino reales, usa ClarifyingQuestionCard o AssistantMessage. "
        "No afirmes paradas/puntos de carga disponibles/encontrados ni incluyas listas vacías como resultado si no llamaste una herramienta de búsqueda/ruta. "
        "No afirmes paradas, puntos de carga o rutas si no vienen de herramientas, datos autorizados o texto explícito del usuario. "
        "Si faltan datos críticos, pregunta. Si el proveedor o los datos autorizados no permiten responder, falla de forma explícita. "
        "Puedes pedir otra herramienta si falta un dato necesario, pero no repitas una llamada ya hecha con los mismos argumentos. "
        "Elige los bloques A2UI que aporten claridad al usuario según la conversación completa. "
        "Cuando tengas resultados de herramientas con estaciones, rutas o métricas, prefiere bloques estructurados para esos hechos verificables "
        "y usa AssistantMessage solo como introducción breve, cierre o aclaración de límites. "
        "Una respuesta simple también es válida si evita sobreafirmar o si no hay datos estructurados suficientes."
    )
    if repair_issues:
        return (
            "Eres el agente conversacional de Kalmio para planificación EV. Tu respuesta anterior fue rechazada "
            "por el contrato de seguridad/datos A2UI o por un guardrail de herramientas. No pidas herramientas en esta reparación. "
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
    started = time.perf_counter()
    codex_model = getattr(settings, "KALMIO_CODEX_MODEL", "gpt-5.4-mini")
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
                    codex_model,
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
            stdout_output = result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        record_trace_event(
            event="llm_api_call",
            name="codex.exec",
            status="error",
            provider="codex",
            model=codex_model,
            duration_ms=elapsed_ms(started),
            metadata={"promptChars": len(prompt)},
            request_payload={"prompt": prompt},
            error=str(exc),
        )
        raise AgentResponseError(f"Codex local no disponible: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "sin detalle"
        record_trace_event(
            event="llm_api_call",
            name="codex.exec",
            status="error",
            provider="codex",
            model=codex_model,
            duration_ms=elapsed_ms(started),
            metadata={"promptChars": len(prompt), "returnCode": result.returncode},
            request_payload={"prompt": prompt},
            response_payload={"stdout": stdout_output, "stderr": result.stderr.strip()},
            error=detail,
        )
        raise AgentResponseError(f"Codex local falló: {detail}")

    payload = decode_codex_json(raw_output, stdout_output)
    if not isinstance(payload, dict):
        record_trace_event(
            event="llm_api_call",
            name="codex.exec",
            status="error",
            provider="codex",
            model=codex_model,
            duration_ms=elapsed_ms(started),
            metadata={"promptChars": len(prompt), "returnCode": result.returncode},
            request_payload={"prompt": prompt},
            response_payload={"rawOutput": raw_output, "stdout": stdout_output},
            error="Codex local no devolvió un objeto JSON.",
        )
        raise AgentResponseError("Codex local no devolvió un objeto JSON.")
    record_trace_event(
        event="llm_api_call",
        name="codex.exec",
        status="ok",
        provider="codex",
        model=codex_model,
        duration_ms=elapsed_ms(started),
        metadata={"promptChars": len(prompt), "returnCode": result.returncode},
        request_payload={"prompt": prompt},
        response_payload=payload,
    )
    return payload


def decode_codex_json(raw_output: str, stdout_output: str = "") -> Any:
    for candidate in (raw_output, stdout_output):
        payload = try_decode_json_candidate(candidate)
        if payload is not None:
            return payload
    raise AgentResponseError("Codex local no devolvió JSON válido.")


def try_decode_json_candidate(candidate: str) -> Any | None:
    text = candidate.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = strip_json_fence(text)
    if fenced != text:
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            pass

    extracted = first_json_object(text)
    if extracted is None:
        return None
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        return None


def strip_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) < 3:
        return text
    if not lines[-1].strip().startswith("```"):
        return text
    return "\n".join(lines[1:-1]).strip()


def first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


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
                    context="Ubicación usada para buscar una parada de carga urgente",
                    needs_confirmation=True,
                ),
                block(
                    f"urgent-{uuid4().hex[:10]}",
                    "UrgentChargeCard",
                    {
                        "battery": intent.vehicle_fields.get("battery"),
                        "nearest": str(nearest.get("name") or "Punto de carga cercano por confirmar"),
                        "stationName": str(nearest.get("stationName") or nearest.get("name") or ""),
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
                            "Muestro paradas con puntos de carga autorizados cerca de la ubicación indicada. "
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
                    context="Destino usado para buscar paradas de carga",
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
                {"level": "medio", "text": "Muestro solo paradas respaldadas por puntos de carga autorizados devueltos por la herramienta interna."},
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
                    "name": str(recommendation.get("name") or "Punto de carga recomendado"),
                    "stationName": str(recommendation.get("stationName") or recommendation.get("name") or ""),
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
        return "No puedo hacer esa acción desde el chat. Puedo ayudarte a calcular una ruta, buscar paradas con puntos de carga autorizados o pedir los datos que falten."
    if "proveedor" in normalized or "ruta" in normalized:
        return "No he podido validar la ruta ahora mismo. Reinténtalo con origen y destino concretos, o busca primero una parada de carga cerca de una ciudad."
    if "datos" in normalized or "cargadores" in normalized:
        return "No he podido validar suficientes puntos de carga con datos autorizados. Puedo intentarlo con otra ubicación o un radio más amplio."
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
        elif block_type == "AssistantMessage":
            issues.extend(assistant_message_contract_issues(props, facts))
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
            issues.extend(action_buttons_contract_issues(props, facts, explicit_coordinates))
        elif block_type == "CostComparisonCard":
            issues.extend(cost_contract_issues(props))
        elif block_type == "RiskExplanationCard":
            issues.extend(risk_explanation_contract_issues(props))

    issues.extend(factual_charger_copy_contract_issues(blocks, facts))
    issues.extend(approximate_location_contract_issues(blocks, facts))
    return dedupe_preserve_order(issues)


def tool_fact_index(tool_history: list[dict[str, Any]], history_blocks: list[dict] | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "stations": {},
        "locations": [],
        "approximateLocations": [],
        "routes": [],
        "vehicle": {},
        "stationSearches": 0,
    }
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
        tool_name = result.get("tool") or call.get("tool")
        if tool_name == "resolve_location":
            add_approximate_location_fact(facts, args.get("query"), result.get("location"))
        if tool_name in {"search_destination_chargers", "plan_route"}:
            facts["stationSearches"] += 1
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
        if tool_name == "plan_route":
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
    normalized_values = station_value_aliases(value)
    for field in ("powerKw", "distanceKm", "detourMin", "confidence", "lat", "lon", "availableEvses", "connectorTypes"):
        if field in normalized_values:
            current[field] = normalized_values.get(field)


def station_value_aliases(value: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    aliases = {
        "powerKw": ("powerKw", "power_kw"),
        "distanceKm": ("distanceKm", "distance_km"),
        "detourMin": ("detourMin", "detour_min"),
        "confidence": ("confidence",),
        "lat": ("lat",),
        "lon": ("lon",),
        "availableEvses": ("availableEvses", "available_evses", "availableConnectors", "available_connectors"),
        "connectorTypes": ("connectorTypes", "connector_types"),
    }
    for canonical, keys in aliases.items():
        for key in keys:
            if key in value:
                normalized[canonical] = value.get(key)
                break

    location = value.get("location")
    if isinstance(location, dict):
        normalized.setdefault("lat", location.get("lat"))
        normalized.setdefault("lon", location.get("lon"))

    connectors = value.get("connectors")
    if isinstance(connectors, list):
        connector_types = []
        available_count = 0
        max_power_kw = optional_float(normalized.get("powerKw")) or 0
        for connector in connectors:
            if not isinstance(connector, dict):
                continue
            connector_type = display_text(connector.get("type"), "")
            if connector_type:
                connector_types.append(connector_type)
            count = int(optional_float(connector.get("count")) or 0)
            if connector.get("available") is True:
                available_count += count or 1
            max_power_kw = max(max_power_kw, optional_float(connector.get("power_kw")) or 0)
        if connector_types:
            normalized.setdefault("connectorTypes", connector_types)
        if available_count:
            normalized.setdefault("availableEvses", available_count)
        if max_power_kw:
            normalized.setdefault("powerKw", max_power_kw)
    return normalized


def add_location_fact(facts: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    lat = optional_float(value.get("lat"))
    lon = optional_float(value.get("lon"))
    if lat is None or lon is None:
        return
    facts["locations"].append({"label": display_text(value.get("label"), "Ubicación indicada"), "lat": lat, "lon": lon})


def add_approximate_location_fact(facts: dict[str, Any], query: Any, location: Any) -> None:
    if not isinstance(location, dict):
        return
    query_text = display_text(query, "")
    label = display_text(location.get("label"), "")
    if not query_text or not label:
        return
    normalized_query = normalize(query_text)
    normalized_label = normalize(label)
    if normalized_query == normalized_label or normalized_label not in normalized_query:
        return
    if location.get("precision") in {"city_approximation", "known_location_approximation"}:
        facts["approximateLocations"].append({"query": query_text, "resolvedLabel": label})
        return
    if not any(term in normalized_query for term in ("hotel", "calle", "paseo", "avenida", "plaza", "melia", "alhambra", "atocha")):
        return
    facts["approximateLocations"].append({"query": query_text, "resolvedLabel": label})


def approximate_location_contract_issues(blocks: list[dict], facts: dict[str, Any]) -> list[str]:
    if not facts.get("approximateLocations"):
        return []
    if not any(block_uses_factual_location(block) for block in blocks):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if has_approximation_disclaimer(visible_text):
        return []
    location = facts["approximateLocations"][-1]
    return [
        "La respuesta usa una ubicación resuelta solo como aproximación "
        f"('{location['query']}' -> '{location['resolvedLabel']}') y debe decirlo de forma visible."
    ]


def block_uses_factual_location(block: dict) -> bool:
    return block.get("type") in {
        "AlternativeStopsList",
        "DestinationChargingCard",
        "LocationDetailCard",
        "MapPreviewCard",
        "RecommendedStopCard",
        "RouteSummaryCard",
        "StayPlanningCard",
        "UrgentChargeCard",
    }


def block_visible_text(block: dict) -> str:
    props = block.get("props") if isinstance(block.get("props"), dict) else {}
    return visible_text_from_value(props)


def visible_text_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for key, nested in value.items():
            if key in {"text", "question", "title", "description", "summary", "risk", "context", "warning", "warnings"}:
                parts.append(visible_text_from_value(nested))
            elif isinstance(nested, (dict, list)):
                parts.append(visible_text_from_value(nested))
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        return " ".join(visible_text_from_value(item) for item in value)
    return ""


def assistant_message_contract_issues(props: dict, facts: dict[str, Any]) -> list[str]:
    text = display_text(props.get("text"), "")
    if not text:
        return []
    normalized_text = normalize(text)
    if has_approximation_disclaimer(normalized_text):
        return []

    issues = []
    for location in facts.get("approximateLocations", []):
        query = display_text(location.get("query"), "")
        resolved_label = display_text(location.get("resolvedLabel"), "")
        if query and normalize(query) in normalized_text:
            issues.append(
                "AssistantMessage.text sugiere ubicación exacta para "
                f"'{query}', pero la herramienta solo resolvió '{resolved_label}'. "
                "Debe decir que usa la ciudad/zona como aproximación o pedir coordenadas/dirección exacta."
            )
    return issues


def has_approximation_disclaimer(normalized_text: str) -> bool:
    return any(
        term in normalized_text
        for term in (
            "aproximacion",
            "aproximado",
            "aproximada",
            "como referencia",
            "no puedo ubicar",
            "no he podido ubicar",
            "no tengo la ubicacion exacta",
            "sin ubicacion exacta",
        )
    )


def alternative_stops_contract_issues(props: dict, facts: dict[str, Any]) -> list[str]:
    stops = props.get("stops")
    if not isinstance(stops, list):
        return ["AlternativeStopsList.props.stops debe ser una lista."]
    if not stops and not facts.get("stationSearches"):
        return ["AlternativeStopsList.stops está vacío sin una búsqueda o ruta de herramienta trazable."]
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


def factual_charger_copy_contract_issues(blocks: list[dict], facts: dict[str, Any]) -> list[str]:
    if facts.get("stations") or facts.get("stationSearches"):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text or negates_found_chargers(visible_text):
        return []
    if claims_chargers_found(visible_text):
        return [
            "La respuesta afirma paradas o puntos de carga disponibles/encontrados sin resultado de herramienta trazable. "
            "Debe llamar search_destination_chargers/plan_route o formularlo como una búsqueda pendiente."
        ]
    return []


def claims_chargers_found(normalized_text: str) -> bool:
    return any(
        term in normalized_text
        for term in (
            "he encontrado",
            "encontre",
            "te muestro cargadores",
            "te muestro paradas",
            "cargadores disponibles",
            "paradas disponibles",
            "paradas con carga",
            "cargadores autorizados devueltos",
            "estos son los cargadores",
            "estas son las paradas",
            "estos cargadores",
            "estas paradas",
        )
    )


def negates_found_chargers(normalized_text: str) -> bool:
    return any(
        term in normalized_text
        for term in (
            "no he encontrado",
            "no encontre",
            "sin resultados",
            "no hay cargadores",
            "no hay paradas",
            "no puedo listar",
            "necesito validar",
            "puedo buscar",
        )
    )


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
    rendered_values = station_value_aliases(props)
    for field in ("powerKw", "distanceKm", "detourMin", "lat", "lon", "availableEvses"):
        if field not in rendered_values:
            continue
        rendered = rendered_values.get(field)
        expected = source.get(field)
        if rendered is None:
            continue
        if expected is None:
            issues.append(f"{label}.{field} no está en el resultado de herramienta para {name}.")
        elif field in {"lat", "lon"} and not coordinate_value_matches(rendered, expected):
            issues.append(f"{label}.{field} no coincide con el dato de herramienta para {name}.")
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


def action_buttons_contract_issues(
    props: dict,
    facts: dict[str, Any] | None = None,
    explicit_coordinates: list[tuple[float, float]] | None = None,
) -> list[str]:
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
        label = normalize(str(action.get("label") or ""))
        if any(term in label for term in ("reserv", "pagar", "pago", "booking", "payment", "comprar")):
            issues.append(f"ActionButtons.actions[{index}] pide una acción no soportada por Kalmio.")
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
                            coordinates_from_text(unquote(url)),
                            facts,
                            explicit_coordinates,
                        )
                    )

        if isinstance(event, dict):
            context = event.get("context") if isinstance(event.get("context"), dict) else {}
            lat = optional_float(context.get("lat"))
            lon = optional_float(context.get("lon"))
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
    issues: list[str] = []
    if not coordinates:
        return issues
    station = station_referenced_by_action_label(action_label, facts)
    for lat, lon in coordinates:
        if station is not None:
            if not close_station_coordinates(lat, lon, station.get("lat"), station.get("lon")):
                issues.append(f"{label} usa coordenadas que no coinciden con la estación trazable '{station['name']}'.")
            continue
        if not coordinate_traced_by_any_fact(lat, lon, facts, explicit_coordinates):
            issues.append(f"{label} usa coordenadas que no vienen del usuario, estación, origen, destino ni herramienta.")
    return issues


def station_referenced_by_action_label(action_label: str, facts: dict[str, Any]) -> dict[str, Any] | None:
    normalized_label = normalize(action_label)
    for station in facts.get("stations", {}).values():
        station_name = display_text(station.get("name"), "")
        normalized_station = station_key(station_name)
        if normalized_station and normalized_station in normalized_label:
            return station
    return None


def coordinate_traced_by_any_fact(
    lat: float,
    lon: float,
    facts: dict[str, Any],
    explicit_coordinates: list[tuple[float, float]],
) -> bool:
    if coordinate_traced(lat, lon, facts.get("locations", []), explicit_coordinates):
        return True
    for station in facts.get("stations", {}).values():
        if close_coordinates(lat, lon, station.get("lat"), station.get("lon")):
            return True
    return False


def close_station_coordinates(lat: float, lon: float, expected_lat: Any, expected_lon: Any) -> bool:
    other_lat = optional_float(expected_lat)
    other_lon = optional_float(expected_lon)
    if other_lat is None or other_lon is None:
        return False
    return abs(lat - other_lat) <= 0.0005 and abs(lon - other_lon) <= 0.0005


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


def coordinate_value_matches(rendered: Any, expected: Any) -> bool:
    rendered_number = optional_float(rendered)
    expected_number = optional_float(expected)
    if rendered_number is None or expected_number is None:
        return str(rendered).strip() == str(expected).strip()
    return abs(rendered_number - expected_number) <= 0.0005


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
    location_hints = known_location_hints(current_message)
    if not transcript:
        return "\n".join([*location_hints, current_message]) if location_hints else current_message
    state_line = f"{state_summary}\n" if state_summary else ""
    hints_line = "\n".join(location_hints)
    if hints_line:
        hints_line += "\n"
    return (
        "Conversación disponible de Kalmio. Usa el historial para resolver referencias y datos parciales; "
        "si el usuario cambia claramente de objetivo, sigue el mensaje actual.\n"
        f"{state_line}"
        f"{hints_line}"
        f"{transcript}\n"
        f"Mensaje actual del usuario: {current_message}"
    )


def known_location_hints(message: str) -> list[str]:
    normalized = normalize(message)
    hints = []
    seen: set[str] = set()
    for key, (label, lat, lon) in KNOWN_LOCATIONS.items():
        if key not in normalized or label in seen:
            continue
        seen.add(label)
        hints.append(
            "Pista de ubicación conocida detectada en el mensaje actual, no una decisión de intención: "
            f"{label} ({lat:.4f}, {lon:.4f})."
        )
    return hints


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
            f"parada/punto de carga cercano {props.get('placeName') or props.get('nearest')}, distancia {props.get('distanceKm')} km, "
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
        stop_names = [
            str(stop.get("placeName") or stop.get("name"))
            for stop in stops
            if isinstance(stop, dict) and (stop.get("placeName") or stop.get("name"))
        ]
        if stop_names:
            return "Paradas mostradas: " + ", ".join(stop_names[:5])
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
                        f"No hay paradas con puntos de carga autorizados importados cerca de {location.label}. "
                        "No voy a inventar estaciones; comparte otra ubicación o coordenadas más precisas."
                    ),
                },
            ),
            location_request_block(
                reason="urgent_charge",
                title="Prueba con otra ubicación cercana",
                body=(
                    "No encuentro paradas con puntos de carga autorizados alrededor de esa ubicación. "
                    "Comparte una ubicación más precisa o una ciudad cercana y volveré a comprobarlo."
                ),
            ),
        ]

    nearest = stations[0]
    top = stations[:3]
    return [
        location_detail_block(
            location,
            context="Ubicación usada para buscar una parada de carga urgente",
            needs_confirmation=True,
        ),
        block(
            f"urgent-{uuid4().hex[:10]}",
            "UrgentChargeCard",
            {
                "battery": intent.vehicle_fields.get("battery"),
                "nearest": nearest.station.name,
                "stationName": nearest.station.name,
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
                        "stationName": item.station.name,
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
                    "Muestro paradas con puntos de carga autorizados cerca de la ubicación indicada. "
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
                "Puedo buscar una parada de carga cerca de un hotel o destino, pero necesito una ciudad conocida o coordenadas.",
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
                    context="Destino usado para buscar paradas de carga",
                    needs_confirmation=True,
                ),
            block(
                f"risk-{uuid4().hex[:10]}",
                "RiskExplanationCard",
                {
                    "level": "alto",
                    "text": "No hay paradas con puntos de carga autorizados cerca de ese destino. No voy a inventar estaciones.",
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
            context="Destino usado para buscar paradas de carga",
            needs_confirmation=True,
        ),
        block(
            f"stops-{uuid4().hex[:10]}",
            "AlternativeStopsList",
            {
                "stops": [
                    {
                        "name": item.station.name,
                        "stationName": item.station.name,
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
                "text": "Muestro paradas con puntos de carga autorizados cerca del destino. Confirma acceso final, tarifa y disponibilidad antes de depender de ellos.",
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
                    else "He decidido explorar paradas de carga en ruta. Sin datos completos del coche no calculo autonomía."
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
                "stationName": station["name"],
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
                            "stationName": alternative.station["name"],
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
                            "label": "Abrir parada en Maps",
                            "functionCall": {
                                "call": "openUrl",
                                "args": {
                                    "url": f"https://www.google.com/maps/search/?api=1&query={station['lat']},{station['lon']}",
                                },
                            },
                        },
                        {
                            "label": "Guardar plan",
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
        place_name = (
            props.get("placeName")
            or props.get("locationName")
            or props.get("stopName")
            or recommended_stop.get("placeName")
            or recommended_stop.get("locationName")
        )
        nearest = (
            props.get("nearest")
            or props.get("stationName")
            or props.get("name")
            or props.get("chargerName")
            or recommended_stop.get("stationName")
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
        normalized = {
            "battery": battery,
            "nearest": display_text(nearest, "Punto de carga cercano por confirmar"),
            "stationName": display_text(nearest, ""),
            "distanceKm": distance_km,
        }
        if place_name:
            normalized["placeName"] = display_text(place_name, "")
        else:
            normalized.pop("placeName", None)
        return normalized
    if block_type == "RecommendedStopCard":
        recommended_stop = props.get("recommendedStop") if isinstance(props.get("recommendedStop"), dict) else {}
        place_name = (
            props.get("placeName")
            or props.get("locationName")
            or props.get("stopName")
            or recommended_stop.get("placeName")
            or recommended_stop.get("locationName")
        )
        name = (
            props.get("stationName")
            or props.get("name")
            or recommended_stop.get("stationName")
            or recommended_stop.get("name")
            or props.get("station")
            or props.get("charger")
        )
        power_kw = props.get("powerKw")
        if power_kw is None:
            power_kw = recommended_stop.get("powerKw")
        distance_km = props.get("distanceKm")
        if distance_km is None:
            distance_km = recommended_stop.get("distanceKm")
        detour_min = props.get("detourMin")
        if detour_min is None:
            detour_min = recommended_stop.get("detourMin")
        normalized = {
            **props,
            "name": display_text(name, "Punto de carga recomendado"),
            "stationName": display_text(name, ""),
            "powerKw": power_kw,
            "distanceKm": distance_km,
            "detourMin": detour_min,
            "confidence": str(props.get("confidence") or recommended_stop.get("confidence") or "media"),
        }
        if place_name:
            normalized["placeName"] = display_text(place_name, "")
        else:
            normalized.pop("placeName", None)
        return normalized
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
        if nights is None and (props.get("durationText") or props.get("duration")):
            nights = nights_from_duration_text(str(props.get("durationText") or props.get("duration")))
        city = (
            props.get("city")
            or props.get("locationLabel")
            or props.get("destination")
            or props.get("location")
            or "Destino"
        )
        chargers = props.get("chargers") if isinstance(props.get("chargers"), list) else []
        primary_stop = props.get("primaryStop") if isinstance(props.get("primaryStop"), dict) else {}
        if not primary_stop and chargers and isinstance(chargers[0], dict):
            primary_stop = chargers[0]
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
        stops = props.get("stops") or props.get("alternatives") or props.get("chargers")
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
