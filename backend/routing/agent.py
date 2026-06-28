from __future__ import annotations

import json
import re
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
    route_geometry_payload,
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
    "RouteCorridorCard",
    "StationPreviewCard",
    "StationDetailCard",
    "StationList",
    "ActionButtons",
    "PositionRequestCard",
    "PreferenceChips",
    "ErrorFallbackCard",
}

STATION_CARD_TYPES = {"StationPreviewCard", "StationDetailCard"}


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
ProgressCallback = Callable[[dict[str, Any]], None]


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
    ]


def run_conversation_agent(
    message: str,
    history_blocks: list[dict] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    mode = getattr(settings, "KALMIO_CONVERSATION_AGENT_MODE", "local")
    if mode == "deepseek":
        blocks = validate_blocks(
            run_deepseek_agent(message, history_blocks=history_blocks, progress_callback=progress_callback)
        )
        if not any(item.get("type") == "UserMessage" for item in blocks):
            blocks.insert(0, block(f"user-{uuid4().hex[:10]}", "UserMessage", {"text": message.strip()}))
        return blocks
    if mode == "pydantic_ai":
        blocks = validate_blocks(
            run_pydantic_ai_agent(message, history_blocks=history_blocks, progress_callback=progress_callback)
        )
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
                position_request_block(
                    reason="urgent_charge",
                    title="Necesito tu ubicación",
                    body=(
                        "Para buscar una parada de carga cercana sin inventar resultados, "
                        "comparte tu ubicación o escribe una ciudad, carretera o punto cercano."
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
                missing_data_message_block(
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
                    f"assistant-{uuid4().hex[:10]}",
                    "AssistantMessage",
                    {"text": f"No puedo calcular la ruta ahora: {exc}"},
                )
            )
        except PlanningDataError as exc:
            blocks.append(
                block(
                    f"assistant-{uuid4().hex[:10]}",
                    "AssistantMessage",
                    {"text": str(exc)},
                )
            )
        return blocks

    blocks.append(
        missing_data_message_block(
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
                    "No he podido completar esta respuesta con fiabilidad. No voy a asumir estaciones, coordenadas, "
                    "precios ni estado del vehículo. Para continuar, envíame origen o ubicación, destino si hay ruta, "
                    "batería actual y conector."
                )
            },
        ),
    ]


