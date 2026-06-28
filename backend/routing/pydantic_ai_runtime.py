from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from django.conf import settings
from pydantic_ai import RunContext
from pydantic import BaseModel, ConfigDict, Field

from routing.a2ui_output_models import PydanticAIDecision, PydanticAIFinalOutput
from routing.instrumentation import (
    elapsed_ms,
    estimate_deepseek_cost,
    normalize_usage,
    record_trace_event,
    tool_result_summary,
    to_plain,
)
from routing.policies.a2ui import a2ui_contract_issues
from routing.tool_contracts import LocationArg, PreferencesArg, VehicleArg, conversation_tool_trace_metadata
from routing.tools import ConversationToolError, ToolCall, execute_conversation_tool


ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class KalmioAgentDeps:
    current_message: str
    history_blocks: list[dict[str, Any]]
    tool_history: list["ToolHistoryEntry"] = field(default_factory=list)
    seen_calls: set[str] = field(default_factory=set)
    blocked_tool_attempts: int = 0
    progress_callback: ProgressCallback | None = None

    def tool_history_dicts(self) -> list[dict[str, Any]]:
        return [entry.model_dump() for entry in self.tool_history]


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call: ToolCallRecord
    result: dict[str, Any] = Field(default_factory=dict)


class RenderableToolResult(RuntimeError):
    def __init__(self, tool_result: dict[str, Any]) -> None:
        super().__init__("Renderable tool result is ready.")
        self.tool_result = tool_result