def run_deepseek_agent(
    message: str,
    history_blocks: list[dict] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    with agent_trace_turn("deepseek"):
        return run_provider_agent(
            message,
            history_blocks=history_blocks,
            request_decision=request_deepseek_decision,
            max_tool_calls=getattr(settings, "KALMIO_DEEPSEEK_MAX_TOOL_CALLS", 3),
            progress_callback=progress_callback,
        )


def run_pydantic_ai_agent(
    message: str,
    history_blocks: list[dict] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    from routing.pydantic_ai_agent import request_pydantic_ai_decision

    with agent_trace_turn("pydantic_ai:deepseek"):
        return run_provider_agent(
            message,
            history_blocks=history_blocks,
            request_decision=request_pydantic_ai_decision,
            max_tool_calls=getattr(settings, "KALMIO_DEEPSEEK_MAX_TOOL_CALLS", 3),
            progress_callback=progress_callback,
        )


def run_provider_agent(
    message: str,
    *,
    history_blocks: list[dict] | None,
    request_decision: DecisionRequester,
    max_tool_calls: int,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    history_blocks = history_blocks or []
    decision_message = contextualized_prompt(message, history_blocks)
    tool_history: list[dict[str, Any]] = []
    seen_calls: set[str] = set()
    invalid_decision_retry_used = False
    promised_tool_retry_used = False

    for _ in range(max_tool_calls + 1):
        try:
            emit_progress(
                progress_callback,
                "agent_reasoning",
                "Entendiendo la petición y el contexto útil",
            )
            decision = request_decision(decision_message, tool_history=tool_history)
        except AgentResponseError as exc:
            if not tool_history and not invalid_decision_retry_used:
                invalid_decision_retry_used = True
                record_trace_event(
                    event="agent_guardrail",
                    name="invalid_decision_retry",
                    status="warning",
                    metadata={"reason": str(exc), "recovery": "retry_with_json_reminder"},
                )
                try:
                    decision = request_decision(
                        decision_message
                        + "\n\nTu respuesta anterior no fue JSON válido o no respetó el contrato. "
                        "Reintenta una sola vez: devuelve exactamente un objeto JSON raíz type=tool_call o type=final. "
                        "Si hay datos suficientes para usar una herramienta autorizada, emite tool_call ahora; "
                        "no prometas buscar datos en texto visible.",
                        tool_history=tool_history,
                    )
                except AgentResponseError:
                    raise
            else:
                if tool_history:
                    return fallback_from_tool_history(tool_history, str(exc), decision_message)
                raise
        if decision["type"] == "final":
            if (
                not tool_history
                and not promised_tool_retry_used
                and final_blocks_promise_tool_without_result(decision["blocks"])
            ):
                promised_tool_retry_used = True
                record_trace_event(
                    event="agent_guardrail",
                    name="promised_tool_without_call",
                    status="warning",
                    metadata={"recovery": "retry_allowing_tool_call"},
                    request_payload=decision["blocks"],
                )
                decision = request_decision(
                    decision_message
                    + "\n\nTu respuesta anterior prometía buscar, consultar o mostrar cargadores/ruta, "
                    "pero no emitió ninguna llamada de herramienta. Si el usuario dio ubicación, origen/destino "
                    "o zona suficiente, devuelve type=tool_call. Si falta un dato crítico, devuelve type=final "
                    "preguntando ese dato sin prometer que ya estás buscando.",
                    tool_history=tool_history,
                )
                if decision["type"] != "final":
                    # Continue below so the retried tool_call goes through the same grounding, loop and execution path.
                    pass
                elif final_blocks_promise_tool_without_result(decision["blocks"]):
                    return fallback_from_tool_history(
                        tool_history,
                        "El agente prometió consultar herramientas pero no emitió una llamada ejecutable.",
                        decision_message,
                    )
            if decision["type"] != "final":
                # Fall through to the shared tool-call handling below.
                pass
            else:
                return validated_or_repaired_final_blocks(
                    decision_message,
                    decision["blocks"],
                    tool_history,
                    history_blocks=history_blocks,
                    request_decision=request_decision,
                    progress_callback=progress_callback,
                )

        grounding_issues = tool_call_argument_grounding_issues(
            decision,
            current_message=message,
            history_blocks=history_blocks,
            tool_history=tool_history,
        )
        if grounding_issues:
            return final_or_fallback_after_blocked_tool_call(
                decision_message,
                decision,
                tool_history,
                history_blocks=history_blocks,
                request_decision=request_decision,
                guardrail_name="ungrounded_tool_arguments",
                reason=" ".join(grounding_issues),
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
        emit_progress(
            progress_callback,
            "tool_started",
            conversation_tool_progress_label(decision["tool"]),
            tool=decision["tool"],
        )
        try:
            result = execute_conversation_tool(ToolCall(name=decision["tool"], args=decision["args"]))
        except ConversationToolError as exc:
            result = {"ok": False, "tool": decision["tool"], "error": str(exc)}
        finally:
            tool_duration_ms = elapsed_ms(tool_started)
        emit_progress(
            progress_callback,
            "tool_finished",
            conversation_tool_finished_label(decision["tool"], bool(result.get("ok"))),
            tool=decision["tool"],
            ok=bool(result.get("ok")),
        )
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
    try:
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
    except AgentResponseError as exc:
        return fallback_from_tool_history(tool_history, str(exc), message)
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
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    request_decision = request_decision or request_deepseek_decision
    emit_progress(progress_callback, "validating_a2ui", "Comprobando que la respuesta es segura")
    blocks = validate_blocks(candidate_blocks)
    issues = a2ui_contract_issues(blocks, tool_history, message, history_blocks=history_blocks)
    if not issues:
        return blocks

    record_trace_event(
        event="agent_guardrail",
        name="a2ui_contract_issues",
        status="warning",
        metadata={
            "issueCount": len(issues),
            "issues": issues,
            "recovery": "repair_retry",
        },
        request_payload=candidate_blocks,
    )
    try:
        emit_progress(progress_callback, "repairing_a2ui", "Ajustando la respuesta antes de mostrarla")
        repair_decision = request_decision(
            message,
            tool_history=tool_history,
            repair_issues=issues,
            candidate_blocks=candidate_blocks,
        )
    except AgentResponseError as exc:
        return fallback_from_tool_history(tool_history, str(exc), message)
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


def emit_progress(
    progress_callback: ProgressCallback | None,
    stage: str,
    label: str,
    **metadata: Any,
) -> None:
    if progress_callback is None:
        return
    progress_callback({"stage": stage, "label": label, **metadata})


def conversation_tool_progress_label(tool: str) -> str:
    labels = {
        "resolve_location": "Resolviendo la ubicación",
        "search_destination_chargers": "Consultando puntos de carga autorizados",
        "plan_route": "Calculando ruta y margen de batería",
    }
    return labels.get(tool, "Consultando datos autorizados")


def conversation_tool_finished_label(tool: str, ok: bool) -> str:
    if not ok:
        return "La comprobación necesita una respuesta prudente"
    labels = {
        "resolve_location": "Ubicación resuelta",
        "search_destination_chargers": "Puntos de carga consultados",
        "plan_route": "Ruta calculada",
    }
    return labels.get(tool, "Datos consultados")


def run_deepseek_decision(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    prompt = conversation_agent_prompt(
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

    base_url = getattr(settings, "KALMIO_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=getattr(settings, "KALMIO_DEEPSEEK_TIMEOUT_SECONDS", 30),
    )
    model = getattr(settings, "KALMIO_DEEPSEEK_MODEL", "deepseek-v4-flash")
    provider = openai_compatible_provider_label(base_url)
    request: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Responde solo con JSON válido para respuestas finales. "
                    "Si usas herramientas, emite tool calls nativas o el objeto JSON type=tool_call como objeto raíz; "
                    "nunca pongas tool_call dentro de blocks."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    max_tokens_key = "max_completion_tokens" if provider == "openai" else "max_tokens"
    request[max_tokens_key] = getattr(settings, "KALMIO_DEEPSEEK_MAX_TOKENS", 1800)
    if provider == "deepseek":
        request["extra_body"] = {
            "thinking": {
                "type": "enabled" if getattr(settings, "KALMIO_DEEPSEEK_THINKING", False) else "disabled"
            }
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
            provider=provider,
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
            provider=provider,
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
            provider=provider,
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
        provider=provider,
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


def openai_compatible_provider_label(base_url: str) -> str:
    normalized = base_url.lower()
    if "api.openai.com" in normalized:
        return "openai"
    if "deepseek" in normalized:
        return "deepseek"
    return "openai_compatible"


def deepseek_request_metadata(request: dict[str, Any]) -> dict[str, Any]:
    messages = request.get("messages") if isinstance(request.get("messages"), list) else []
    prompt_chars = sum(len(str(message.get("content") or "")) for message in messages if isinstance(message, dict))
    tools = request.get("tools") if isinstance(request.get("tools"), list) else []
    extra_body = request.get("extra_body") if isinstance(request.get("extra_body"), dict) else {}
    thinking = extra_body.get("thinking") if isinstance(extra_body.get("thinking"), dict) else {}
    return {
        "messageCount": len(messages),
        "promptChars": prompt_chars,
        "maxTokens": request.get("max_tokens") or request.get("max_completion_tokens"),
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
                "description": "Resuelve una ciudad, zona, dirección o POI conocido antes de buscar paradas de carga o calcular ruta.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Ciudad, zona, dirección, hotel o POI textual."},
                        "searchMode": {
                            "type": "string",
                            "enum": ["auto", "poi", "address", "place"],
                            "description": "Pista opcional: poi para hoteles/estaciones/monumentos, address para calles/direcciones, place para ciudades/zonas.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_destination_chargers",
                "description": (
                    "Busca puntos de carga autorizados cerca de una ubicación ya resuelta o coordenadas explícitas. "
                    "Usa purpose para que la herramienta aplique ranking/umbrales según la decisión del agente, "
                    "sin que Django haga parsing conversacional."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": location_schema,
                        "purpose": {
                            "type": "string",
                            "enum": ["urgent", "destination", "stay", "near_route_fallback"],
                            "description": "Propósito ya decidido por el agente para ranking: urgente, destino, estancia o respaldo cercano a ruta.",
                        },
                        "connector": {"type": "string", "description": "Conector si el usuario lo ha indicado."},
                        "radius_km": {"type": "number", "description": "Radio entre 1 y 100 km."},
                        "limit": {"type": "integer", "description": "Número de estaciones, entre 1 y 6."},
                        "requested_services": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Servicios pedidos explícitamente, como restaurant, bathroom, cafe, supermarket.",
                        },
                        "max_useful_power_kw": {
                            "type": "number",
                            "description": "Potencia máxima útil del coche o preferencia; cap de ranking, no dato inventado.",
                        },
                        "require_verified_price": {
                            "type": "boolean",
                            "description": "True solo si el usuario exige precio/tarifa verificada; excluye tarifas estimadas o ausentes.",
                        },
                        "min_total_evses": {
                            "type": "integer",
                            "description": "Tamaño mínimo de hub en puestos de carga registrados.",
                        },
                        "allow_unvalidated_safety": {
                            "type": "boolean",
                            "description": "False solo si el usuario exige seguridad validada; normalmente true porque Kalmio no valida seguridad del entorno.",
                        },
                        "max_data_age_days": {
                            "type": "number",
                            "description": "Freshness máxima aceptable de datos importados si el usuario lo pide.",
                        },
                        "require_access_notes": {
                            "type": "boolean",
                            "description": "True solo si el usuario exige notas de acceso verificadas por fuente.",
                        },
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
                "description": (
                    "Calcula ruta factual con proveedor, estaciones autorizadas del corredor y, solo si hay perfil completo, "
                    "validación energética. Devuelve sub-resultados routeProvider, corridorStations, energyValidation, "
                    "ranking y unsatisfiedConstraints."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": location_schema,
                        "destination": location_schema,
                        "vehicle": {
                            "type": "object",
                            "description": (
                                "Datos del vehículo solo si el usuario ha dado perfil completo: batería, capacidad útil, "
                                "consumo, conector y potencia máxima. Con solo modelo comercial o batería de salida, omite vehicle."
                            ),
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
    return parse_agent_decision(payload)


def parse_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or str(value).strip() == "":
        return {}
    payload = try_decode_json_candidate(str(value))
    if isinstance(payload, dict):
        return payload
    raise AgentResponseError("DeepSeek pidió una herramienta con argumentos JSON inválidos.")


def tool_call_argument_grounding_issues(
    decision: dict[str, Any],
    *,
    current_message: str,
    history_blocks: list[dict],
    tool_history: list[dict[str, Any]],
) -> list[str]:
    tool = str(decision.get("tool") or "")
    args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
    grounding_text = grounded_user_context_text(current_message, history_blocks, tool_history)

    checks: list[tuple[str, Any]] = []
    issues: list[str] = []
    if tool == "search_destination_chargers":
        checks.append(("location", args.get("location")))
    elif tool == "plan_route":
        origin = args.get("origin")
        destination = args.get("destination")
        checks.extend((("origin", origin), ("destination", destination)))
        if same_location_argument(origin, destination):
            label = display_text(origin.get("label") if isinstance(origin, dict) else None, "")
            issues.append(
                f"La herramienta plan_route usa la misma ubicación '{label or 'sin etiqueta'}' como origen y destino. "
                "Falta el origen real del viaje; pregunta desde dónde sale antes de planificar ida/vuelta."
            )
    elif tool == "resolve_location":
        query = display_text(args.get("query"), "")
        normalized_query = normalize(query)
        if not query or location_query_is_generic(normalized_query):
            issues.append(
                f"La herramienta resolve_location usa la consulta genérica '{query or 'sin texto'}'. "
                "Si no hay ciudad, zona, carretera concreta, POI o coordenadas, pregunta por ubicación actual manual; "
                "no intentes resolver 'ubicación actual' ni frases de batería."
            )
        elif not location_query_is_grounded(normalized_query, grounding_text):
            issues.append(
                f"La herramienta resolve_location usa la consulta '{query}' sin que aparezca en el mensaje del usuario "
                "o el historial útil. Usa solo ciudades, zonas o POIs aportados por el usuario."
            )
    else:
        return []

    for key, location in checks:
        if location_argument_is_grounded(location, grounding_text):
            continue
        label = display_text(location.get("label") if isinstance(location, dict) else None, "")
        issues.append(
            f"La herramienta {tool}.{key} usa la ubicación '{label or 'sin etiqueta'}' sin que aparezca "
            "en el mensaje del usuario, el historial útil o una resolución previa. "
            "Pregunta por la ciudad/zona o usa solo ubicaciones aportadas/resueltas; no uses ejemplos del prompt como datos."
        )
    return issues


def location_query_is_generic(normalized_query: str) -> bool:
    generic_terms = {
        "ubicacion actual",
        "mi ubicacion",
        "posicion actual",
        "mi posicion",
        "estoy aqui",
        "aqui",
        "zona actual",
        "carretera",
        "no conozco la zona",
    }
    if normalized_query in generic_terms:
        return True
    return bool(re.search(r"\bestoy\s+al\s+\d{1,3}\s*%?\b", normalized_query))


def location_query_is_grounded(normalized_query: str, grounded_text: str) -> bool:
    if normalized_query and normalized_query in grounded_text:
        return True
    tokens = location_label_tokens(normalized_query)
    return bool(tokens) and all(token in grounded_text for token in tokens)


def grounded_user_context_text(
    current_message: str,
    history_blocks: list[dict],
    tool_history: list[dict[str, Any]],
) -> str:
    parts = [current_message]
    for item in history_blocks:
        if not isinstance(item, dict):
            continue
        props = item.get("props") if isinstance(item.get("props"), dict) else {}
        if item.get("type") == "UserMessage":
            parts.append(display_text(props.get("text"), ""))

    for entry in tool_history:
        if not isinstance(entry, dict):
            continue
        call = entry.get("call") if isinstance(entry.get("call"), dict) else {}
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        for key in ("location", "origin", "destination"):
            parts.append(location_argument_text(args.get(key)))
            parts.append(location_argument_text(result.get(key)))
        if call.get("tool") == "resolve_location":
            parts.append(display_text(args.get("query"), ""))
            parts.append(location_argument_text(result.get("location")))

    return normalize(" ".join(part for part in parts if part))


def user_conversation_text(message: str, history_blocks: list[dict]) -> str:
    parts = [current_user_message_text(message)]
    for item in history_blocks:
        if not isinstance(item, dict) or item.get("type") != "UserMessage":
            continue
        props = item.get("props") if isinstance(item.get("props"), dict) else {}
        parts.append(display_text(props.get("text"), ""))
    return normalize(" ".join(part for part in parts if part))


def current_user_message_text(message: str) -> str:
    marker = "Mensaje actual del usuario:"
    if marker not in message:
        return message
    return message.rsplit(marker, 1)[-1].strip()


def location_argument_is_grounded(location: Any, grounded_text: str) -> bool:
    if not isinstance(location, dict):
        return False
    label = display_text(location.get("label"), "")
    if not label:
        return False
    normalized_label = normalize(label)
    if normalized_label and normalized_label in grounded_text:
        return True
    tokens = location_label_tokens(normalized_label)
    return bool(tokens) and all(token in grounded_text for token in tokens)


def same_location_argument(first: Any, second: Any) -> bool:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    first_label = normalize(display_text(first.get("label"), ""))
    second_label = normalize(display_text(second.get("label"), ""))
    if first_label and second_label and first_label == second_label:
        return True
    try:
        first_lat = float(first.get("lat"))
        first_lon = float(first.get("lon"))
        second_lat = float(second.get("lat"))
        second_lon = float(second.get("lon"))
    except (TypeError, ValueError):
        return False
    return abs(first_lat - second_lat) < 0.0001 and abs(first_lon - second_lon) < 0.0001


def location_label_tokens(normalized_label: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", normalized_label) if len(token) >= 3]


def location_argument_text(location: Any) -> str:
    if not isinstance(location, dict):
        return ""
    return display_text(location.get("label"), "")


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


def final_blocks_promise_tool_without_result(blocks: list[dict]) -> bool:
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks if isinstance(block, dict)))
    if not visible_text:
        return False
    promise_patterns = (
        r"\b(voy|vamos)\s+a\s+(buscar|consultar|comprobar|calcular|mostrar)\b",
        r"\b(te\s+)?(busco|consulto|compruebo|calculo|muestro)\b",
        r"\b(he\s+de\s+buscar|necesito\s+buscar)\b",
    )
    tool_subject_terms = (
        "cargador",
        "cargadores",
        "carga",
        "punto de carga",
        "puntos de carga",
        "estacion",
        "estaciones",
        "ruta",
        "parada",
        "paradas",
    )
    return any(re.search(pattern, visible_text) for pattern in promise_patterns) and any(
        term in visible_text for term in tool_subject_terms
    )


def attr_or_key(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def compact_tool_history_for_prompt(tool_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for entry in tool_history:
        if not isinstance(entry, dict):
            continue
        call = entry.get("call") if isinstance(entry.get("call"), dict) else {}
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        tool_name = display_text(call.get("tool") or result.get("tool"), "")
        compacted.append(
            {
                "call": compact_prompt_value(call),
                "result": compact_tool_result_for_prompt(result, tool_name),
            }
        )
    return compacted


def compact_tool_result_for_prompt(result: dict[str, Any], tool_name: str = "") -> dict[str, Any]:
    tool_name = display_text(result.get("tool") or tool_name, "")
    if not result:
        return {}
    if not result.get("ok"):
        return {
            "ok": result.get("ok"),
            "tool": tool_name or result.get("tool"),
            "error": result.get("error"),
        }

    if tool_name == "plan_route":
        compact: dict[str, Any] = {}
        for key in (
            "ok",
            "tool",
            "planningLevel",
            "origin",
            "destination",
            "distanceKm",
            "durationMin",
            "energyKwh",
            "arrivalBattery",
            "corridorRadiusKm",
            "warnings",
            "routeProvider",
            "energyValidation",
            "ranking",
            "unsatisfiedConstraints",
        ):
            if key in result:
                compact[key] = compact_prompt_value(result[key])
        if isinstance(result.get("corridorStations"), dict):
            corridor = {
                key: compact_prompt_value(value)
                for key, value in result["corridorStations"].items()
                if key != "stations"
            }
            stations = result["corridorStations"].get("stations")
            if isinstance(stations, list):
                corridor["stations"] = compact_station_list_for_prompt(stations, limit=3)
                corridor["stationCount"] = len(stations)
            compact["corridorStations"] = corridor
        if isinstance(result.get("routeGeometry"), dict):
            compact["routeGeometrySummary"] = route_geometry_summary_for_prompt(result["routeGeometry"])
        if isinstance(result.get("recommendation"), dict):
            compact["recommendation"] = compact_station_for_prompt(result["recommendation"])
        if isinstance(result.get("alternatives"), list):
            compact["alternatives"] = compact_station_list_for_prompt(result["alternatives"], limit=3)
            compact["alternativeCount"] = len(result["alternatives"])
        return compact

    if tool_name == "search_destination_chargers":
        compact = {}
        for key in ("ok", "tool", "location", "warnings", "error"):
            if key in result:
                compact[key] = compact_prompt_value(result[key])
        stops = result.get("stops")
        if isinstance(stops, list):
            compact["stops"] = compact_station_list_for_prompt(stops, limit=6)
            compact["stopCount"] = len(stops)
        return compact

    if tool_name == "resolve_location":
        compact = {}
        for key in ("ok", "tool", "searchMode", "location", "candidates", "source", "precision", "isApproximate", "error"):
            if key in result:
                compact[key] = compact_prompt_value(result[key])
        if isinstance(compact.get("candidates"), list):
            compact["candidates"] = compact["candidates"][:3]
            compact["candidateCount"] = len(result.get("candidates") or [])
        return compact

    return compact_prompt_value(result)


def compact_station_list_for_prompt(stations: list[Any], *, limit: int) -> list[dict[str, Any]]:
    return [compact_station_for_prompt(station) for station in stations[:limit] if isinstance(station, dict)]


def compact_station_for_prompt(station: dict[str, Any]) -> dict[str, Any]:
    compact = station_props_from_result(station)
    for key in ("reliability", "confidence"):
        if key in station and key not in compact:
            compact[key] = station[key]
    score_reasons = station.get("scoreReasons")
    if isinstance(score_reasons, list) and score_reasons:
        compact["scoreReasons"] = [str(reason) for reason in score_reasons[:5]]
    return compact_prompt_value(compact)


def compact_blocks_for_prompt(blocks: list[Any]) -> list[Any]:
    compacted: list[Any] = []
    for item in blocks:
        if not isinstance(item, dict):
            compacted.append(item)
            continue
        block_type = display_text(item.get("type"), "")
        compacted.append(
            {
                key: compact_prompt_value(value)
                for key, value in item.items()
                if key != "props"
            }
            | {"props": compact_block_props_for_prompt(block_type, item.get("props"))}
        )
    return compacted


def compact_block_props_for_prompt(block_type: str, props: Any) -> Any:
    if not isinstance(props, dict):
        return compact_prompt_value(props)
    if block_type in STATION_CARD_TYPES:
        return compact_station_for_prompt(props)
    if block_type == "StationList":
        compact = {key: compact_prompt_value(value) for key, value in props.items() if key != "stations"}
        stations = props.get("stations")
        if isinstance(stations, list):
            compact["stations"] = compact_station_list_for_prompt(stations, limit=6)
            compact["stationCount"] = len(stations)
        return compact
    if block_type == "RouteCorridorCard":
        compact = {}
        for key, value in props.items():
            if key == "routeGeometry" and isinstance(value, dict):
                compact["routeGeometrySummary"] = route_geometry_summary_for_prompt(value)
            elif key == "primaryStation" and isinstance(value, dict):
                compact[key] = compact_station_for_prompt(value)
            elif key == "stations" and isinstance(value, list):
                compact[key] = compact_station_list_for_prompt(value, limit=6)
                compact["stationCount"] = len(value)
            else:
                compact[key] = compact_prompt_value(value)
        return compact
    return compact_prompt_value(props)


def compact_prompt_value(value: Any) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, nested in value.items():
            if key == "routeGeometry" and isinstance(nested, dict):
                compact["routeGeometrySummary"] = route_geometry_summary_for_prompt(nested)
            elif key == "coordinates" and looks_like_route_coordinates(nested):
                compact["coordinatesSummary"] = {"pointCount": route_coordinate_point_count(nested)}
            else:
                compact[key] = compact_prompt_value(nested)
        return compact
    if isinstance(value, list):
        return [compact_prompt_value(item) for item in value]
    return value


def looks_like_route_coordinates(value: Any) -> bool:
    return isinstance(value, list) and route_coordinate_point_count(value) > 20


def route_geometry_summary_for_prompt(route_geometry: dict[str, Any]) -> dict[str, Any]:
    coordinates = route_geometry.get("coordinates")
    summary: dict[str, Any] = {
        "present": True,
        "type": route_geometry.get("type"),
        "pointCount": route_coordinate_point_count(coordinates),
    }
    return {key: value for key, value in summary.items() if value not in (None, "")}


def route_coordinate_point_count(coordinates: Any) -> int:
    if not isinstance(coordinates, list) or not coordinates:
        return 0
    if len(coordinates) >= 2 and all(isinstance(item, (int, float)) for item in coordinates[:2]):
        return 1
    return sum(route_coordinate_point_count(item) for item in coordinates)


def conversation_agent_prompt(
    message: str,
    tool_history: list[dict[str, Any]] | None = None,
    repair_issues: list[str] | None = None,
    candidate_blocks: list[dict] | None = None,
) -> str:
    tool_history = tool_history or []
    repair_issues = repair_issues or []
    candidate_blocks = candidate_blocks or []
    prompt_tool_history = compact_tool_history_for_prompt(tool_history)
    prompt_candidate_blocks = compact_blocks_for_prompt(candidate_blocks)
    known_locations = "; ".join(
        f"{label}({lat:.4f},{lon:.4f})" for label, lat, lon in KNOWN_LOCATIONS.values()
    )
    tool_instructions = (
        "Herramientas permitidas. Puedes llamar solo una por respuesta tool_call:\n"
        '- resolve_location: resuelve ciudad, zona, calle/dirección o POI. Args: {"query":"texto",'
        '"searchMode":"auto|poi|address|place"}; usa poi para hoteles, estaciones, monumentos o recintos; '
        "address para calles/direcciones; place para ciudades/zonas; auto si no está claro.\n"
        "- search_destination_chargers: busca puntos de carga autorizados alrededor de una ubicación ya resuelta o "
        'coordenadas dadas por el usuario. Args: {"location":{"label":"...","lat":0,"lon":0},"connector":null,'
        '"purpose":"destination|urgent|stay|near_route_fallback","radius_km":80,"limit":3,'
        '"requested_services":[],"max_useful_power_kw":null,"require_verified_price":false,'
        '"min_total_evses":null,"allow_unvalidated_safety":true,"max_data_age_days":null,'
        '"require_access_notes":false}\n'
        "- plan_route: calcula ruta y paradas con proveedor y datos autorizados. Args: "
        '{"origin":{"label":"...","lat":0,"lon":0},"destination":{"label":"...","lat":0,"lon":0},'
        '"vehicle":null,"preferences":{"reserve_min_percent":20,"max_useful_power_kw":null},"corridor_radius_km":25}\n'
        "Si el mensaje trae origen y destino concretos y pide ruta, paradas, pocas paradas, parada rápida/barata/cómoda "
        "o comparación de paradas, la primera decisión debe ser plan_route con vehicle:null cuando falte perfil completo; "
        "pide autonomía/consumo/modelo después como límite de validación, no antes de llamar la herramienta.\n"
        "Nunca llames herramientas con label vacío, lat/lon 0,0, placeholders o ubicaciones no dadas/resueltas; pregunta antes. "
        "Nunca llames resolve_location con 'ubicación actual', 'mi ubicación', 'zona actual', porcentajes de batería o frases genéricas; resolve_location solo acepta ciudad, zona, carretera concreta o POI nombrado por el usuario.\n"
        "Ubicaciones internas conocidas para argumentos de herramienta, sin inventar otras coordenadas: "
        f"{known_locations}.\n"
    )
    behavior_instructions = (
        "Comportamiento EV esperado:\n"
        "- Usa el historial útil, acepta correcciones naturales y no suenes como formulario.\n"
        "- Presenta las recomendaciones como paradas o lugares útiles para el viaje; usa name/stationName como punto de carga trazable y placeName solo si sale de herramienta o del usuario. No inventes lugares, servicios ni POIs.\n"
        "- Modelo de composición A2UI: una respuesta debe sentirse como una unidad de decisión accionable, no como una pila de tarjetas. Por defecto empieza con AssistantMessage de 1-3 frases: explica la decisión, ubicación usada, límite o problema relevante y el siguiente paso útil sin ocultar incertidumbre. Después muestra una sola card principal (StationPreviewCard o RouteCorridorCard) y acciones útiles. RouteCorridorCard es mapa de corredor y estaciones cercanas a la ruta; no la presentes como parada recomendada. Si usas ActionButtons para una recomendación, colócalos inmediatamente después de la card a la que pertenecen; el renderer los tratará como el pie de acción de esa decisión. Si hay cautela, riesgo o límite de datos, ponlo en el AssistantMessage previo a la card, nunca como bloque intermedio entre la card principal y ActionButtons. No uses ActionButtons para repetir texto ni como sustituto de herramientas necesarias.\n"
        "- No existe un componente separado de riesgo ni de aclaración. Explica riesgos, incertidumbres, límites de datos, datos faltantes y siguientes pasos en AssistantMessage antes de la card principal. Usa ErrorFallbackCard solo para fallos técnicos renderizables. Mantén StationList fuera de la primera respuesta salvo que cambie una decisión, haya empate real, baja confianza, o el usuario pida comparar/ver más opciones.\n"
        "- En copy visible, expresa duraciones largas en horas y minutos (por ejemplo, 8 h 37 min), no como cientos de minutos. Evita la palabra técnica 'trazado/trazados': para el conductor usa 'según los datos disponibles', 'registrado', 'indicado', 'verificado' o 'autorizado' según el dato.\n"
        "- Carga urgente sin ubicación: pide solo ubicación actual, ciudad/zona o coordenadas. Si necesitas que el conductor comparta ubicación actual o escriba una ubicación manual, usa PositionRequestCard para ofrecer 'Usar mi ubicación' y 'Escribir ubicación'; no lo sustituyas por un AssistantMessage de texto. No pidas destino para una carga urgente. No llames resolve_location con frases que no son ubicaciones concretas, como 'ubicación actual', 'mi ubicación', 'estoy al 12%', 'no conozco la zona', 'estoy en carretera', 'tengo poca batería' o 'voy con niños'; pregunta el dato mínimo primero.\n"
        "- Tras una urgencia, una ciudad/zona/coordenadas es continuación de la urgencia; usa herramientas si hay ubicación suficiente.\n"
        "- Si el usuario corrige la ubicación, descarta la anterior, conserva batería, conector y preferencias si siguen teniendo sentido y busca con la nueva.\n"
        "- Si pregunta por un fallo anterior, no contradigas bloques ya validados; explica validación, cobertura, aproximación o datos autorizados.\n"
        "- Calle/POI/zona: intenta resolver la parte conocida con resolve_location. Si no puedes ubicar esa calle exacta, dilo y ofrece ciudad aproximada o coordenadas; no inventes coordenadas.\n"
        "- Ruta sin consumo/modelo: puedes usar plan_route para explorar contexto de ruta y estaciones cercanas al corredor, pero no inventes autonomía, energía ni llegada. Si plan_route devuelve planningLevel=chargers_only, dilo. Usa RouteCorridorCard para distancia/duración/mapa/estaciones cercanas de la herramienta y solo después de plan_route; no calcules ni inventes distancia/duración sin herramienta. RouteCorridorCard debe ser compacta en chat: destaca el mapa y el número de estaciones cerca de la ruta, con batería al llegar solo si la herramienta la trae; deja energía, ratios, pins y lectura densa para el detalle del mapa. No la llames parada sugerida ni recomendación. StationPreviewCard queda para una estación autorizada concreta cuando el usuario pida o el contexto justifique una recomendación explícita; StationList queda para comparar/ver más opciones, empate real o baja confianza. Di visiblemente que no puedes validar batería de llegada ni reserva sin consumo/perfil. No repitas la duración en prosa si ya está en RouteCorridorCard; evita frases como '4 horas' y deja el dato en la tarjeta o usa formato '4 h'. El AssistantMessage inicial debe explicar antes de la card qué puedes mostrar, qué no puedes validar y cuál es el siguiente paso; muestra después el mapa de corredor pronto en móvil. Patrón recomendado: AssistantMessage explicativo, una RouteCorridorCard principal, ActionButtons para ver detalle/refinar, y solo después StationPreviewCard o StationList si hay una recomendación o comparación justificada. Si el usuario pregunta si 'le da', 'llega sin cargar' o 'puede llegar sin cargar' y hay origen/destino pero faltan batería actual, autonomía, modelo o consumo, debes llamar plan_route para mostrar distancia/duración de proveedor; no respondas sí/no, no afirmes que llega, pide esos datos críticos, y no muestres StationPreviewCard/StationList como recomendación principal salvo que el usuario pida paradas de respaldo o plan B. Si el usuario prefiere parar pocas veces y ya hay origen/destino, debes llamar plan_route; si faltan autonomía/consumo/modelo, di antes de las estaciones que no puedes garantizar ni optimizar pocas paradas sin esos datos; presenta cualquier estación solo como punto de carga autorizado en el corredor, no como plan optimizado. Si el usuario dice que sale con X%, ese X% es batería de salida, no de llegada ni reserva; no escribas 'llegas con X%'. Si el usuario pide no llegar justo sin dar un porcentaje de reserva, no digas que indicó 20%; si usas reserve_min_percent por defecto, llámalo margen conservador por defecto. No digas asegurar/garantizar margen en chargers_only ni 'te ayudará a recuperar margen'; di que cargar en el corredor puede ayudar a recuperar margen operativo no validado. Si el viaje es futuro (mañana, fecha concreta, finde, viernes/domingo), añade en el AssistantMessage inicial, antes de cualquier RouteCorridorCard, StationPreviewCard o StationList, una advertencia visible: disponibilidad, acceso y tarifas pueden cambiar antes del viaje.\n"
        "- Perfil de vehículo: un modelo comercial como Tesla Model Y y una batería de salida no son un perfil autorizado de consumo/autonomía. Para plan_route, usa vehicle:null u omite vehicle salvo que el usuario haya dado explícitamente batería, capacidad útil kWh, consumo kWh/100 km, conector y potencia máxima. No rellenes campos desconocidos con null, ceros o defaults. Puedes mencionar modelo y batería en el copy, pero no calcular energía, autonomía ni llegada con ellos.\n"
        "- Hotel/destino/estancia: si hay ciudad/POI suficiente y el usuario necesita cargar durante la estancia, llama search_destination_chargers directamente; no devuelvas solo un botón para buscar ni una respuesta final que diga 'buscaré'. Una ciudad conocida ya es ubicación suficiente para una búsqueda aproximada; no esperes hotel/zona exacta para la primera búsqueda, puedes pedir refinamiento después de mostrar resultados. Si tienes una ciudad conocida pero no tienes coordenadas exactas del hotel/POI, la primera decisión debe ser type=tool_call search_destination_chargers con la ciudad como location approximate, no type=final. Si el usuario da un POI/hotel dentro de una ciudad conocida, usa primero la ciudad/zona como aproximación verificable salvo que tengas coordenadas exactas autorizadas del POI; evita empezar por un punto muy estrecho que pueda ocultar cargadores urbanos útiles. No lo conviertas en ruta salvo que pidan origen-destino. Si muestras resultados de destino/estancia, explica en AssistantMessage la ubicación usada y si es aproximada; pide dirección, zona exacta o coordenadas para refinar cuando falte el punto exacto. Si el usuario dijo que el hotel no tiene cargador y la herramienta devuelve varias paradas, elige una parada primaria con StationPreviewCard usando solo distancia, potencia, conectores y puestos de carga registrados, y usa ActionButtons para navegar, refinar o pedir más opciones; no la presentes como disponibilidad en vivo ni como reserva. Reserva StationList para cuando el usuario pida ver/comparar opciones, haya empate real, baja confianza o alternativas materialmente útiles que cambien la decisión.\n"
        "- Si buscas por ciudad aproximada porque el hotel/POI exacto no está resuelto, la respuesta visible debe decirlo en AssistantMessage: usa la ciudad como aproximación, no como ubicación exacta del hotel/POI, y pide dirección, zona exacta o coordenadas para refinar.\n"
        "- Si el usuario menciona ida y vuelta, volver, regreso o fechas de salida/vuelta, reconoce contexto de viaje redondo. Si falta origen para planificar ida/vuelta, pregunta por el origen en un AssistantMessage antes de pedir hotel/zona y no llames plan_route ni search_destination_chargers todavia. No uses la ciudad destino como origen.\n"
        "- Si resolve_location recibe un hotel, calle o POI pero solo devuelve una ciudad/zona, no afirmes que conoces el lugar exacto; no presentes el hotel exacto como ubicación validada; di que usas esa ciudad/zona como aproximación o pide coordenadas/dirección exacta.\n"
        "- Si search_destination_chargers devuelve stops, trátalos como estaciones: usa StationPreviewCard para una estación concreta o StationList para varias, con nombres y métricas exactas trazables. No uses placeholders cuando hay estaciones. Antes de llamar una herramienta, no crees StationPreviewCard genéricos como 'Cargador en Granada', potencia 0, distancia 0 o coordenadas iguales a la ciudad: pide herramienta o pregunta el dato mínimo.\n"
        "- Al llamar search_destination_chargers, decide purpose por contexto útil y pásalo explícitamente: urgent para carga inmediata/batería baja/cerca de mí, destination para cargar cerca de destino/hotel/POI, stay para estancias de varios días o cargar durante la estancia, near_route_fallback para plan B cerca de corredor cuando no procede calcular ruta completa. Purpose solo ajusta ranking/umbrales de la herramienta; no es intent parsing de Django. Pasa requested_services solo si el usuario pidió servicios concretos; max_useful_power_kw solo si el usuario/coche dio ese límite; require_verified_price solo si exige precio verificado; min_total_evses para hubs grandes; allow_unvalidated_safety=false solo si el usuario exige seguridad validada, sabiendo que normalmente no habrá resultados porque Kalmio no valida seguridad del entorno; max_data_age_days y require_access_notes solo si pide freshness o notas de acceso verificadas.\n"
        "- En móvil, no satures la primera respuesta con todas las alternativas si hay una estación primaria clara. Por defecto, no muestres StationList en esa primera respuesta: prefiere StationPreviewCard para la recomendación y ActionButtons inmediatamente después para navegar, pedir más opciones o ajustar la búsqueda. Para pedir más opciones, usa ActionButtons con event.name='show_more_options' y un context trazable de la búsqueda o estación cuando exista; para navegación usa functionCall.openUrl si hay lat/lon trazables. Usa StationList cuando el usuario pida comparar/más opciones, cuando haya empate real, baja confianza o alternativas materialmente útiles que cambien la decisión. Si muestras StationPreviewCard y StationList juntos, no repitas la estación primaria dentro de StationList.\n"
        "- No uses superlativos globales como 'el más rápido en la ciudad' o 'el mejor de Córdoba' salvo que la herramienta lo demuestre. Acota a 'entre estas opciones' o 'según los datos disponibles' cuando compares potencia/distancia.\n"
        "- Si ya hay stops con potencia/distancia/disponibilidad y el usuario pide comparar potencia, alternativas o más opciones, responde con esos resultados previos; no repitas la misma búsqueda sin cambiar ubicación, radio, conector o criterio material.\n"
        "- Si una herramienta permitida falla, explica el fallo en contexto y pide una acción mínima; no fabriques datos.\n"
        "- Batería baja: pocas opciones, riesgo explícito, y ActionButtons de navegación con functionCall.openUrl cuando la estación recomendada tiene lat/lon trazables. Puedes mencionar la batería en texto de riesgo si aporta contexto, pero no la uses como métrica principal de StationPreviewCard. "
        "Si el usuario dice poca batería sin porcentaje explícito, no inventes un número; explica la batería baja en AssistantMessage. "
        "Trata esa situación como urgente. Orden exacto recomendado si hay coordenadas de herramienta: AssistantMessage con el riesgo y la decisión, StationPreviewCard, ActionButtons, y solo después StationList si hace falta; nunca pongas AssistantMessage ni StationList entre StationPreviewCard y ActionButtons en este caso. "
        "Con batería <=10%, prioriza una sola estación primaria, muestra el riesgo de margen muy bajo primero en AssistantMessage y junto a esa estación como frase visible para el conductor, y deja solo 1-2 alternativas adicionales después. "
        "Si la estación primaria tiene lat/lon trazables, ActionButtons con functionCall.openUrl es obligatorio y debe ir antes de cualquier StationList; no lo sustituyas por texto. "
        "Pon el aviso de riesgo en AssistantMessage antes de las alternativas.\n"
        "- No describas availableEvses, totalEvses o puestos importados como 'libres', 'disponibles en vivo' u ocupación actual. En copy visible para conductores di 'puestos de carga registrados' o 'puestos'; evita la sigla técnica EVSE salvo en nombres de campos internos. Si tienes availableEvses y totalEvses, puedes mostrarlo como ratio de puestos disponibles/total, por ejemplo '4/10 puestos', sin llamarlo disponibilidad en vivo. Usa 'conectores' solo para connectorTypes como CCS2 o Type2. Si el usuario pide evitar cargadores con un solo conector/EVSE, prioriza estaciones con más de 1 puesto registrado cuando la herramienta lo soporte y explica el dato sin afirmar ocupación en vivo.\n"
        "- Punto de carga ocupado: si el historial deja claro cuál era la parada primaria anterior, no la repitas como plan B. "
        "En la respuesta visible, nombra la parada descartada y deja claro que no debe seguir siendo el plan principal. "
        "Reutiliza exactamente alternativas previas de la herramienta con sus nombres, distancias, potencia y coordenadas; no cambies métricas ni inventes coordenadas. "
        "Si un dato como precio, dirección exacta o puestos de carga no estaba en la alternativa previa, omítelo en vez de completarlo. "
        "Si usas navegación para una alternativa previa, usa su lat/lon exactos. Si no hay alternativas previas suficientes, vuelve a buscar con la ubicación previa o pide el dato mínimo que falte. "
        "Recuerda que la disponibilidad en vivo puede cambiar.\n"
        "- En carretera y poco desvío: pide carretera, zona actual/coordenadas y destino si faltan; no lo reduzcas a búsqueda urbana arbitraria. "
        "Cuando no haya ubicación suficiente, usa AssistantMessage con una pregunta breve sobre carretera/zona actual, destino o coordenadas. "
        "Usa PositionRequestCard solo si basta con posición actual/manual del conductor; no muestres campos genéricos de ciudad si el usuario ya dijo que está en carretera y quiere poco desvío.\n"
        "- Si el coche carga máximo a X kW, pasa X como preferences.max_useful_power_kw; si recomiendas un cargador de más potencia, di antes de la primera parada una frase explícita como: 'Tu coche no aprovechará más de X kW; la potencia superior no se premia en esta elección'. No basta con decir que no necesita ultrarrápidos. No presentes la potencia superior como ventaja. No digas que has filtrado o excluido paradas por potencia si todavía muestras una estación por encima de ese máximo útil; di que esa potencia superior no se premia ni cambia lo que el coche puede aprovechar.\n"
        "- Restricción dura de llegada: sin perfil de vehículo no la presentes como cumplida; pide modelo/consumo/autonomía. Si la herramienta devuelve arrivalBattery:null o energyKwh:null, no los sustituyas por estimaciones ni por frases de certeza. Si el usuario pide llegar con al menos X%, pasa X como reserve_min_percent y di antes de cualquier StationPreviewCard/StationList que ese X% no se puede validar en chargers_only sin consumo/perfil.\n"
        "- Preferencias de precio, hubs grandes o tamaño de parada: trátalas como preferencia de decisión sobre paradas, no como comparación de hardware. Si falta ruta o ubicación, no llames herramientas con ubicaciones vacías; pide origen/destino o ubicación actual. Usa pricePerKwhEur/currency solo cuando venga de herramienta y priceIsEstimated no sea true; muestra tarifas verificadas dentro de StationPreviewCard o StationList. No calcules coste total de una sesión si no hay energía/cantidad de carga. Si no hay tarifas de proveedor o solo hay tarifas estimadas, dilo en AssistantMessage sin mostrar precio. No conviertas una preferencia de precio en una ruta arriesgada.\n"
        "- Cargar antes de salir vs al llegar: si faltan datos, no calcules. Da una comparación conceptual breve: cargar antes reduce riesgo si sales bajo, la ruta es larga o no conoces carga en destino; cargar al llegar puede tener sentido si llegas con margen y hay punto autorizado en destino. Luego pide origen, destino, batería actual y modelo/consumo/autonomía.\n"
        "- Viajes futuros: di visiblemente antes de mostrar paradas que disponibilidad, acceso y tarifas pueden cambiar antes del viaje. En reparaciones A2UI, no elimines esa advertencia; debe conservar las tres palabras disponibilidad, acceso y tarifas antes de cualquier lista de paradas. Niños/comodidad: si la herramienta trae amenities en la parada primaria, debes mencionarlos brevemente por nombre en la respuesta visible como servicios indicados o comodidad potencial despues del riesgo principal; no digas que están cerca, disponibles, son seguros, ideales, perfectos o aptos para niños salvo que el dato venga explícitamente de la herramienta. Separa proximidad de servicios: puedes decir que la estación está cerca de la ubicación buscada y que trae servicios indicados, pero no digas que restaurantes/cafeterías/baños están cerca si la herramienta solo trae amenities.\n"
        "- Preferencias de servicios como baños, cafetería, restaurante o comer: si faltan ruta o ubicación, pregunta por ubicación/ruta. Si el siguiente turno aporta ciudad, zona o coordenadas, conserva esa preferencia y llama search_destination_chargers con esa ubicación; no vuelvas a preguntar qué necesita. Si la búsqueda devuelve amenities vacíos o no incluye esos servicios, muestra los cargadores encontrados y di visiblemente que baños/cafetería/restaurante no están verificados en esos resultados.\n"
        "- Preferencias de desvío controlado por comodidad: usa route tooling si hay ruta. Si la herramienta trae detourMin y amenities, presenta la parada primaria como punto autorizado dentro o cerca del margen pedido y menciona servicios indicados como comodidad potencial; no digas 'buenos servicios', 'más cómodo' ni que el sitio es cómodo si la herramienta solo trae amenities. No introduzcas preferencias de pocas paradas salvo que el usuario las pida. Si muestras alternativas, conserva el desvío de la herramienta para que el usuario pueda comparar.\n"
        "- Preferencias de seguridad nocturna o evitar sitios solitarios: si falta ubicación/ruta, pregunta por el dato mínimo sin prometer que buscarás sitios con afluencia, actividad, vigilancia o iluminación. Si el siguiente turno aporta ciudad, zona o coordenadas, conserva esa preferencia y llama search_destination_chargers con esa ubicación; no respondas solo con una ubicación resuelta. Puedes priorizar señales disponibles como dirección céntrica, potencia, puestos de carga/conectores o hub si la herramienta lo trae; no afirmes seguridad, vigilancia, iluminación, afluencia, actividad ni que sea menos probable que un lugar sea solitario. Di en AssistantMessage que Kalmio no valida seguridad ni entorno en vivo y que el conductor debe verificar el entorno al llegar de noche. Si muestras alternativas, ese límite debe aparecer antes de StationList para que no quede escondido en móvil.\n"
        "- Estancias de varios días: piensa en carga durante estancia y vuelta; si hay viaje redondo y falta origen, pídelo; si solo pide carga en destino y hay ubicación suficiente, busca en destino. Si la estancia añade riesgo o una decisión útil, explícalo con AssistantMessage; no repitas destino/noches en un componente dedicado.\n"
        "- Rutas baratas, reservas duras, carga justa o comparativas rápida/barata necesitan origen, destino y datos de vehículo/batería para calcular energía, llegada o coste total; si faltan, pregunta en el mismo turno por origen, destino, batería actual y modelo/consumo/autonomía. Si la herramienta sí trae pricePerKwhEur y priceIsEstimated no es true, puedes comparar tarifa por kWh entre estaciones. No inventes tarifas, kWh, llegada ni comparativas de precio; si no hay datos de tarifas de proveedor, dilo.\n"
        "Ejemplos críticos por analogía, no reglas rígidas: 'Necesito cargar ya' -> pide ubicación, no destino; 'En Córdoba' tras urgencia -> busca Córdoba; "
        "'Paseo de la Victoria de Córdoba' -> si solo resuelves Córdoba, explica la aproximación; "
        "'Voy a dormir en Valencia, busca cargadores cerca del hotel' -> llama search_destination_chargers con Valencia como aproximación y explica que el hotel exacto refina; "
        "'Valencia centro' tras hotel sin cargador -> AssistantMessage explicando que usas Valencia centro como aproximación y que falta hotel exacto si el límite cambia la decisión + StationPreviewCard + ActionButtons pegados a la recomendación; deja que el usuario pida alternativas; "
        "'Voy a Granada y duermo cerca de la Alhambra' -> devuelve type=tool_call search_destination_chargers; usa Granada como primera búsqueda aproximada para no esconder cargadores urbanos si no tienes coordenadas exactas autorizadas del alojamiento; en la respuesta final posterior a la herramienta, si es finde, antes de paradas di que disponibilidad, acceso y tarifas pueden cambiar, di que usas Granada/Alhambra como aproximación y no como ubicación exacta del alojamiento, y pide hotel/zona/direccion exacta para refinar; "
        "'Me voy 3 días a Córdoba y me quedo en el hotel Meliá' -> llama search_destination_chargers con Córdoba como aproximación, no ActionButtons; "
        "'Voy una semana a Cádiz y necesito cargar durante la estancia' -> llama search_destination_chargers con Cádiz como aproximación; usa AssistantMessage para explicar la ubicación usada y la incertidumbre de estancia, no preguntes primero por hotel/zona; "
        "'Quiero la ruta más barata, pero sin bajar del 20%' sin origen/destino -> no llames plan_route, pregunta origen, destino y datos de vehículo/batería; "
        "'Voy a Córdoba el viernes y vuelvo el domingo' -> AssistantMessage preguntando origen/salida para planificar ida/vuelta antes de llamar herramientas; "
        "'Zaragoza a Barcelona con 25%' sin consumo/modelo -> no valides ese 25%; "
        "'Córdoba a Valencia con 58%, no quiero llegar justo' -> plan_route puede mostrar RouteCorridorCard con estaciones autorizadas del corredor, pero debes decir que la llegada/reserva no se valida sin consumo o perfil; "
        "'Sevilla a Granada, me da para llegar sin cargar?' -> plan_route puede mostrar RouteCorridorCard de distancia/duración, pero no respondas sí/no sin batería actual/autonomía/modelo/consumo; pide esos datos; "
        "'Alicante a Bilbao, prefiero parar pocas veces' -> plan_route puede mostrar contexto y puntos de corredor, pero debes decir antes que no puedes optimizar pocas paradas sin autonomía/consumo/modelo; "
        "'Evita cargadores caros si hay alternativas razonables' -> pide ruta o ubicación; si la herramienta trae tarifas verificadas, compara tarifa/kWh, si no, aclara que no inventas tarifas; "
        "'Prefiero hubs grandes aunque sean un poco más caros' -> no llames herramientas sin ruta/ubicación; pide ruta o ubicación actual y usa tarifas verificadas solo si el proveedor las da; "
        "'Me conviene cargar antes de salir o al llegar?' -> compara conceptualmente y pide origen, destino, batería y vehículo antes de calcular; "
        "'Busca una parada con baños y cafetería' -> pregunta ubicación/ruta; 'Estoy cerca de Almansa' después -> llama search_destination_chargers con Almansa, muestra cargadores encontrados y di que baños/cafetería no están verificados si amenities viene vacío; "
        "'Prefiero desviarme 10 minutos si el sitio es más cómodo. Voy de Madrid a Valencia' -> plan_route, muestra desvío de la herramienta y amenities como servicios indicados, no comodidad garantizada ni pocas paradas; "
        "'No quiero cargar en sitios solitarios de noche' -> pregunta ubicación/ruta; 'Estoy en Valencia centro' después -> llama search_destination_chargers, muestra puntos autorizados y explica que no validas seguridad, iluminación, afluencia ni actividad en vivo; "
        "'Mi coche carga máximo a 100 kW, no necesito ultrarrápidos' -> usa preferences.max_useful_power_kw=100 y, si muestras estaciones de más de 100 kW, di antes que el coche no aprovechará más de 100 kW y que la potencia superior no se premia.\n"
    )
    catalog_instructions = (
        "Catálogo A2UI permitido por propósito, no por reglas rígidas de intención:\n"
        "AssistantMessage texto breve para contexto conversacional como origen, destino, batería, margen, reserva e incertidumbre concreta; RouteCorridorCard solo plan_route y debe combinar mapa compacto, ruta y estaciones cercanas al corredor sin declarar una estación recomendada; "
        "StationPreviewCard/StationList solo estaciones de carga respaldadas por herramientas; en esos bloques name/stationName debe ser una estación verificable; address puede ser dirección/zona de herramienta. AssistantMessage explica incertidumbre concreta; "
        "Para preferencias de precio, muestra pricePerKwhEur verificado y no estimado en StationPreviewCard o StationList; no inventes ahorro, coste total ni comparativas si la herramienta no trae datos suficientes. AssistantMessage muestra la ubicación/zona resuelta cuando aporte contexto; StationPreviewCard muestra estación concreta con distanceKm, powerKw, pricePerKwhEur, availableEvses, connectorTypes, lat/lon cuando vengan de herramienta; no muestres pricePerKwhEur si priceIsEstimated es true. "
        "si quieres mostrar alternativas, usa StationList solo cuando aporte una decisión distinta; si hay riesgo o límite crítico, explícalo en AssistantMessage antes de la card. "
        "RouteCorridorCard es el único componente de ruta/mapa: úsalo con routeGeometry GeoJSON LineString de proveedor, origin/destination con coordenadas de herramienta, stations de herramienta, corridorRadiusKm y geometryPrecision='provider'. "
        "Si no tienes geometría de proveedor, usa geometryPrecision='schematic' o no muestres mapa; no inventes coordenadas ni geometría. "
        "ActionButtons usa event para backend/agente, functionCall.openUrl para abrir mapas, o disabled con reason; cuando pertenezcan a una recomendación colócalos inmediatamente después de esa card para que se rendericen como acciones de la misma unidad; "
        "Usa labels de acción concretos: 'Elegir esta parada' o 'Elegir este punto de carga' para seleccionar una recomendación, 'Abrir ruta' para navegación openUrl y 'Buscar otra opción' para alternativas; evita labels vagos como 'Confirmar' o acciones de selección genéricas. No ofrezcas reservar, pagar ni comprar desde ActionButtons.\n"
        "AssistantMessage pide datos críticos en texto libre; "
        "PositionRequestCard pide posición actual/manual del conductor; en la copia inicial evita mencionar coordenadas salvo que el usuario ya las haya ofrecido, porque la alternativa manual debe sentirse equivalente y no técnica; "
        "PreferenceChips solo para correcciones o preferencias explícitas, siempre con props.title contextual; "
        "ErrorFallbackCard reservado.\n"
        "tool_call no es un componente A2UI y nunca debe aparecer dentro de blocks; si necesitas una herramienta, devuelve type=tool_call como objeto raíz.\n"
    )
    output_instructions = (
        "Devuelve un único objeto JSON compacto, sin markdown, sin texto exterior y sin bloques de código. Formas válidas:\n"
        '{"type":"tool_call","intent":"...","confidence":0.0,"tool":"search_destination_chargers","args":{...},'
        '"rationale":"metadata interna breve"}\n'
        '{"type":"final","intent":"...","confidence":0.0,"blocks":[{"id":"...","type":"AssistantMessage","version":1,'
        '"props":{"text":"..."}}],"metadata":{"rationale":"metadata interna breve"}}\n'
        "intent, confidence, rationale y metadata son opcionales y no se muestran al usuario. "
        f"Tipos A2UI permitidos: {', '.join(sorted(A2UI_COMPONENT_TYPES))}. "
        "Dentro de blocks no uses type=tool_call, component=tool_call ni objetos con tool/args; eso solo es válido como objeto raíz. "
        "Para ActionButtons usa actions con event {name, context} o functionCall {call:'openUrl', args:{url:'https://...'}}; "
        "no uses handlers arbitrarios. "
        "No inventes disponibilidad, precios, estaciones, coordenadas ni estado del vehículo. "
        "No uses ActionButtons para sustituir una herramienta de búsqueda cuando ya tienes ciudad/POI suficiente. "
        "No llames plan_route con coordenadas vacías o 0,0; si faltan origen/destino reales, usa AssistantMessage. "
        "No devuelvas RouteCorridorCard ni distancia/duración de ruta si no tienes resultado de plan_route. "
        "No afirmes paradas/puntos de carga disponibles/encontrados ni incluyas listas vacías como resultado si no llamaste una herramienta de búsqueda/ruta. "
        "No afirmes paradas, puntos de carga o rutas si no vienen de herramientas, datos autorizados o texto explícito del usuario. "
        "No respondas con 'buscaré', 'voy a buscar' o 'puedo buscar' cuando ya tienes ciudad/POI suficiente para usar una herramienta; en ese caso devuelve type=tool_call. "
        "Si faltan datos críticos, pregunta. Si el proveedor o los datos autorizados no permiten responder, falla de forma explícita. "
        "Puedes pedir otra herramienta si falta un dato necesario, pero no repitas una llamada ya hecha con los mismos argumentos. "
        "Elige los bloques A2UI que aporten claridad al usuario según la conversación completa. "
        "Cuando tengas resultados de herramientas con estaciones, rutas o métricas, prefiere bloques estructurados para esos hechos verificables "
        "y usa AssistantMessage solo como introducción breve, cierre o aclaración de límites. "
        "Una respuesta simple también es válida si evita sobreafirmar o si no hay datos estructurados suficientes."
    )
    station_result_instructions = station_search_result_prompt(message, tool_history)
    service_result_instructions = requested_service_result_prompt(message, tool_history)
    if repair_issues:
        return (
            "Eres el agente conversacional de Kalmio para planificación EV. Tu respuesta anterior fue rechazada "
            "por el contrato de seguridad/datos A2UI o por un guardrail de herramientas. No pidas herramientas en esta reparación. "
            "Devuelve solo type=final con blocks A2UI válidos; puedes simplificar la UI si no puedes demostrar los datos. "
            "Problemas detectados:\n"
            f"{json.dumps(repair_issues, ensure_ascii=False)}\n"
            "Usa solo datos del historial de herramientas; no inventes estaciones, precios, disponibilidad, coordenadas ni estado del vehículo.\n"
            "Si el historial ya contiene estaciones trazables de herramienta, no elimines todas las StationPreviewCard/StationList "
            "solo porque falte una advertencia de servicios, precio, disponibilidad o margen: conserva al menos una estación "
            "válida y añade el aviso visible que falta.\n"
            f"{behavior_instructions}"
            f"{catalog_instructions}"
            f"{output_instructions}\n"
            "Contexto dinámico del turno:\n"
            f"Usuario: {message}\n"
            f"Historial de herramientas compactado: {json.dumps(prompt_tool_history, ensure_ascii=False)}\n"
            f"Bloques rechazados compactados: {json.dumps(prompt_candidate_blocks, ensure_ascii=False)}\n"
            f"{station_result_instructions}"
            f"{service_result_instructions}"
        )
    if tool_history:
        return (
            "Eres el agente conversacional de Kalmio para planificación EV. Ya se ejecutaron estas herramientas "
            "internas de Django. Decide si necesitas otra herramienta permitida o si ya puedes devolver type=final con A2UI.\n"
            f"{tool_instructions}"
            f"{behavior_instructions}"
            f"{catalog_instructions}"
            f"{output_instructions}\n"
            "Contexto dinámico del turno:\n"
            f"Usuario: {message}\n"
            f"Historial de herramientas compactado: {json.dumps(prompt_tool_history, ensure_ascii=False)}\n"
            f"{station_result_instructions}"
            f"{service_result_instructions}"
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

def station_search_result_prompt(message: str, tool_history: list[dict[str, Any]]) -> str:
    result = latest_station_search_result(tool_history)
    if not result:
        return ""
    stops = station_search_result_stops(result)
    if not stops:
        return ""
    tool_name = result.get("tool") or "search_destination_chargers/plan_route"
    destination_context = ""
    if message_mentions_destination_or_stay(normalize(message)) and isinstance(result.get("location"), dict):
        destination_context = (
            "Como estos resultados vienen de una búsqueda de destino/estancia, explica en AssistantMessage la "
            "ubicación usada antes de las estaciones. Si la ubicación es ciudad/zona aproximada, di que es una "
            "aproximación y pide dirección, zona exacta o coordenadas para refinar.\n"
        )
    return (
        f"Ya tienes resultados de {tool_name} en el historial. No repitas la misma búsqueda ni pidas "
        "otra herramienta salvo que cambie materialmente ubicación, ruta, conector o preferencia. Devuelve type=final "
        "con AssistantMessage y StationPreviewCard/StationList usando solo esos resultados.\n"
        f"{destination_context}"
    )


def requested_service_result_prompt(message: str, tool_history: list[dict[str, Any]]) -> str:
    requested = requested_service_codes(message)
    if not requested:
        return ""
    result = latest_station_search_result(tool_history)
    if not result:
        return ""
    stops = station_search_result_stops(result)
    if not stops or any(stop_has_requested_service(stop, requested) for stop in stops):
        return ""
    return (
        "Dato crítico de servicios: el usuario pidió baños/cafetería/restaurante, pero los resultados de herramienta "
        "no traen esos amenities. En la respuesta final muestra los cargadores, pero di de forma visible que "
        "baños/cafetería/restaurante no están verificados en esos resultados; no los inventes ni los formules como cercanos.\n"
    )


def decode_agent_json(raw_output: str, stdout_output: str = "") -> Any:
    for candidate in (raw_output, stdout_output):
        payload = try_decode_json_candidate(candidate)
        if payload is not None:
            return payload
    raise AgentResponseError("El agente no devolvió JSON válido.")


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


def parse_agent_decision(payload: dict[str, Any]) -> dict[str, Any]:
    decision_type = str(payload.get("type") or payload.get("kind") or payload.get("action") or "").strip()
    if not decision_type and isinstance(payload.get("blocks"), list):
        decision_type = "final"
    if decision_type in {"final", "ask"}:
        blocks = payload.get("blocks")
        if not isinstance(blocks, list):
            raise AgentResponseError("El agente no devolvió bloques para la respuesta final.")
        misplaced_tool_call = tool_call_from_misplaced_block(blocks)
        if misplaced_tool_call:
            return misplaced_tool_call
        return {"type": "final", "blocks": blocks}
    if decision_type in {"tool_call", "tool"} or isinstance(payload.get("tool_call"), dict):
        tool_payload = payload.get("tool_call") if isinstance(payload.get("tool_call"), dict) else payload
        tool = str(tool_payload.get("tool") or tool_payload.get("name") or "").strip()
        args = tool_payload.get("args") if isinstance(tool_payload.get("args"), dict) else {}
        if not tool:
            raise AgentResponseError("El agente pidió una herramienta sin nombre.")
        return {"type": "tool_call", "tool": tool, "args": args}
    raise AgentResponseError("El agente devolvió una decisión no soportada.")


def tool_call_from_misplaced_block(blocks: list[Any]) -> dict[str, Any] | None:
    for item in blocks:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or item.get("component") or "").strip() not in {"tool_call", "tool"}:
            continue
        tool_payload = item.get("props") if isinstance(item.get("props"), dict) else item
        tool = str(tool_payload.get("tool") or tool_payload.get("name") or "").strip()
        args = tool_payload.get("args") if isinstance(tool_payload.get("args"), dict) else {}
        if not tool:
            raise AgentResponseError("El agente puso una llamada de herramienta en blocks sin nombre de herramienta.")
        return {"type": "tool_call", "tool": tool, "args": args}
    return None


def station_props_from_result(value: dict[str, Any]) -> dict[str, Any]:
    aliases = station_value_aliases(value) if isinstance(value, dict) else {}
    name = (
        display_text(value.get("stationName") or value.get("name"), "Estación por confirmar")
        if isinstance(value, dict)
        else "Estación por confirmar"
    )
    props: dict[str, Any] = {
        "name": name,
        "stationName": name,
    }
    for source in (
        "powerKw",
        "distanceKm",
        "detourMin",
        "confidence",
        "lat",
        "lon",
        "availableEvses",
        "totalEvses",
        "connectorTypes",
        "pricePerKwhEur",
        "currency",
        "priceIsEstimated",
    ):
        if source in aliases:
            props[source] = aliases[source]
    if isinstance(value, dict):
        for source, target in (
            ("address", "address"),
            ("distance_km", "distanceKm"),
            ("power_kw", "powerKw"),
            ("max_power_kw", "powerKw"),
            ("available_evses", "availableEvses"),
            ("available_connectors", "availableEvses"),
            ("connector_count", "totalEvses"),
            ("connector_types", "connectorTypes"),
            ("price_eur_kwh", "pricePerKwhEur"),
            ("price_per_kwh", "pricePerKwhEur"),
            ("price_is_estimated", "priceIsEstimated"),
        ):
            if target not in props and source in value:
                props[target] = value[source]
        amenities = value.get("amenities")
        if isinstance(amenities, list):
            props["amenities"] = amenities
    if props.get("priceIsEstimated") is True:
        props.pop("pricePerKwhEur", None)
    return props


def station_props_from_nearby(value: Any) -> dict[str, Any]:
    station = value.station
    props = {
        "name": station.name,
        "stationName": station.name,
        "address": station.address,
        "powerKw": value.max_power_kw,
        "distanceKm": value.distance_km,
        "connectorTypes": value.connector_types,
        "availableEvses": value.available_evses,
        "lat": float(station.latitude),
        "lon": float(station.longitude),
        "amenities": station.amenities,
    }
    tariff = station.tariffs.first()
    if tariff:
        props["priceIsEstimated"] = tariff.is_estimated
        if not tariff.is_estimated:
            props["pricePerKwhEur"] = float(tariff.price_per_kwh)
            props["currency"] = tariff.currency
    return props


def blocks_from_tool_result(tool_result: dict[str, Any], message: str = "") -> list[dict]:
    tool = tool_result.get("tool")
    if not tool_result.get("ok"):
        return [
            block(
                f"assistant-{uuid4().hex[:10]}",
                "AssistantMessage",
                {"text": user_facing_failure_text(str(tool_result.get("error") or "La herramienta no pudo devolver datos reales."))},
            )
        ]
    if tool == "search_destination_chargers":
        location = tool_result.get("location") if isinstance(tool_result.get("location"), dict) else {}
        label = location_label(location)
        stations = tool_result.get("stops") if isinstance(tool_result.get("stops"), list) else []
        if parse_intent(message).is_urgent_request:
            nearest = stations[0] if stations and isinstance(stations[0], dict) else {}
            return [
                block(
                    f"assistant-{uuid4().hex[:10]}",
                    "AssistantMessage",
                    {
                        "text": (
                            f"Uso {label} como ubicación aproximada para esta búsqueda urgente. "
                            "Muestro paradas con puntos de carga autorizados cerca de esa zona. "
                            "Confirma acceso final, tarifa y disponibilidad antes de depender de ellas."
                        ),
                    },
                ),
                block(
                    f"station-{uuid4().hex[:10]}",
                    "StationPreviewCard",
                    {"title": "Estación cercana", **station_props_from_result(nearest)},
                ),
                block(
                    f"stations-{uuid4().hex[:10]}",
                    "StationList",
                    {
                        "title": "Otras estaciones cercanas",
                        "stations": [station_props_from_result(station) for station in stations],
                    },
                ),
            ]
        return [
            block(
                f"assistant-{uuid4().hex[:10]}",
                "AssistantMessage",
                {
                    "text": (
                        f"Uso {label} como ubicación aproximada para la búsqueda. "
                        "Muestro solo paradas respaldadas por puntos de carga autorizados devueltos por la herramienta interna. "
                        "Confirma acceso final, tarifa y disponibilidad antes de depender de ellas."
                    ),
                },
            ),
            block(
                f"stations-{uuid4().hex[:10]}",
                "StationList",
                {
                    "title": "Estaciones cerca del destino",
                    "stations": [station_props_from_result(station) for station in stations],
                },
            ),
        ]
    if tool == "plan_route":
        recommendation = tool_result.get("recommendation") if isinstance(tool_result.get("recommendation"), dict) else {}
        alternatives = tool_result.get("alternatives") if isinstance(tool_result.get("alternatives"), list) else []
        return [
            block(
                f"route-{uuid4().hex[:10]}",
                "RouteCorridorCard",
                {
                    "distanceKm": tool_result.get("distanceKm"),
                    "durationMin": tool_result.get("durationMin"),
                    "energyKwh": tool_result.get("energyKwh"),
                    "arrivalBattery": tool_result.get("arrivalBattery"),
                    "origin": tool_result.get("origin"),
                    "destination": tool_result.get("destination"),
                    "stations": [
                        station_props_from_result(station)
                        for station in [recommendation, *alternatives]
                        if isinstance(station, dict) and station
                    ],
                    "routeGeometry": tool_result.get("routeGeometry"),
                    "corridorRadiusKm": tool_result.get("corridorRadiusKm"),
                    "geometryPrecision": "provider" if tool_result.get("routeGeometry") else "unknown",
                    "source": "plan_route",
                },
            ),
        ]
    return [block(f"assistant-{uuid4().hex[:10]}", "AssistantMessage", {"text": "Herramienta ejecutada."})]


def fallback_from_tool_history(tool_history: list[dict[str, Any]], reason: str, message: str = "") -> list[dict]:
    latest_result = latest_tool_result(tool_history)
    if latest_result and latest_result.get("ok"):
        if is_renderable_tool_result(latest_result):
            return blocks_from_tool_result(latest_result, message)
        return [
            block(
                f"assistant-{uuid4().hex[:10]}",
                "AssistantMessage",
                {
                    "text": (
                        "Muestro solo datos validados por las herramientas disponibles y marco lo que no puedo confirmar. "
                        f"{user_facing_failure_text(reason)}"
                    )
                },
            ),
            *blocks_from_tool_result(latest_result, message),
        ]
    return [
        block(
            f"assistant-{uuid4().hex[:10]}",
            "AssistantMessage",
            {
                "text": (
                    "No he podido cerrar una respuesta fiable con los datos validados. "
                    "No voy a completar estaciones, coordenadas, precios ni disponibilidad por mi cuenta. "
                    f"{user_facing_failure_text(reason)}"
                )
            },
        ),
    ]


def is_renderable_tool_result(tool_result: dict[str, Any]) -> bool:
    return str(tool_result.get("tool") or "") in {"search_destination_chargers", "plan_route"}


def user_facing_failure_text(reason: str) -> str:
    normalized = normalize(reason)
    if "herramienta no permitida" in normalized:
        return "No puedo hacer esa acción desde el chat. Puedo ayudarte a calcular una ruta, buscar paradas con puntos de carga autorizados o pedir los datos que falten."
    if "un solo conector" in normalized or "un solo puesto" in normalized or "multi-puesto" in normalized:
        return (
            "He usado solo puntos de carga autorizados y priorizo estaciones con más de un puesto registrado cuando el dato existe. "
            "Confirma acceso final, conectores físicos y disponibilidad antes de depender de ellas."
        )
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
    user_context = user_conversation_text(message, history_blocks or [])
    facts["vehicle"].update(parse_vehicle_fields(user_context))
    explicit_coordinates = coordinates_from_text(user_context)
    issues: list[str] = []

    for item in blocks:
        if not isinstance(item, dict):
            issues.append("Todos los bloques A2UI deben ser objetos.")
            continue
        block_type = item.get("type")
        props = item.get("props") if isinstance(item.get("props"), dict) else {}

        if block_type == "StationList":
            issues.extend(station_list_contract_issues(props, facts))
        elif block_type == "AssistantMessage":
            issues.extend(assistant_message_contract_issues(props, facts))
        elif block_type in STATION_CARD_TYPES:
            station_name = props.get("name") or props.get("stationName")
            issues.extend(required_station_reference_contract_issues(f"{block_type}.name", station_name, facts))
            issues.extend(station_reference_contract_issues(f"{block_type}.name", station_name, facts))
            issues.extend(station_metric_contract_issues(str(block_type), props, facts))
        elif block_type == "RouteCorridorCard":
            issues.extend(route_summary_contract_issues(props, facts, "RouteCorridorCard"))
            issues.extend(map_preview_contract_issues(props, facts, explicit_coordinates, "RouteCorridorCard"))
        elif block_type == "ActionButtons":
            issues.extend(action_buttons_contract_issues(props, facts, explicit_coordinates))
    issues.extend(factual_charger_copy_contract_issues(blocks, facts))
    issues.extend(destination_city_approximation_contract_issues(blocks, tool_history, user_context, facts))
    issues.extend(approximate_location_contract_issues(blocks, facts))
    issues.extend(comfort_copy_contract_issues(blocks))
    issues.extend(night_safety_copy_contract_issues(blocks, user_context))
    issues.extend(night_safety_warning_order_contract_issues(blocks, user_context))
    issues.extend(requested_service_data_contract_issues(blocks, tool_history, user_context, facts))
    issues.extend(default_reserve_copy_contract_issues(blocks, tool_history, user_context, facts))
    issues.extend(unvalidated_route_margin_copy_contract_issues(blocks, tool_history, facts))
    issues.extend(chargers_only_warning_order_contract_issues(blocks, tool_history, facts))
    issues.extend(max_useful_power_copy_contract_issues(blocks, tool_history, facts))
    issues.extend(few_stops_copy_context_contract_issues(blocks, user_context))
    issues.extend(departure_battery_copy_contract_issues(blocks, user_context))
    issues.extend(future_trip_volatility_copy_contract_issues(blocks, user_context))
    issues.extend(cheap_route_reserve_context_contract_issues(blocks, user_context))
    issues.extend(price_preference_context_contract_issues(blocks, user_context, tool_history, facts))
    issues.extend(minimum_charge_context_contract_issues(blocks, user_context))
    issues.extend(single_connector_preference_contract_issues(blocks, tool_history, user_context, facts))
    issues.extend(action_button_sequence_contract_issues(blocks))
    return dedupe_preserve_order(issues)


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


def tool_fact_index(tool_history: list[dict[str, Any]], history_blocks: list[dict] | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "stations": {},
        "locations": [],
        "approximateLocations": [],
        "routes": [],
        "routePreferences": [],
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
            route = dict(result)
            preferences = args.get("preferences") if isinstance(args.get("preferences"), dict) else {}
            if preferences:
                route["preferences"] = preferences
                facts["routePreferences"].append(preferences)
            facts["routes"].append(route)
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
        elif block_type == "StationList":
            stations = props.get("stations") if isinstance(props.get("stations"), list) else props.get("stops")
            if isinstance(stations, list):
                for station in stations:
                    add_station_fact(facts, station)
        elif block_type in STATION_CARD_TYPES:
            add_station_fact(facts, props)
        elif block_type == "RouteCorridorCard":
            facts["routes"].append(props)
            for key in ("origin", "destination"):
                add_location_fact(facts, props.get(key))
            stations = props.get("stations")
            if isinstance(stations, list):
                for station in stations:
                    add_station_fact(facts, station)
        elif block_type == "ActionButtons":
            actions = props.get("actions")
            if isinstance(actions, list):
                for action in actions:
                    add_action_context_facts(facts, action)


def add_action_context_facts(facts: dict[str, Any], action: Any) -> None:
    if not isinstance(action, dict):
        return
    event = action.get("event") if isinstance(action.get("event"), dict) else {}
    context = event.get("context") if isinstance(event.get("context"), dict) else {}
    add_location_fact(facts, context.get("location"))
    previous_search = context.get("previous_search") if isinstance(context.get("previous_search"), dict) else {}
    add_location_fact(facts, previous_search.get("location"))


def add_station_fact(facts: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    name = display_text(value.get("name") or value.get("stationName"), "")
    if not name:
        return
    key = station_key(name)
    current = facts["stations"].setdefault(key, {"name": name})
    normalized_values = station_value_aliases(value)
    for field in (
        "powerKw",
        "distanceKm",
        "detourMin",
        "confidence",
        "lat",
        "lon",
        "availableEvses",
        "totalEvses",
        "connectorTypes",
        "pricePerKwhEur",
        "currency",
        "priceIsEstimated",
        "amenities",
        "address",
    ):
        if field in normalized_values:
            current[field] = normalized_values.get(field)
        elif field in value:
            current[field] = value.get(field)


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
        "totalEvses": ("totalEvses", "total_evses", "connector_count"),
        "connectorTypes": ("connectorTypes", "connector_types"),
        "pricePerKwhEur": ("pricePerKwhEur", "pricePerKwh", "price_eur_kwh", "price_per_kwh"),
        "currency": ("currency",),
        "priceIsEstimated": ("priceIsEstimated", "price_is_estimated", "tariff_is_estimated"),
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
    if location.get("isApproximate") is True:
        facts["approximateLocations"].append({"query": query_text, "resolvedLabel": label})
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


def comfort_copy_contract_issues(blocks: list[dict]) -> list[str]:
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    unsafe_terms = (
        "ideal",
        "seguro",
        "segura",
        "sitio perfecto",
        "sitio perfecta",
        "parada perfecta",
        "parada perfecto",
        "buenos servicios",
        "mejores servicios",
        "sitio mas comodo",
        "sitio más cómodo",
        "parada mas comoda",
        "parada más cómoda",
        "perfecto para ninos",
        "perfecta para ninos",
        "apto para ninos",
        "apta para ninos",
        "child-friendly",
        "entretener a los ninos",
    )
    if any(visible_text_has_term(visible_text, term) for term in unsafe_terms):
        return [
            "La respuesta hace un claim de seguridad/comodidad para niños no respaldado por datos. "
            "Debe formular servicios solo como datos indicados o comodidad potencial, sin ideal/seguro/apto/entretener."
        ]
    if claims_service_proximity(visible_text):
        if is_service_location_clarifying_copy(blocks, visible_text) or mentions_unverified_service_data(visible_text):
            return []
        return [
            "La respuesta afirma que un servicio está cerca sin dato verificable de proximidad. "
            "Debe decir servicios indicados o comodidad potencial y pedir confirmación."
        ]
    return []


def claims_service_proximity(visible_text: str) -> bool:
    amenity_terms = ("cafeteria", "cafe", "supermercado", "restaurante", "bano", "banos")
    proximity_terms = ("cerca", "cercano", "cercana", "cercanos", "cercanas")
    nearby_words = r"(?:[^\w.!?;:]+\w+){0,6}[^\w.!?;:]+"
    for amenity in amenity_terms:
        for proximity in proximity_terms:
            if re.search(rf"\b{re.escape(amenity)}\b{nearby_words}\b{re.escape(proximity)}\b", visible_text):
                return True
            if re.search(rf"\b{re.escape(proximity)}\b{nearby_words}\b{re.escape(amenity)}\b", visible_text):
                return True
    return False


def night_safety_copy_contract_issues(blocks: list[dict], message: str) -> list[str]:
    if not user_message_mentions_night_safety(message):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    unsafe_terms = (
        "mas afluencia",
        "alta afluencia",
        "lugar concurrido",
        "zona concurrida",
        "senales de actividad",
        "señales de actividad",
        "mas actividad",
        "menos probable que sea solitario",
        "menos probable que sean solitarios",
        "no es solitario",
        "no son solitarios",
        "bien iluminado",
        "vigilado",
        "con vigilancia",
        "vigilancia presencial",
        "seguridad garantizada",
        "seguro de noche",
        "segura de noche",
    )
    if any(term in visible_text for term in unsafe_terms):
        return [
            "La respuesta hace una inferencia de seguridad nocturna no respaldada por datos. "
            "Puede decir que prioriza señales disponibles como dirección céntrica o puestos de carga, "
            "pero no puede usar afluencia, actividad, vigilancia o iluminación como criterio positivo; "
            "debe aclarar que no valida seguridad, iluminación ni afluencia en vivo."
        ]
    return []


def user_message_mentions_night_safety(message: str) -> bool:
    normalized = normalize(message)
    if not normalized:
        return False
    safety_terms = (
        "solitario",
        "solitaria",
        "solitarios",
        "solitarias",
        "de noche",
        "noche",
        "oscuro",
        "oscura",
        "seguridad",
        "seguro",
        "segura",
    )
    return any(visible_text_has_term(normalized, term) for term in safety_terms)


def night_safety_warning_order_contract_issues(blocks: list[dict], message: str) -> list[str]:
    if not user_message_mentions_night_safety(message):
        return []
    if first_block_index(blocks, "RouteCorridorCard") is None and first_block_index(blocks, "StationList") is None:
        return []
    early_text = normalize(" ".join(block_visible_text(block) for block in blocks_before_first_charge_option(blocks)))
    if (
        "no valida seguridad" in early_text
        or "no valido seguridad" in early_text
        or "no puedo validar seguridad" in early_text
        or "no valida seguridad ni entorno" in early_text
    ):
        return []
    return [
        "Si el usuario quiere evitar sitios solitarios de noche, el AssistantMessage inicial debe explicar "
        "antes de StationList que Kalmio no valida seguridad, iluminación ni afluencia en vivo."
    ]


def is_service_location_clarifying_copy(blocks: list[dict], visible_text: str) -> bool:
    has_charge_result_block = any(block.get("type") in STATION_CARD_TYPES or block.get("type") == "StationList" for block in blocks)
    if has_charge_result_block:
        return False
    asks_for_location = any(
        phrase in visible_text
        for phrase in (
            "necesito saber donde",
            "necesito saber donde la quieres",
            "donde la quieres",
            "donde estas",
            "donde estás",
            "ciudad concreta",
            "ruta que tengas",
            "ubicacion actual",
            "ubicación actual",
            "cerca de que lugar",
            "cerca de qué lugar",
        )
    )
    return asks_for_location


def requested_service_data_contract_issues(
    blocks: list[dict],
    tool_history: list[dict[str, Any]],
    message: str,
    facts: dict[str, Any],
) -> list[str]:
    requested = requested_service_codes(message)
    if not requested:
        return []
    stops = latest_station_candidates(tool_history, facts)
    if not stops:
        return []
    if any(stop_has_requested_service(stop, requested) for stop in stops):
        return []
    if not any(block.get("type") in STATION_CARD_TYPES or block.get("type") == "StationList" for block in blocks):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if mentions_unverified_service_data(visible_text):
        return []
    return [
        "El usuario pidió servicios como baños/cafetería/restaurante, pero la herramienta no los trazó en estos resultados. "
        "La respuesta debe decir que esos servicios no están verificados en los cargadores mostrados."
    ]


def requested_service_codes(message: str) -> set[str]:
    normalized = normalize(message)
    requested: set[str] = set()
    if any(visible_text_has_term(normalized, term) for term in ("bano", "banos", "aseo", "aseos")):
        requested.update({"BATHROOM", "TOILETS"})
    if any(visible_text_has_term(normalized, term) for term in ("cafeteria", "cafe")):
        requested.add("CAFE")
    if any(visible_text_has_term(normalized, term) for term in ("restaurante", "comer")):
        requested.add("RESTAURANT")
    return requested


def latest_station_search_result(tool_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(tool_history):
        result = entry.get("result")
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        tool_name = result.get("tool") or (entry.get("call") or {}).get("tool")
        if tool_name in {"search_destination_chargers", "plan_route"}:
            return result
    return None


def station_search_result_stops(result: dict[str, Any]) -> list[dict[str, Any]]:
    stops: list[dict[str, Any]] = []
    for key in ("stops", "alternatives"):
        value = result.get(key)
        if isinstance(value, list):
            stops.extend(item for item in value if isinstance(item, dict))
    recommendation = result.get("recommendation")
    if isinstance(recommendation, dict):
        stops.append(recommendation)
    return stops


def latest_station_candidates(tool_history: list[dict[str, Any]], facts: dict[str, Any]) -> list[dict[str, Any]]:
    result = latest_station_search_result(tool_history)
    if result:
        stops = station_search_result_stops(result)
        if stops:
            return stops
    stations = facts.get("stations") if isinstance(facts.get("stations"), dict) else {}
    return [station for station in stations.values() if isinstance(station, dict)]


def stop_has_requested_service(stop: dict[str, Any], requested: set[str]) -> bool:
    amenities = stop.get("amenities")
    if not isinstance(amenities, list):
        return False
    codes = {normalize(str(item)).upper().replace("-", "_").replace(" ", "_") for item in amenities}
    return bool(codes & requested)


def mentions_unverified_service_data(visible_text: str) -> bool:
    return any(
        phrase in visible_text
        for phrase in (
            "no estan verificados",
            "no están verificados",
            "no esta verificado",
            "no está verificado",
            "no verificados",
            "no verificado",
            "no tengo datos de servicios",
            "sin datos de servicios",
            "no hay datos de banos",
            "no hay datos de cafeteria",
            "no aparecen banos",
            "no aparece cafeteria",
        )
    )


def single_connector_preference_contract_issues(
    blocks: list[dict],
    tool_history: list[dict[str, Any]],
    message: str,
    facts: dict[str, Any],
) -> list[str]:
    if not user_message_avoids_single_connector(message):
        return []

    candidates = latest_station_candidates(tool_history, facts)
    if not candidates:
        return []

    issues: list[str] = []
    has_station_block = any(block.get("type") in STATION_CARD_TYPES or block.get("type") == "StationList" for block in blocks)
    if not has_station_block:
        issues.append(
            "El usuario pidio evitar cargadores con un solo conector/puesto y la herramienta encontro cargadores. "
            "La respuesta debe mostrar StationPreviewCard o StationList con estaciones trazables y explicar puestos/conectores registrados."
        )

    primary = first_block_props(blocks, "StationPreviewCard") or first_block_props(blocks, "StationDetailCard")
    primary_source = station_candidate_for_block(primary, candidates)
    primary_count = traced_evse_or_connector_count(primary_source or primary)
    if (
        primary
        and primary_count is not None
        and primary_count <= 1
        and any((traced_evse_or_connector_count(candidate) or 0) > 1 for candidate in candidates)
    ):
        issues.append(
            "El usuario pidio evitar cargadores con un solo conector/EVSE, pero la parada primaria tiene "
            "solo 1 puesto/conector registrado y hay alternativas con mas de 1. La primaria debe usar una opcion multi-puesto registrada."
        )

    visible_text = normalize(
        " ".join(
            block_visible_text(block)
            for block in blocks
            if isinstance(block, dict) and block.get("type") != "UserMessage"
        )
    )
    if claims_connector_count_without_connector_count(visible_text, candidates):
        issues.append(
            "La respuesta presenta availableEvses como conteo de conectores. Debe decir puestos de carga registrados "
            "o puntos de carga importados, y reservar 'conectores' para connectorTypes."
        )
    if not any(
        visible_text_has_term(visible_text, term)
        for term in ("puesto", "puestos", "conector", "conectores", "confirma", "confirmar")
    ):
        issues.append(
            "El usuario pidio evitar cargadores con un solo conector/puesto. La respuesta visible debe reconocer "
            "esa preferencia hablando de puestos de carga registrados o conectores físicos, y pedir confirmar acceso/datos finales."
        )
    return issues


def user_message_avoids_single_connector(message: str) -> bool:
    normalized = normalize(message)
    return any(
        phrase in normalized
        for phrase in (
            "un solo conector",
            "solo conector",
            "single connector",
            "evita cargadores con un conector",
            "evitar cargadores con un conector",
        )
    )


def station_candidates_from_tool_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    recommendation = result.get("recommendation")
    if isinstance(recommendation, dict):
        candidates.append(recommendation)
    stops = result.get("stops")
    if isinstance(stops, list):
        candidates.extend(stop for stop in stops if isinstance(stop, dict))
    alternatives = result.get("alternatives")
    if isinstance(alternatives, list):
        candidates.extend(stop for stop in alternatives if isinstance(stop, dict))
    return candidates


def first_block_props(blocks: list[dict], block_type: str) -> dict[str, Any]:
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == block_type and isinstance(block.get("props"), dict):
            return block["props"]
    return {}


def station_candidate_for_block(props: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    name = station_key(display_text(props.get("name") or props.get("stationName"), ""))
    if not name:
        return None
    for candidate in candidates:
        candidate_name = station_key(display_text(candidate.get("name") or candidate.get("stationName"), ""))
        if candidate_name == name:
            return candidate
    return None


def traced_evse_or_connector_count(value: dict[str, Any] | None) -> float | None:
    if not isinstance(value, dict):
        return None
    aliases = station_value_aliases(value)
    total_evses = optional_float(aliases.get("totalEvses"))
    if total_evses is not None:
        return total_evses
    return optional_float(aliases.get("availableEvses"))


def claims_connector_count_without_connector_count(visible_text: str, candidates: list[dict[str, Any]]) -> bool:
    if not visible_text:
        return False
    has_total_evses = any(optional_float(station_value_aliases(candidate).get("totalEvses")) is not None for candidate in candidates)
    if has_total_evses:
        return False
    return any(
        phrase in visible_text
        for phrase in (
            "al menos 2 conectores",
            "al menos dos conectores",
            "ninguno tiene un solo conector",
            "ninguna tiene un solo conector",
            "todos tienen mas de un conector",
            "todos tienen más de un conector",
        )
    )


def default_reserve_copy_contract_issues(
    blocks: list[dict],
    tool_history: list[dict[str, Any]],
    message: str,
    facts: dict[str, Any],
) -> list[str]:
    reserve = latest_plan_route_reserve(tool_history, facts)
    if reserve is None:
        return []
    normalized_message = normalize(message)
    reserve_label = integer_percent_label(reserve)
    if reserve_label is None or user_message_mentions_percent(normalized_message, reserve_label):
        return []

    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    attribution_terms = (
        f"{reserve_label}% que pides",
        f"{reserve_label}% que pediste",
        f"{reserve_label}% que has pedido",
        f"{reserve_label}% de reserva que pides",
        f"{reserve_label}% de reserva que pediste",
        f"{reserve_label}% indicado",
        f"{reserve_label}% que indicas",
        f"reserva del {reserve_label}% que pides",
        f"reserva de {reserve_label}% que pides",
        f"reserva del {reserve_label}% indicada",
        f"reserva de {reserve_label}% indicada",
    )
    if any(term in visible_text for term in attribution_terms):
        return [
            "La respuesta atribuye al usuario una reserva porcentual que no dijo. "
            "Debe presentarla como margen conservador por defecto o pedir el porcentaje deseado."
        ]
    return []


def unvalidated_route_margin_copy_contract_issues(
    blocks: list[dict],
    tool_history: list[dict[str, Any]],
    facts: dict[str, Any],
) -> list[str]:
    route = latest_plan_route_result(tool_history, facts)
    if not route:
        return []
    if not route_requires_unvalidated_arrival_warning(route):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    forbidden_terms = (
        "asegurar margen",
        "garantizar margen",
        "garantizar la reserva",
        "asegurar la reserva",
        "te ayudara a recuperar margen",
        "te ayudará a recuperar margen",
        "ayudara a recuperar margen operativo",
        "ayudará a recuperar margen operativo",
    )
    if any(term in visible_text for term in forbidden_terms):
        return [
            "La respuesta promete o da certeza sobre recuperar margen aunque la ruta no tiene consumo, energía ni batería de llegada validados. "
            "Debe decir que la parada puede ayudar a recuperar margen operativo no validado."
        ]
    return []


def chargers_only_warning_order_contract_issues(
    blocks: list[dict],
    tool_history: list[dict[str, Any]],
    facts: dict[str, Any],
) -> list[str]:
    route = latest_plan_route_result(tool_history, facts)
    if not route or not route_requires_unvalidated_arrival_warning(route):
        return []
    if first_block_index(blocks, "RouteCorridorCard") is None and first_block_index(blocks, "StationList") is None:
        return []
    early_text = normalize(" ".join(block_visible_text(block) for block in blocks_before_first_charge_option(blocks)))
    if (
        ("no puedo validar" in early_text or "no valido" in early_text)
        and ("bateria de llegada" in early_text or "batería de llegada" in early_text)
        and "reserva" in early_text
    ):
        return []
    return [
        "En una ruta chargers_only, el AssistantMessage inicial debe explicar antes de RouteCorridorCard o StationList "
        "que batería de llegada y reserva no están validadas."
    ]


def max_useful_power_copy_contract_issues(
    blocks: list[dict],
    tool_history: list[dict[str, Any]],
    facts: dict[str, Any],
) -> list[str]:
    cap = latest_plan_route_max_useful_power(tool_history, facts)
    if cap is None:
        return []

    over_cap_powers = [
        power for power in rendered_station_power_values(blocks)
        if power > cap + 0.1
    ]
    if not over_cap_powers:
        return []

    issues: list[str] = []
    pre_charge_text = normalize(" ".join(block_visible_text(block) for block in blocks_before_first_charge_option(blocks)))
    if not explains_max_useful_power_limit(pre_charge_text, cap):
        issues.append(
            "Cuando se muestra una estación por encima del máximo útil del coche, la respuesta debe explicar antes "
            "de la primera parada que esa potencia superior no se aprovecha/no se premia."
        )

    visible_text = normalize(
        " ".join(
            block_visible_text(block)
            for block in blocks
            if isinstance(block, dict) and block.get("type") != "UserMessage"
        )
    )
    if visible_text and claims_hard_power_filter(visible_text):
        issues.append(
            "La respuesta afirma que filtró o excluyó paradas por potencia útil, pero muestra una estación "
            "por encima del máximo útil del coche. Debe explicar que la potencia superior no se aprovecha/no se premia "
            "y no presentarla como ventaja ni como filtro duro."
        )
    return issues


def rendered_station_power_values(blocks: list[dict]) -> list[float]:
    powers: list[float] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        props = block.get("props") if isinstance(block.get("props"), dict) else {}
        if block.get("type") in STATION_CARD_TYPES:
            power = optional_float(station_value_aliases(props).get("powerKw"))
            if power is not None:
                powers.append(power)
            continue
        if block.get("type") != "StationList":
            continue
        stations = props.get("stations")
        if not isinstance(stations, list):
            continue
        for station in stations:
            if not isinstance(station, dict):
                continue
            power = optional_float(station_value_aliases(station).get("powerKw"))
            if power is not None:
                powers.append(power)
    return powers


def claims_hard_power_filter(visible_text: str) -> bool:
    return any(
        term in visible_text
        for term in (
            "he filtrado",
            "filtre",
            "filtré",
            "filtrado paradas",
            "filtrado cargadores",
            "filtre paradas",
            "filtré paradas",
            "excluido ultrarrapidos",
            "excluido ultrarrápidos",
            "descartado ultrarrapidos",
            "descartado ultrarrápidos",
            "solo paradas de hasta",
            "solo cargadores de hasta",
        )
    )


def explains_max_useful_power_limit(visible_text: str, cap: float) -> bool:
    if not visible_text:
        return False
    cap_label = integer_percent_label(cap) or f"{cap:g}"
    if f"{cap_label} kw" not in visible_text:
        return False
    return any(
        term in visible_text
        for term in (
            "no aprovechara",
            "no aprovechará",
            "no aprovecha",
            "no se aprovecha",
            "no se premia",
            "maximo util",
            "máximo útil",
            "por encima del maximo",
            "por encima del máximo",
        )
    )


def first_block_index(blocks: list[dict], block_type: str) -> int | None:
    for index, item in enumerate(blocks):
        if isinstance(item, dict) and item.get("type") == block_type:
            return index
    return None


def few_stops_copy_context_contract_issues(blocks: list[dict], message: str) -> list[str]:
    normalized_message = normalize(message)
    user_asked_few_stops = any(
        phrase in normalized_message
        for phrase in (
            "pocas veces",
            "pocas paradas",
            "parar poco",
            "parar pocas",
            "parar lo menos",
            "menos paradas",
        )
    )
    if user_asked_few_stops:
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    if any(
        phrase in visible_text
        for phrase in (
            "prefieres parar pocas veces",
            "prefieres pocas paradas",
            "si prefieres parar pocas veces",
            "para parar pocas veces",
        )
    ):
        return [
            "La respuesta introduce una preferencia de pocas paradas que el usuario no pidió. "
            "Debe mantener el foco en la preferencia real: desvío controlado y comodidad indicada."
        ]
    return []


def future_trip_volatility_copy_contract_issues(blocks: list[dict], message: str) -> list[str]:
    normalized_message = normalize(message)
    if not user_message_mentions_future_trip(normalized_message):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    has_route_or_charge_block = any(
        block.get("type") in {"RouteCorridorCard", "StationList"} or block.get("type") in STATION_CARD_TYPES
        for block in blocks
    )
    claims_route_or_stops = any(
        visible_text_has_term(visible_text, term)
        for term in ("parada", "paradas", "corredor")
    )
    if not has_route_or_charge_block and not claims_route_or_stops:
        return []
    availability_terms = (
        "disponibilidad",
        "ocupacion",
        "ocupación",
        "evses registrados",
        "conectores registrados",
    )
    access_terms = ("acceso", "accesos")
    tariff_terms = ("tarifa", "tarifas", "precio", "precios", "coste", "costes")
    if (
        any(visible_text_has_term(visible_text, term) for term in availability_terms)
        and any(visible_text_has_term(visible_text, term) for term in access_terms)
        and any(visible_text_has_term(visible_text, term) for term in tariff_terms)
    ):
        early_text = normalize(" ".join(block_visible_text(block) for block in blocks_before_first_charge_option(blocks)))
        if early_text and (
            any(visible_text_has_term(early_text, term) for term in availability_terms)
            and any(visible_text_has_term(early_text, term) for term in access_terms)
            and any(visible_text_has_term(early_text, term) for term in tariff_terms)
        ):
            return []
        if not any(block.get("type") in STATION_CARD_TYPES or block.get("type") == "StationList" for block in blocks):
            return []
        return [
            "El usuario indica un viaje futuro y la advertencia de disponibilidad, acceso y tarifas debe aparecer "
            "antes de StationPreviewCard/StationList o en el AssistantMessage inicial."
        ]
    return [
        "El usuario indica un viaje futuro y la respuesta debe advertir visiblemente que disponibilidad, "
        "acceso y tarifas pueden cambiar antes del viaje."
    ]


def departure_battery_copy_contract_issues(blocks: list[dict], message: str) -> list[str]:
    departure_percents = departure_battery_percent_labels(normalize(message))
    if not departure_percents:
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    for percent in departure_percents:
        arrival_terms = (
            f"llegas con el {percent}%",
            f"llegas con {percent}%",
            f"llegar con el {percent}%",
            f"llegar con {percent}%",
            f"llegada con el {percent}%",
            f"llegada con {percent}%",
        )
        if any(term in visible_text for term in arrival_terms):
            return [
                f"La respuesta trata el {percent}% de salida como porcentaje de llegada o reserva. "
                "Debe decir que el usuario sale con ese porcentaje y que la batería de llegada no está validada."
            ]
    return []


def cheap_route_reserve_context_contract_issues(blocks: list[dict], message: str) -> list[str]:
    normalized_message = normalize(message)
    if not cheap_route_with_reserve_request(normalized_message):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    missing: list[str] = []
    if not any(term in visible_text for term in ("origen", "desde donde", "sales", "salida")):
        missing.append("origen")
    if not any(term in visible_text for term in ("destino", "adonde", "a donde")):
        missing.append("destino")
    if "bateria" not in visible_text:
        missing.append("batería actual")
    if not any(term in visible_text for term in ("modelo", "consumo", "autonomia")):
        missing.append("modelo/consumo/autonomía")
    if not missing:
        return []
    return [
        "La respuesta a una ruta barata con reserva mínima debe pedir en el mismo turno origen, destino, "
        "batería actual y modelo/consumo/autonomía. Faltan: " + ", ".join(missing) + "."
    ]


def cheap_route_with_reserve_request(normalized_message: str) -> bool:
    if "ruta" not in normalized_message:
        return False
    if not any(term in normalized_message for term in ("barata", "barato", "precio", "coste")):
        return False
    return any(term in normalized_message for term in ("sin bajar", "reserva", "20%", "20 %", "20 por ciento"))


def price_preference_context_contract_issues(
    blocks: list[dict],
    message: str,
    tool_history: list[dict[str, Any]],
    facts: dict[str, Any],
) -> list[str]:
    normalized_message = normalize(message)
    if not price_preference_request(normalized_message):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    has_context = price_preference_has_context(tool_history, facts)
    missing: list[str] = []
    if not has_context and not any(
        term in visible_text for term in ("origen", "destino", "ubicacion", "desde donde", "adonde", "a donde")
    ):
        missing.append("ruta o ubicación")
    if not any(term in visible_text for term in ("tarifa", "tarifas", "precio", "precios", "coste", "costes")):
        missing.append("limitación de tarifas/precios")
    if not missing:
        return []
    return [
        "La respuesta a una preferencia de precio debe pedir ruta/ubicación y aclarar que no inventará tarifas "
        "o precios si el proveedor no los da. Faltan: " + ", ".join(missing) + "."
    ]


def price_preference_request(normalized_message: str) -> bool:
    return any(term in normalized_message for term in ("caro", "caros", "barato", "barata", "precio", "tarifa", "coste"))


def price_preference_has_context(tool_history: list[dict[str, Any]], facts: dict[str, Any]) -> bool:
    if price_preference_has_tool_context(tool_history):
        return True
    return any(station_has_price_or_location(station) for station in facts.get("stations", {}).values())


def price_preference_has_tool_context(tool_history: list[dict[str, Any]]) -> bool:
    result = latest_station_search_result(tool_history)
    if not result or not result.get("ok"):
        return False
    if result.get("origin") and result.get("destination"):
        return True
    if result.get("location"):
        return True
    return bool(station_search_result_stops(result))


def station_has_price_or_location(station: dict[str, Any]) -> bool:
    return (
        optional_float(station.get("pricePerKwhEur")) is not None
        or (
            optional_float(station.get("lat")) is not None
            and optional_float(station.get("lon")) is not None
        )
    )


def minimum_charge_context_contract_issues(blocks: list[dict], message: str) -> list[str]:
    normalized_message = normalize(message)
    if not minimum_charge_request(normalized_message):
        return []
    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))
    if not visible_text:
        return []
    missing: list[str] = []
    if not any(term in visible_text for term in ("origen", "desde donde", "sales", "salida")):
        missing.append("origen")
    if not any(term in visible_text for term in ("destino", "adonde", "a donde")):
        missing.append("destino")
    if "bateria" not in visible_text:
        missing.append("batería actual")
    if not any(term in visible_text for term in ("modelo", "consumo", "autonomia")):
        missing.append("modelo/consumo/autonomía")
    if not missing:
        return []
    return [
        "La respuesta para cargar lo justo debe pedir origen, destino, batería actual y modelo/consumo/autonomía "
        "antes de calcular kWh o coste. Faltan: " + ", ".join(missing) + "."
    ]


def minimum_charge_request(normalized_message: str) -> bool:
    return "cargar lo justo" in normalized_message or "sin pagar de mas" in normalized_message


def latest_plan_route_result(tool_history: list[dict[str, Any]], facts: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for entry in reversed(tool_history):
        call = entry.get("call") if isinstance(entry.get("call"), dict) else {}
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        if call.get("tool") == "plan_route" and result.get("ok"):
            return result
    if facts:
        routes = facts.get("routes") if isinstance(facts.get("routes"), list) else []
        for route in reversed(routes):
            if isinstance(route, dict):
                return route
    return None


def latest_plan_route_reserve(tool_history: list[dict[str, Any]], facts: dict[str, Any] | None = None) -> float | None:
    for entry in reversed(tool_history):
        call = entry.get("call") if isinstance(entry.get("call"), dict) else {}
        if call.get("tool") != "plan_route":
            continue
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        preferences = args.get("preferences") if isinstance(args.get("preferences"), dict) else {}
        reserve = optional_float(preferences.get("reserve_min_percent"))
        if reserve is not None:
            return reserve
    if facts:
        for preferences in reversed(facts.get("routePreferences") or []):
            if not isinstance(preferences, dict):
                continue
            reserve = optional_float(preferences.get("reserve_min_percent"))
            if reserve is not None:
                return reserve
    return None


def latest_plan_route_max_useful_power(tool_history: list[dict[str, Any]], facts: dict[str, Any] | None = None) -> float | None:
    for entry in reversed(tool_history):
        call = entry.get("call") if isinstance(entry.get("call"), dict) else {}
        if call.get("tool") != "plan_route":
            continue
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        preferences = args.get("preferences") if isinstance(args.get("preferences"), dict) else {}
        power = optional_float(preferences.get("max_useful_power_kw"))
        if power is not None:
            return power
    if facts:
        for preferences in reversed(facts.get("routePreferences") or []):
            if not isinstance(preferences, dict):
                continue
            power = optional_float(preferences.get("max_useful_power_kw"))
            if power is not None:
                return power
        vehicle = facts.get("vehicle") if isinstance(facts.get("vehicle"), dict) else {}
        power = optional_float(vehicle.get("max_charge_kw"))
        if power is not None:
            return power
    return None


def route_requires_unvalidated_arrival_warning(route: dict[str, Any]) -> bool:
    return (
        route.get("planningLevel") == "chargers_only"
        or route.get("arrivalBattery") is None
        or route.get("energyKwh") is None
    )


def integer_percent_label(value: float) -> str | None:
    if abs(value - round(value)) > 0.001:
        return None
    return str(int(round(value)))


def user_message_mentions_percent(normalized_message: str, percent_label: str) -> bool:
    return (
        f"{percent_label}%" in normalized_message
        or f"{percent_label} %" in normalized_message
        or f"{percent_label} por ciento" in normalized_message
    )


def user_message_mentions_future_trip(normalized_message: str) -> bool:
    future_terms = (
        "manana",
        "mañana",
        "pasado manana",
        "pasado mañana",
        "este finde",
        "el finde",
        "fin de semana",
        "viernes",
        "sabado",
        "sábado",
        "domingo",
        "lunes",
        "martes",
        "miercoles",
        "miércoles",
        "jueves",
    )
    return any(visible_text_has_term(normalized_message, term) for term in future_terms)


def departure_battery_percent_labels(normalized_message: str) -> list[str]:
    labels: list[str] = []
    patterns = (
        r"\bsalgo\s+con\s+(\d{1,3})\s*%",
        r"\bsalimos\s+con\s+(\d{1,3})\s*%",
        r"\bsaldre\s+con\s+(\d{1,3})\s*%",
        r"\bsaldremos\s+con\s+(\d{1,3})\s*%",
        r"\bsalida\s+con\s+(\d{1,3})\s*%",
    )
    for pattern in patterns:
        labels.extend(match.group(1) for match in re.finditer(pattern, normalized_message))
    return dedupe_preserve_order(labels)


def blocks_before_first_charge_option(blocks: list[dict]) -> list[dict]:
    before: list[dict] = []
    for block in blocks:
        if block.get("type") in STATION_CARD_TYPES or block.get("type") in {"RouteCorridorCard", "StationList"}:
            return before
        before.append(block)
    return before


def visible_text_has_term(visible_text: str, term: str) -> bool:
    return re.search(rf"(^|[^a-z0-9]){re.escape(term)}($|[^a-z0-9])", visible_text) is not None


def block_uses_factual_location(block: dict) -> bool:
    return block.get("type") in {
        "StationList",
        "RouteCorridorCard",
        "StationPreviewCard",
        "StationDetailCard",
    }


VISIBLE_COPY_KEYS = {
    "text",
    "question",
    "title",
    "description",
    "summary",
    "risk",
    "context",
    "warning",
    "warnings",
    "body",
    "message",
    "recommendation",
}


def block_visible_text(block: dict) -> str:
    props = block.get("props") if isinstance(block.get("props"), dict) else {}
    return visible_text_from_value(props)


def visible_text_from_value(value: Any, *, include_strings: bool = False) -> str:
    if isinstance(value, str):
        return value if include_strings else ""
    if isinstance(value, dict):
        parts = []
        for key, nested in value.items():
            if key in VISIBLE_COPY_KEYS:
                parts.append(visible_text_from_value(nested, include_strings=True))
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        if not include_strings:
            return ""
        return " ".join(visible_text_from_value(item, include_strings=True) for item in value)
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
            "no tengo la direccion exacta",
            "no tengo coordenadas exactas",
            "no esta resuelto",
            "no esta geolocalizado",
            "sin ubicacion exacta",
        )
    )


def station_list_contract_issues(props: dict, facts: dict[str, Any]) -> list[str]:
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
        name = display_text(station.get("name") or station.get("stationName"), "")
        if not name:
            issues.append(f"StationList.stations[{index}] necesita name.")
            continue
        issues.extend(station_reference_contract_issues(f"StationList.stations[{index}].name", name, facts))
        issues.extend(station_metric_contract_issues(f"StationList.stations[{index}]", station, facts))
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


def destination_city_approximation_contract_issues(
    blocks: list[dict],
    tool_history: list[dict[str, Any]],
    message: str,
    facts: dict[str, Any],
) -> list[str]:
    normalized_message = normalize(message)
    if not message_mentions_hotel_or_poi(normalized_message):
        return []

    searches = city_approximation_destination_searches(tool_history, normalized_message, facts)
    if not searches:
        return []

    visible_text = normalize(" ".join(block_visible_text(block) for block in blocks))

    issues: list[str] = []
    for search in searches:
        label = display_text(search.get("label"), "")
        if not has_approximation_disclaimer(visible_text):
            issues.append(
                f"La respuesta usa '{label}' como búsqueda de ciudad para un hotel/POI y debe decir visiblemente "
                "que es una aproximación, no una ubicación exacta del hotel."
            )
        if not asks_for_refinement(visible_text):
            issues.append(
                "La respuesta debe pedir dirección, zona exacta, coordenadas o el hotel exacto para refinar la búsqueda."
            )
    return issues


def city_approximation_destination_searches(
    tool_history: list[dict[str, Any]],
    normalized_message: str,
    facts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    known_city_labels = {normalize(value[0]) for value in KNOWN_LOCATIONS.values()}
    searches: list[dict[str, Any]] = []
    for entry in tool_history:
        call = entry.get("call") if isinstance(entry, dict) and isinstance(entry.get("call"), dict) else {}
        if call.get("tool") != "search_destination_chargers":
            continue
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        location = args.get("location") if isinstance(args.get("location"), dict) else {}
        label = display_text(location.get("label"), "")
        normalized_label = normalize(label)
        if not label or normalized_label not in normalized_message:
            continue
        if normalized_label not in known_city_labels:
            continue
        searches.append({"label": label})
    if facts:
        for location in facts.get("locations") or []:
            if not isinstance(location, dict):
                continue
            label = display_text(location.get("label"), "")
            normalized_label = normalize(label)
            if not label or normalized_label not in normalized_message:
                continue
            if normalized_label not in known_city_labels:
                continue
            searches.append({"label": label})
    return searches


def message_mentions_hotel_or_poi(normalized_text: str) -> bool:
    return any(
        term in normalized_text
        for term in (
            "hotel",
            "melia",
            "alojamiento",
            "me quedo",
            "duermo",
            "cerca de la alhambra",
            "cerca del hotel",
        )
    )


def message_mentions_destination_or_stay(normalized_text: str) -> bool:
    return message_mentions_hotel_or_poi(normalized_text) or any(
        term in normalized_text
        for term in (
            "destino",
            "estancia",
            "durante la estancia",
            "semana",
            "dias",
            "días",
            "finde",
            "fin de semana",
            "al llegar",
        )
    )


def asks_for_refinement(normalized_text: str) -> bool:
    return any(
        term in normalized_text
        for term in (
            "direccion",
            "dirección",
            "zona exacta",
            "hotel exacto",
            "ubicacion exacta",
            "ubicación exacta",
            "coordenadas",
            "refinar",
            "afinar",
        )
    )


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
    name = display_text(props.get("name") or props.get("stationName"), "")
    if not name or generic_station_label(name):
        return []
    source = facts["stations"].get(station_key(name))
    if not source:
        return []

    issues: list[str] = []
    rendered_values = station_value_aliases(props)
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
        elif field in {"lat", "lon"} and not coordinate_value_matches(rendered, expected):
            issues.append(f"{label}.{field} no coincide con el dato de herramienta para {name}.")
        elif not values_match(rendered, expected):
            issues.append(f"{label}.{field} no coincide con el dato de herramienta para {name}.")
    return issues


def route_summary_contract_issues(props: dict, facts: dict[str, Any], label: str) -> list[str]:
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
        elif not values_match(rendered, expected):
            issues.append(f"{label}.{field} no coincide con plan_route.")
    return issues


def map_preview_contract_issues(
    props: dict,
    facts: dict[str, Any],
    explicit_coordinates: list[tuple[float, float]],
    label: str,
) -> list[str]:
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
        lat = optional_float(point.get("lat"))
        lon = optional_float(point.get("lon"))
        if lat is None and lon is None:
            continue
        if lat is None or lon is None:
            issues.append(f"{label}.{field} necesita lat y lon juntos.")
        elif not coordinate_traced(lat, lon, facts["locations"], explicit_coordinates):
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
    if not isinstance(rendered, list) or not isinstance(expected, list):
        return False
    if len(rendered) != 2 or len(expected) != 2:
        return False
    rendered_lon = optional_float(rendered[0])
    rendered_lat = optional_float(rendered[1])
    expected_lon = optional_float(expected[0])
    expected_lat = optional_float(expected[1])
    if rendered_lon is None or rendered_lat is None or expected_lon is None or expected_lat is None:
        return False
    return close_coordinates(rendered_lat, rendered_lon, expected_lat, expected_lon)


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
    if block_type == "PositionRequestCard":
        title = str(props.get("title") or "Necesito ubicación").strip()
        body = str(props.get("body") or "").strip()
        return f"Asistente pidió ubicación: {title}. {body}".strip()
    if block_type in STATION_CARD_TYPES:
        price = props.get("pricePerKwhEur")
        price_text = f", precio {price} {props.get('currency') or 'EUR'}/kWh" if price is not None else ""
        return (
            "Estación mostrada previamente: "
            f"{props.get('name') or props.get('stationName')}, potencia {props.get('powerKw')} kW, "
            f"distancia {props.get('distanceKm')} km, EVSEs {props.get('availableEvses')}, "
            f"conectores {props.get('connectorTypes')}, desvío {props.get('detourMin')} min{price_text}."
        )
    if block_type == "RouteCorridorCard":
        return (
            "Resultado previo de ruta: "
            f"{props.get('distanceKm')} km, {props.get('durationMin')} min, "
            f"llegada {props.get('arrivalBattery')}%."
        )
    if block_type == "StationList":
        stations = props.get("stations") if isinstance(props.get("stations"), list) else []
        stop_summaries = [summarize_stop_for_context(station) for station in stations[:5] if isinstance(station, dict)]
        stop_summaries = [summary for summary in stop_summaries if summary]
        if stop_summaries:
            return "Estaciones mostradas con datos trazables: " + "; ".join(stop_summaries)
    return ""


def summarize_stop_for_context(stop: dict) -> str:
    name = display_text(stop.get("placeName") or stop.get("name") or stop.get("stationName"), "")
    if not name:
        return ""
    aliases = station_value_aliases(stop)
    details = []
    distance = aliases.get("distanceKm")
    if distance is not None:
        details.append(f"distancia {distance} km")
    power = aliases.get("powerKw")
    if power is not None:
        details.append(f"potencia {power} kW")
    price = aliases.get("pricePerKwhEur")
    if price is not None:
        details.append(f"precio {price} {aliases.get('currency') or 'EUR'}/kWh")
    connectors = aliases.get("connectorTypes")
    if isinstance(connectors, list) and connectors:
        connector_text = ", ".join(str(connector) for connector in connectors if connector)
        if connector_text:
            details.append(f"conectores {connector_text}")
    lat = aliases.get("lat")
    lon = aliases.get("lon")
    if lat is not None and lon is not None:
        details.append(f"coordenadas {lat},{lon}")
    if not details:
        return name
    return f"{name} ({', '.join(details)})"


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
                f"assistant-{uuid4().hex[:10]}",
                "AssistantMessage",
                {
                    "text": (
                        f"No hay paradas con puntos de carga autorizados importados cerca de {location.label}. "
                        "No voy a inventar estaciones; comparte otra ubicación o coordenadas más precisas."
                    ),
                },
            ),
            position_request_block(
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
        block(
            f"assistant-{uuid4().hex[:10]}",
            "AssistantMessage",
            {
                "text": (
                    f"Uso {location.label} como ubicación aproximada para esta búsqueda urgente. "
                    "Muestro estaciones con puntos de carga autorizados cerca de esa zona. "
                    "Confirma acceso final, tarifa y disponibilidad antes de depender de ellas."
                ),
            },
        ),
        block(
            f"station-{uuid4().hex[:10]}",
            "StationPreviewCard",
            {"title": "Estación cercana", **station_props_from_nearby(nearest)},
        ),
        block(
            f"stations-{uuid4().hex[:10]}",
            "StationList",
            {
                "title": "Otras estaciones cercanas",
                "stations": [station_props_from_nearby(item) for item in top],
            },
        ),
    ]


def destination_charge_blocks(intent: ParsedIntent) -> list[dict]:
    location = intent.destination_search or intent.destination or intent.origin
    if location is None:
        return [
            missing_data_message_block(
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
                f"assistant-{uuid4().hex[:10]}",
                "AssistantMessage",
                {
                    "text": (
                        f"Uso {location.label} como ubicación aproximada para la búsqueda. "
                        "No hay paradas con puntos de carga autorizados cerca de ese destino. No voy a inventar estaciones."
                    )
                },
            ),
        ]

    top = stations[:3]
    return [
        block(
            f"assistant-{uuid4().hex[:10]}",
            "AssistantMessage",
            {
                "text": (
                    f"Uso {location.label} como ubicación aproximada para la búsqueda. "
                    "Muestro estaciones con puntos de carga autorizados cerca del destino. "
                    "Confirma acceso final, tarifa y disponibilidad antes de depender de ellas."
                ),
            },
        ),
        block(
            f"stations-{uuid4().hex[:10]}",
            "StationList",
            {
                "title": "Estaciones cerca del destino",
                "stations": [station_props_from_nearby(item) for item in top],
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
    primary_station_props = route_station_props(station, title="Estación recomendada")
    alternative_station_props = [route_station_props(alternative.station) for alternative in plan.alternatives]
    warning_text = " ".join(str(warning).strip() for warning in plan.warnings if str(warning).strip())
    assistant_text = (
        "He decidido calcular ruta porque hay origen y destino. "
        if intent.vehicle
        else "He decidido explorar paradas de carga en ruta. Sin datos completos del coche no calculo autonomía."
    )
    if warning_text:
        assistant_text = f"{assistant_text} {warning_text}"
    blocks = [
        block(
            f"assistant-{uuid4().hex[:10]}",
            "AssistantMessage",
            {"text": assistant_text},
        ),
        block(
            f"route-{uuid4().hex[:10]}",
            "RouteCorridorCard",
            {
                "distanceKm": round(plan.route.distance_km, 1),
                "durationMin": plan.route.duration_min,
                "energyKwh": round_optional(plan.energy_kwh),
                "arrivalBattery": round_optional(plan.arrival_battery_percent),
                "origin": {"label": intent.origin.label, "lat": intent.origin.lat, "lon": intent.origin.lon},
                "destination": {"label": intent.destination.label, "lat": intent.destination.lat, "lon": intent.destination.lon},
                "stations": [primary_station_props, *alternative_station_props],
                "routeGeometry": route_geometry_payload(plan.route),
                "corridorRadiusKm": 25,
                "geometryPrecision": "provider",
                "source": "plan_route",
            },
        ),
    ]
    blocks.extend(
        [
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


def route_station_props(station: dict[str, Any], title: str | None = None) -> dict[str, Any]:
    props: dict[str, Any] = {
        "name": station["name"],
        "stationName": station["name"],
        "powerKw": station.get("power_kw"),
        "distanceKm": station.get("distance_to_route_km"),
        "detourMin": station.get("detour_min"),
        "lat": station.get("lat"),
        "lon": station.get("lon"),
        "confidence": "media",
        **station_price_props_from_mapping(station),
    }
    if title:
        props["title"] = title
    if station.get("available_connectors") is not None:
        props["availableEvses"] = station.get("available_connectors")
    if station.get("connector_count") is not None:
        props["totalEvses"] = station.get("connector_count")
    if station.get("connector"):
        props["connectorTypes"] = [station.get("connector")]
    if isinstance(station.get("services"), list):
        props["amenities"] = station.get("services")
    return props


def station_price_props_from_mapping(station: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {"priceIsEstimated": station.get("price_is_estimated")}
    if station.get("price_eur_kwh") is not None and station.get("price_is_estimated") is not True:
        props["pricePerKwhEur"] = station.get("price_eur_kwh")
        props["currency"] = "EUR"
    return props


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


def missing_data_message_block(question: str, fields: list[str]) -> dict:
    normalized_fields = [str(field).strip() for field in fields if str(field).strip()]
    field_text = ", ".join(normalized_fields)
    text = question if not field_text else f"{question} Envíame: {field_text}."
    return block(f"assistant-{uuid4().hex[:10]}", "AssistantMessage", {"text": text})


def position_request_block(reason: str, title: str, body: str) -> dict:
    return block(
        f"position-{uuid4().hex[:10]}",
        "PositionRequestCard",
        {
            "reason": reason,
            "title": title,
            "body": body,
            "precision": "approximate",
            "manualFields": ["ciudad", "latitud", "longitud"],
        },
    )


def location_label(location: dict[str, Any] | ParsedLocation) -> str:
    if isinstance(location, ParsedLocation):
        return location.label
    return display_text(location.get("label") or location.get("name"), "la ubicación indicada")


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
    return dedupe_station_list_blocks(valid)


def dedupe_station_list_blocks(blocks: list[dict]) -> list[dict]:
    seen_primary_stations: set[str] = set()
    cleaned: list[dict] = []
    for item in blocks:
        block_type = item.get("type")
        props = item.get("props") if isinstance(item.get("props"), dict) else {}
        if block_type in STATION_CARD_TYPES:
            seen_primary_stations.update(station_identities(props))
            cleaned.append(item)
            continue
        if block_type != "StationList":
            cleaned.append(item)
            continue

        stations = props.get("stations")
        if not isinstance(stations, list):
            cleaned.append(item)
            continue

        list_seen: set[str] = set()
        normalized_stations = []
        for station in stations:
            identities = station_identities(station)
            if identities and (identities & seen_primary_stations or identities & list_seen):
                continue
            list_seen.update(identities)
            normalized_stations.append(station)

        if not normalized_stations and stations:
            continue
        cleaned.append({**item, "props": {**props, "stations": normalized_stations}})
    return cleaned


def station_identities(station: Any) -> set[str]:
    if not isinstance(station, dict):
        return set()
    name = normalize(display_text(station.get("name") or station.get("stationName"), ""))
    if not name:
        return set()
    identities = {name}
    lat = optional_float(station.get("lat"))
    lon = optional_float(station.get("lon"))
    if lat is not None and lon is not None:
        identities.add(f"{name}@{lat:.5f},{lon:.5f}")
    return identities


def normalize_block_props(block_type: str, props: dict) -> dict:
    if block_type in {"AssistantMessage", "UserMessage"}:
        text_value = props.get("text") or props.get("message") or props.get("description") or props.get("risk")
        if not text_value and isinstance(props.get("risks"), list):
            text_value = " ".join(str(item) for item in props["risks"] if item)
        if not text_value and isinstance(props.get("items"), list):
            text_value = " ".join(str(item) for item in props["items"] if item)
        if not text_value and isinstance(props.get("warnings"), list):
            text_value = " ".join(str(item) for item in props["warnings"] if item)
        if not text_value:
            text_value = props.get("title") or ""
        return {"text": str(text_value)}
    if block_type in STATION_CARD_TYPES:
        recommended_stop = props.get("recommendedStop") if isinstance(props.get("recommendedStop"), dict) else {}
        station = props.get("station") if isinstance(props.get("station"), dict) else {}
        charger = props.get("charger") if isinstance(props.get("charger"), dict) else {}
        nearest_record = props.get("nearest") if isinstance(props.get("nearest"), dict) else {}
        source = recommended_stop or station or charger or nearest_record
        name = (
            (None if isinstance(props.get("nearest"), bool) else props.get("nearest"))
            or props.get("stationName")
            or props.get("name")
            or props.get("chargerName")
            or recommended_stop.get("stationName")
            or recommended_stop.get("name")
            or station.get("stationName")
            or station.get("name")
            or charger.get("stationName")
            or charger.get("name")
            or nearest_record.get("stationName")
            or nearest_record.get("name")
            or props.get("station")
            or props.get("charger")
        )
        station_name = display_text(name, "Estación por confirmar")
        normalized = {
            "name": station_name,
            "stationName": station_name,
        }
        for field in ("title", "takeaway", "why", "evidence", "uncertainty", "primaryAction", "risk"):
            if field in props:
                normalized[field] = props[field]
        if not normalized.get("address"):
            address = props.get("address") or props.get("locationName") or props.get("placeName") or source.get("address")
            if address:
                normalized["address"] = display_text(address, "")
        source_aliases = station_value_aliases(source)
        prop_aliases = station_value_aliases(props)
        for field, value in {**prop_aliases, **source_aliases}.items():
            normalized.setdefault(field, value)
        for source_key, target_key in (
            ("power_kw", "powerKw"),
            ("max_power_kw", "powerKw"),
            ("distance_km", "distanceKm"),
            ("detour_min", "detourMin"),
            ("available_evses", "availableEvses"),
            ("available_connectors", "availableEvses"),
            ("connector_types", "connectorTypes"),
        ):
            if target_key not in normalized and source_key in source:
                normalized[target_key] = source[source_key]
        if isinstance(source.get("amenities"), list):
            normalized.setdefault("amenities", source["amenities"])
        if isinstance(props.get("amenities"), list):
            normalized.setdefault("amenities", props["amenities"])
        return normalized
    if block_type == "StationList":
        stations = props.get("stations")
        if stations is None:
            stations = props.get("stops")
        if not isinstance(stations, list):
            return {"title": str(props.get("title") or "Estaciones"), "stations": stations}
        normalized_stations = []
        for station in stations:
            if not isinstance(station, dict):
                normalized_stations.append(station)
                continue
            normalized_stations.append(normalize_block_props("StationPreviewCard", station))
        return {
            "title": str(props.get("title") or "Estaciones"),
            "stations": normalized_stations,
        }
    if block_type == "ActionButtons":
        actions = props.get("actions")
        if not isinstance(actions, list):
            return {"actions": actions}
        normalized_actions = []
        for action in actions:
            if not isinstance(action, dict):
                normalized_actions.append(action)
                continue
            normalized_action = {**action}
            label = action.get("label") or action.get("title") or action.get("text")
            if not label:
                function_call = action.get("functionCall") if isinstance(action.get("functionCall"), dict) else {}
                event = action.get("event") if isinstance(action.get("event"), dict) else {}
                if function_call.get("call") == "openUrl":
                    label = "Abrir ruta"
                elif event.get("name"):
                    label = "Continuar"
                elif action.get("disabled"):
                    label = "Acción no disponible"
            if label:
                normalized_action["label"] = display_text(label, "Continuar")
            normalized_actions.append(normalized_action)
        return {**props, "actions": normalized_actions}
    if block_type == "PositionRequestCard":
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
                or "Comparte tu ubicación o escribe una ciudad, carretera o punto cercano para continuar sin inventar resultados."
            ),
            "precision": precision,
            "manualFields": [str(item) for item in manual_fields if item],
        }
    return props


def display_text(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        for key in ("label", "stationName", "name", "title", "text", "value"):
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


def normalize_battery_prop(value: Any) -> float | int | None:
    number = optional_float(value)
    if number is None or number < 0 or number > 100:
        return None
    if number.is_integer():
        return int(number)
    return number


def extra_blocks_from_props(block_type: str, props: dict, index: int) -> list[dict]:
    return []


def normalize(value: str) -> str:
    substitutions = str.maketrans("áéíóúüñ", "aeiouun")
    return value.lower().replace("\u00a0", " ").replace("\u202f", " ").translate(substitutions)