def run_pydantic_ai_agent(
    message: str,
    *,
    history_blocks: list[dict[str, Any]] | None,
    max_tool_calls: int,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    from pydantic_ai.usage import UsageLimits

    from routing.agent import (
        contextualized_prompt,
        conversation_failure_blocks,
        fallback_from_tool_history,
    )

    history_blocks = history_blocks or []
    decision_message = contextualized_prompt(message, history_blocks)
    prompt = pydantic_ai_prompt(decision_message)
    deps = KalmioAgentDeps(
        current_message=message,
        history_blocks=history_blocks,
        progress_callback=progress_callback,
    )
    agent = build_pydantic_ai_agent()
    started = time.perf_counter()
    try:
        emit_progress(progress_callback, "agent_reasoning", "Entendiendo la petición y el contexto útil")
        result = agent.run_sync(
            prompt,
            deps=deps,
            usage_limits=UsageLimits(request_limit=max(max_tool_calls + 2, 2), tool_calls_limit=max_tool_calls),
        )
    except RenderableToolResult as exc:
        from routing.agent import blocks_from_tool_result, validate_blocks

        record_pydantic_ai_trace(
            status="ok",
            started=started,
            prompt=prompt,
            result=None,
            error=None,
            metadata={"runtime": "pydantic_ai", "shortCircuit": "renderable_tool_result"},
        )
        return validate_blocks(blocks_from_tool_result(exc.tool_result, decision_message))
    except Exception as exc:
        if deps.tool_history:
            record_pydantic_ai_trace(
                status="error",
                started=started,
                prompt=prompt,
                result=None,
                error=str(exc),
            )
            return fallback_from_tool_history(deps.tool_history_dicts(), str(exc), decision_message)
        record_trace_event(
            event="agent_guardrail",
            name="pydantic_ai_output_recovery",
            status="ok",
            provider="deepseek",
            model=getattr(settings, "KALMIO_DEEPSEEK_MODEL", "deepseek-v4-pro"),
            duration_ms=elapsed_ms(started),
            metadata={"runtime": "pydantic_ai", "reason": str(exc)},
        )
        return conversation_failure_blocks(message)

    record_pydantic_ai_trace(status="ok", started=started, prompt=prompt, result=result, error=None)
    return result.output.block_dicts()


def pydantic_ai_prompt(decision_message: str) -> str:
    from routing.tools import KNOWN_LOCATIONS

    known_locations = ", ".join(sorted(label for label, _lat, _lon in KNOWN_LOCATIONS.values()))
    return (
        "Tarea: responde como agente EV de Kalmio usando herramientas nativas cuando hagan falta datos reales.\n"
        "\n"
        "Ámbito de Kalmio: España. Si el usuario menciona una ubicación conocida de Kalmio, úsala como ubicación española; "
        "no pidas desambiguar país para ciudades conocidas. Ubicaciones conocidas: "
        f"{known_locations}.\n"
        "\n"
        "Reglas de herramientas:\n"
        "- Usa plan_route cuando haya origen y destino concretos y el usuario pida ruta, paradas en ruta, "
        "pocas paradas, margen, precio de ruta o una corrección de origen/destino.\n"
        "- Usa search_destination_chargers cuando haya ciudad/zona/coordenadas y el usuario quiera cargar cerca, "
        "en destino, hotel o estancia.\n"
        "- Una ciudad conocida es suficiente para una primera búsqueda urbana de cargadores; si el usuario pide "
        "un cargador en Madrid/Córdoba/etc. con preferencia de noche, seguridad, comodidad, precio o servicios, "
        "llama search_destination_chargers con esa ciudad aproximada y explica el límite de datos después. "
        "No pidas barrio/zona antes de mostrar opciones salvo que no haya ninguna ubicación.\n"
        "- Si falta ubicación para carga urgente, devuelve PositionRequestCard o AssistantMessage; no inventes ubicación.\n"
        "- Si falta origen o destino para ruta, pregunta el dato mínimo; no llames plan_route con placeholders.\n"
        "- Si el usuario solo dice de dónde sale y pregunta dónde cargar, pregunta destino antes de buscar; no busques cerca del origen como destino.\n"
        "- Si el usuario pide reservar, di que Kalmio no puede reservar desde el chat ni confirmar plaza con el proveedor; puedes ayudar a buscar opciones.\n"
        "- Si el usuario corrige origen/destino en un follow-up, conserva batería/preferencias explícitas previas salvo que las corrija.\n"
        "- No repitas una herramienta con los mismos argumentos.\n"
        "\n"
        "Reglas de factualidad:\n"
        "- No inventes estaciones, coordenadas, precios, disponibilidad, seguridad, energía, autonomía ni batería de llegada.\n"
        "- Si plan_route devuelve planningLevel='chargers_only' o arrivalBattery/energyKwh nulos, el primer AssistantMessage antes de la RouteCorridorCard debe decir que no puedes validar batería de llegada ni reserva sin consumo, autonomía o perfil completo.\n"
        "- Disponibilidad, acceso y tarifas pueden cambiar en viajes futuros; avísalo si el usuario menciona mañana, viernes, finde, sábado/domingo o fecha.\n"
        "- availableEvses/totalEvses son puestos registrados; no los llames ocupación en vivo. connectorTypes son conectores físicos.\n"
        "\n"
        "A2UI permitido en la salida final:\n"
        "- AssistantMessage: siempre útil para explicar decisión, límite de datos y siguiente paso.\n"
        "- PositionRequestCard: pedir ubicación actual/manual.\n"
        "- RouteCorridorCard: solo después de plan_route. Usa distanceKm, durationMin, origin, destination, corridorRadiusKm, "
        "geometryPrecision='schematic' salvo que tengas routeGeometry completa exacta de herramienta; incluye stations/primaryStation solo con estaciones de herramienta.\n"
        "- StationPreviewCard: una estación concreta de herramienta.\n"
        "- StationList: varias estaciones cuando comparar cambie la decisión.\n"
        "- ActionButtons: solo event seguro o functionCall.openUrl con URL http(s); ponlos pegados a la card a la que pertenecen.\n"
        "\n"
        "Composición recomendada:\n"
        "- Ruta con datos incompletos: AssistantMessage breve, RouteCorridorCard compacta, opcional StationPreviewCard/ActionButtons si el usuario pidió parada.\n"
        "- Carga cerca/destino: AssistantMessage breve, StationPreviewCard primaria, ActionButtons, StationList solo si aporta alternativas.\n"
        "- Aclaración: uno o dos bloques, sin tarjetas de resultados.\n"
        "\n"
        "La salida final debe seguir PydanticAIFinalOutput: intent?, confidence?, blocks, metadata?, rationale?. "
        "No incluyas type/tool/args/tool_call en la salida final; para herramientas, llama las herramientas nativas.\n"
        "\n"
        f"Contexto y mensaje:\n{decision_message}"
    )


def build_pydantic_ai_agent():
    from pydantic_ai import Agent
    from pydantic_ai.exceptions import ModelRetry

    agent = Agent(
        build_pydantic_ai_model(),
        deps_type=KalmioAgentDeps,
        output_type=PydanticAIFinalOutput,
        system_prompt=(
            "Eres el agente conversacional de Kalmio para planificación EV. "
            "Usa las herramientas registradas cuando necesites datos reales, pero no las llames si falta "
            "ubicación, origen o destino crítico para sus argumentos. "
            "Si el usuario pide ida/vuelta, regreso, volver o fechas de salida/vuelta y no dice desde dónde sale, "
            "pregunta el origen en AssistantMessage y no llames herramientas todavía. "
            "Si pide una parada, baños, cafetería, restaurante, seguridad o comodidad pero no da ubicación ni ruta, "
            "pregunta ubicación/ruta y no llames search_destination_chargers. "
            "Si sí da una ciudad conocida para esa parada o preferencia, úsala como primera búsqueda aproximada. "
            "Cuando uses plan_route sin perfil completo de vehículo, la respuesta final debe incluir un AssistantMessage "
            "visible antes de cualquier card explicando que no puedes validar llegada, consumo, autonomía o margen. "
            "Devuelve una respuesta final con blocks A2UI válidos; no inventes hechos."
        ),
        model_settings=pydantic_ai_model_settings(),
        retries=2,
    )

    @agent.output_validator
    def validate_a2ui_output(ctx: RunContext[KalmioAgentDeps], output: PydanticAIFinalOutput) -> PydanticAIFinalOutput:
        from routing.agent import fallback_from_tool_history, validate_blocks

        blocks = validate_blocks(output.block_dicts())
        city_search_issue = known_city_search_required_issue(ctx.deps, blocks)
        if city_search_issue:
            raise ModelRetry(city_search_issue)

        issues = a2ui_contract_issues(
            blocks,
            ctx.deps.tool_history_dicts(),
            ctx.deps.current_message,
            history_blocks=ctx.deps.history_blocks,
        )
        if issues:
            if ctx.deps.tool_history:
                fallback_blocks = validate_blocks(
                    fallback_from_tool_history(
                        ctx.deps.tool_history_dicts(),
                        "Salida final no trazable tras herramienta.",
                        ctx.deps.current_message,
                    )
                )
                return PydanticAIFinalOutput(
                    intent=output.intent,
                    confidence=output.confidence,
                    blocks=fallback_blocks,
                    metadata={
                        **(output.metadata or {}),
                        "guardrail": "tool_result_fallback",
                        "guardrailIssues": issues,
                    },
                    rationale=output.rationale,
                )
            raise ModelRetry(
                "La respuesta final viola el contrato A2UI/factual de Kalmio. "
                "Devuelve una salida final corregida usando solo datos trazables. "
                f"Problemas: {json.dumps(issues, ensure_ascii=False)}"
            )
        return PydanticAIFinalOutput(
            intent=output.intent,
            confidence=output.confidence,
            blocks=blocks,
            metadata=output.metadata,
            rationale=output.rationale,
        )

    @agent.tool(
        name="resolve_location",
        description="Resuelve una ciudad, zona, carretera concreta o POI conocido antes de buscar carga o ruta.",
        retries=1,
        sequential=True,
    )
    def resolve_location(ctx: RunContext[KalmioAgentDeps], query: str) -> dict[str, Any]:
        return execute_pydantic_ai_tool(ctx, "resolve_location", {"query": query})

    @agent.tool(
        name="search_destination_chargers",
        description="Busca puntos de carga autorizados cerca de una ubicación ya resuelta o coordenadas explícitas.",
        retries=1,
        sequential=True,
    )
    def search_destination_chargers(
        ctx: RunContext[KalmioAgentDeps],
        location: LocationArg,
        connector: str | None = None,
        radius_km: float = 80,
        limit: int = 3,
    ) -> dict[str, Any]:
        return execute_pydantic_ai_tool(
            ctx,
            "search_destination_chargers",
            {
                "location": location.model_dump(exclude_none=True),
                "connector": connector,
                "radius_km": radius_km,
                "limit": limit,
            },
        )

    @agent.tool(
        name="plan_route",
        description="Calcula ruta EV con proveedor y puntos de carga autorizados cuando hay origen y destino.",
        retries=1,
        sequential=True,
    )
    def plan_route(
        ctx: RunContext[KalmioAgentDeps],
        origin: LocationArg,
        destination: LocationArg,
        vehicle: VehicleArg | None = None,
        preferences: PreferencesArg | None = None,
        corridor_radius_km: float = 25,
    ) -> dict[str, Any]:
        return execute_pydantic_ai_tool(
            ctx,
            "plan_route",
            {
                "origin": origin.model_dump(exclude_none=True),
                "destination": destination.model_dump(exclude_none=True),
                "vehicle": vehicle.model_dump(exclude_none=True) if vehicle else None,
                "preferences": preferences.model_dump(exclude_none=True) if preferences else None,
                "corridor_radius_km": corridor_radius_km,
            },
        )

    return agent


def known_city_search_required_issue(deps: KalmioAgentDeps, blocks: list[dict[str, Any]]) -> str | None:
    if any(entry.call.tool in {"search_destination_chargers", "plan_route"} for entry in deps.tool_history):
        return None
    city = known_city_in_message(deps.current_message)
    if not city:
        return None
    if not asks_for_city_charger_search(deps.current_message):
        return None
    if not asks_for_more_precise_location(blocks):
        return None
    label, lat, lon = city
    return (
        "La ciudad conocida indicada por el usuario ya es ubicación suficiente para una primera búsqueda urbana. "
        "No pidas barrio, zona exacta ni ubicación precisa antes de mostrar opciones. "
        "Llama search_destination_chargers con "
        f"location={{'label':'{label}','lat':{lat},'lon':{lon}}}; "
        "después explica que es una aproximación y que Kalmio no valida disponibilidad, tarifas, acceso ni seguridad en vivo."
    )


def known_city_in_message(message: str) -> tuple[str, float, float] | None:
    from routing.tools import KNOWN_LOCATIONS, normalize_location_query

    normalized = normalize_location_query(message)
    for key, location in KNOWN_LOCATIONS.items():
        if re.search(rf"(^|[^a-z0-9]){re.escape(key)}([^a-z0-9]|$)", normalized):
            return location
    return None


def asks_for_city_charger_search(message: str) -> bool:
    from routing.tools import normalize_location_query

    normalized = normalize_location_query(message)
    return any(
        term in normalized
        for term in (
            "cargar",
            "cargador",
            "cargadores",
            "ccs2",
            "type2",
            "chademo",
            "gratis",
            "tarifa",
            "precio",
            "barato",
            "hotel",
            "alojamiento",
            "duermo",
            "cerca",
            "urgente",
            "necesito",
            "bateria",
            "%",
        )
    )


def asks_for_more_precise_location(blocks: list[dict[str, Any]]) -> bool:
    if any(block.get("type") == "PositionRequestCard" for block in blocks):
        return True
    visible_text = " ".join(str((block.get("props") or {}).get("text") or "") for block in blocks)
    visible_text += " ".join(str((block.get("props") or {}).get("body") or "") for block in blocks)
    normalized = visible_text.lower()
    return any(
        term in normalized
        for term in (
            "ubicación exacta",
            "ubicacion exacta",
            "zona concreta",
            "barrio",
            "calle",
            "confírmame tu ubicación",
            "confirmame tu ubicacion",
        )
    )


def build_pydantic_ai_model():
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    api_key = getattr(settings, "KALMIO_DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DeepSeek no está configurado: falta KALMIO_DEEPSEEK_API_KEY o DEEPSEEK_API_KEY.")
    return OpenAIChatModel(
        getattr(settings, "KALMIO_DEEPSEEK_MODEL", "deepseek-v4-pro"),
        provider=OpenAIProvider(
            base_url=getattr(settings, "KALMIO_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            api_key=api_key,
        ),
    )


def pydantic_ai_model_settings() -> dict[str, Any]:
    return {
        "max_tokens": getattr(settings, "KALMIO_DEEPSEEK_MAX_TOKENS", 1800),
        "temperature": getattr(settings, "KALMIO_DEEPSEEK_TEMPERATURE", 0),
        "timeout": getattr(settings, "KALMIO_DEEPSEEK_TIMEOUT_SECONDS", 30),
        "extra_body": {
            "thinking": {
                "type": "enabled" if getattr(settings, "KALMIO_DEEPSEEK_THINKING", False) else "disabled",
            },
        },
    }


def execute_pydantic_ai_tool(ctx, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    from routing.agent import (
        compact_tool_result_for_prompt,
        conversation_tool_finished_label,
        conversation_tool_progress_label,
        is_renderable_tool_result,
        tool_call_argument_grounding_issues,
    )

    deps: KalmioAgentDeps = ctx.deps
    args = {key: value for key, value in args.items() if value is not None}
    decision = {"type": "tool_call", "tool": tool_name, "args": args}
    grounding_issues = tool_call_argument_grounding_issues(
        decision,
        current_message=deps.current_message,
        history_blocks=deps.history_blocks,
        tool_history=deps.tool_history_dicts(),
    )
    if grounding_issues:
        return blocked_tool_result_for_model(
            deps,
            tool_name,
            " ".join(grounding_issues),
            guardrail="argument_grounding",
        )

    call_signature = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, ensure_ascii=False)
    if call_signature in deps.seen_calls:
        return blocked_tool_result_for_model(
            deps,
            tool_name,
            f"No repitas la herramienta {tool_name} con los mismos argumentos; devuelve una respuesta final.",
            guardrail="duplicate_tool_call",
        )
    deps.seen_calls.add(call_signature)

    tool_started = time.perf_counter()
    emit_progress(
        deps.progress_callback,
        "tool_started",
        conversation_tool_progress_label(tool_name),
        tool=tool_name,
    )
    try:
        result = execute_conversation_tool(ToolCall(name=tool_name, args=args))
        args_valid = True
        result_valid = True
    except ConversationToolError as exc:
        result = {"ok": False, "tool": tool_name, "error": str(exc)}
        args_valid = False
        result_valid = False
    finally:
        tool_duration_ms = elapsed_ms(tool_started)

    emit_progress(
        deps.progress_callback,
        "tool_finished",
        conversation_tool_finished_label(tool_name, bool(result.get("ok"))),
        tool=tool_name,
        ok=bool(result.get("ok")),
    )
    record_trace_event(
        event="internal_tool_call",
        name=tool_name,
        status="ok" if result.get("ok") else "error",
        duration_ms=tool_duration_ms,
        metadata={
            **tool_result_summary(result),
            **conversation_tool_trace_metadata(tool_name, args_valid=args_valid, result_valid=result_valid),
        },
        request_payload=args,
        response_payload=result,
    )
    deps.tool_history.append(ToolHistoryEntry(call=ToolCallRecord(tool=tool_name, args=args), result=result))
    if result.get("ok") and is_renderable_tool_result(result):
        raise RenderableToolResult(result)
    return compact_tool_result_for_prompt(result, tool_name)


def blocked_tool_result_for_model(
    deps: KalmioAgentDeps,
    tool_name: str,
    message: str,
    *,
    guardrail: str,
) -> dict[str, Any]:
    from routing.agent import compact_tool_result_for_prompt, grounded_user_context_text, normalize
    from routing.tools import KNOWN_LOCATIONS

    result = {
        "ok": False,
        "tool": tool_name,
        "error": f"{message} No ejecutes esta herramienta con datos no dados o no resueltos; pregunta el dato mínimo o responde con límites.",
    }
    deps.blocked_tool_attempts += 1
    record_trace_event(
        event="agent_guardrail",
        name=guardrail,
        status="blocked",
        metadata={"tool": tool_name, "runtime": "pydantic_ai"},
        response_payload=result,
    )
    normalized_context = grounded_user_context_text(deps.current_message, deps.history_blocks, deps.tool_history_dicts())
    has_known_location = any(key in normalized_context for key in KNOWN_LOCATIONS)
    normalized_message = normalize(message)
    should_short_circuit = (
        "ida/vuelta" in normalized_message
        or "falta origen" in normalized_message
        or "falta el origen" in normalized_message
        or "falta destino" in normalized_message
        or "falta el destino" in normalized_message
        or (deps.blocked_tool_attempts >= 2 and not has_known_location)
    )
    if should_short_circuit:
        raise RenderableToolResult(result)
    return compact_tool_result_for_prompt(result, tool_name)


def run_pydantic_ai_decision(prompt: str) -> dict[str, Any]:
    agent = build_pydantic_ai_repair_agent()
    started = time.perf_counter()
    try:
        result = agent.run_sync(prompt)
    except Exception as exc:
        record_pydantic_ai_trace(
            status="error",
            started=started,
            prompt=prompt,
            result=None,
            error=str(exc),
            name="pydantic_ai.Agent.run_sync.repair",
        )
        raise RuntimeError(f"Pydantic AI no pudo devolver una decisión: {exc}") from exc

    record_pydantic_ai_trace(
        status="ok",
        started=started,
        prompt=prompt,
        result=result,
        error=None,
        name="pydantic_ai.Agent.run_sync.repair",
    )
    output = result.output
    return {"type": "final", **output.model_dump(exclude_none=True)}


def build_pydantic_ai_repair_agent():
    from pydantic_ai import Agent

    return Agent(
        build_pydantic_ai_model(),
        output_type=PydanticAIDecision,
        system_prompt=(
            "Devuelve una decisión estructurada para Kalmio. En reparaciones, devuelve type='final' "
            "con blocks A2UI válidos y no pidas herramientas."
        ),
        model_settings=pydantic_ai_model_settings(),
        retries=1,
    )


def record_pydantic_ai_trace(
    *,
    status: str,
    started: float,
    prompt: str,
    result: Any,
    error: str | None,
    name: str = "pydantic_ai.Agent.run_sync",
    metadata: dict[str, Any] | None = None,
) -> None:
    usage_value = None
    if result is not None:
        usage_attr = getattr(result, "usage", None)
        usage_value = usage_attr() if callable(usage_attr) else usage_attr
    usage = normalize_usage(usage_value)
    record_trace_event(
        event="llm_api_call",
        name=name,
        status=status,
        provider="deepseek",
        model=getattr(settings, "KALMIO_DEEPSEEK_MODEL", "deepseek-v4-pro"),
        duration_ms=elapsed_ms(started),
        usage=usage,
        cost=estimate_deepseek_cost(usage),
        metadata={"runtime": "pydantic_ai", **(metadata or {})},
        request_payload={"prompt": prompt},
        response_payload=to_plain(getattr(result, "output", None)) if result is not None else None,
        error=error,
    )


def emit_progress(progress_callback: ProgressCallback | None, stage: str, label: str, **metadata: Any) -> None:
    if progress_callback is None:
        return
    progress_callback({"stage": stage, "label": label, **metadata})
