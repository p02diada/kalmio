from __future__ import annotations

import json
import queue
import threading
from typing import Any, Callable

from django.db import close_old_connections
from django.http import StreamingHttpResponse
from ninja import Router
from ninja import Query
from ninja.responses import Response
from ninja.security import SessionAuth
from ninja.utils import check_csrf
from django.conf import settings

from routing.a2ui_protocol import A2UI_PROTOCOL_VERSION, action_payload_to_text, conversation_a2ui_response
from routing.agent import AgentResponseError, initial_blocks, run_conversation_agent
from routing.models import RoutePlan
from routing.production_planner import PlanningDataError, ProductionPlanResult, plan_route_with_persisted_stations
from routing.providers import Coordinate, RoutingProviderError, get_route_provider
from routing.scoring import Preferences, VehicleContext
from routing.security import (
    check_conversation_throttle,
    record_conversation_attempt,
)
from routing.schemas import (
    ConversationMessageRequest,
    ConversationMessageResponse,
    ConversationRoutePlanRequest,
    RoutePlanError,
    RoutePlanRequest,
    RoutePlanResponse,
)

router = Router(tags=["routing"])


session_auth = SessionAuth()
ACTIVE_CONVERSATION_PLAN_KEY = "active_route_plan"
ACTIVE_CONVERSATION_BLOCKS_KEY = "active_a2ui_blocks"


@router.get("/conversation/messages", response={200: ConversationMessageResponse})
def get_active_conversation_messages(request):
    blocks = request.session.get(ACTIVE_CONVERSATION_BLOCKS_KEY)
    if not blocks:
        blocks = initial_blocks()
        request.session[ACTIVE_CONVERSATION_BLOCKS_KEY] = blocks
    else:
        unique_blocks = with_unique_block_ids(blocks, [])
        if unique_blocks != blocks:
            blocks = unique_blocks
            request.session[ACTIVE_CONVERSATION_BLOCKS_KEY] = blocks
            request.session.modified = True
    return Response(conversation_a2ui_response(blocks), status=200)


@router.post(
    "/conversation/message",
    response={200: ConversationMessageResponse, 403: RoutePlanError, 422: RoutePlanError, 429: RoutePlanError, 502: RoutePlanError},
)
def create_conversation_message(request, payload: ConversationMessageRequest):
    result = prepare_conversation_message_response(request, payload)
    if isinstance(result, Response):
        return result
    try:
        body = run_conversation_turn(request, result["message_text"], result["is_action"])
    except AgentResponseError as exc:
        return Response(conversation_agent_error_payload(exc), status=502)
    return Response(body, status=200)


@router.post(
    "/conversation/message/stream",
    response={403: RoutePlanError, 422: RoutePlanError, 429: RoutePlanError},
)
def create_conversation_message_stream(request, payload: ConversationMessageRequest):
    result = prepare_conversation_message_response(request, payload)
    if isinstance(result, Response):
        return result

    current_blocks = request.session.get(ACTIVE_CONVERSATION_BLOCKS_KEY) or initial_blocks()
    events: queue.Queue[tuple[str, Any] | None] = queue.Queue()

    def progress_callback(progress: dict[str, Any]) -> None:
        events.put(("progress", progress))

    def worker() -> None:
        close_old_connections()
        try:
            new_blocks = generate_conversation_blocks(
                result["message_text"],
                current_blocks,
                progress_callback=progress_callback,
            )
        except AgentResponseError as exc:
            events.put(("error", conversation_agent_error_payload(exc)))
        except Exception:
            events.put(
                (
                    "error",
                    {
                        "detail": (
                            "No he podido completar esta respuesta con fiabilidad. "
                            "Reintenta con origen o ubicación, destino si hay ruta, batería y conector."
                        )
                    },
                )
            )
        else:
            events.put(("blocks", new_blocks))
        finally:
            close_old_connections()
            events.put(None)

    def event_stream():
        yield sse_event("progress", {"stage": "accepted", "label": "Preparando la consulta"})
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while True:
            item = events.get()
            if item is None:
                break
            event, data = item
            if event == "blocks":
                body = finalize_conversation_turn(
                    request,
                    current_blocks,
                    data,
                    result["message_text"],
                    result["is_action"],
                    save_session=True,
                )
                yield sse_event("done", body)
            else:
                yield sse_event(event, data)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def prepare_conversation_message_response(request, payload: ConversationMessageRequest):
    csrf_response = check_csrf(request)
    if csrf_response:
        return Response({"detail": "CSRF verification failed."}, status=403)
    if not request.session.session_key:
        request.session.create()

    throttle = check_conversation_throttle(request)
    if not throttle.allowed:
        return Response(
            {
                "detail": (
                    f"Demasiadas peticiones de conversación en esta sesión. "
                    f"Vuelve a intentarlo en {max(1, throttle.window_seconds // 60)} minutos."
                )
            },
            status=429,
        )
    record_conversation_attempt(request)

    message_text, is_action = conversation_message_text(payload)
    if not message_text:
        return Response({"detail": "Envía texto o una acción A2UI válida."}, status=422)

    return {"message_text": message_text, "is_action": is_action}


def run_conversation_turn(
    request,
    message_text: str,
    is_action: bool,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    save_session: bool = False,
) -> dict[str, Any]:
    current_blocks = request.session.get(ACTIVE_CONVERSATION_BLOCKS_KEY) or initial_blocks()
    new_blocks = generate_conversation_blocks(message_text, current_blocks, progress_callback=progress_callback)
    return finalize_conversation_turn(request, current_blocks, new_blocks, message_text, is_action, save_session)


def generate_conversation_blocks(
    message_text: str,
    current_blocks: list[dict[str, Any]],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    return run_conversation_agent(
        message_text,
        history_blocks=current_blocks,
        progress_callback=progress_callback,
    )


def finalize_conversation_turn(
    request,
    current_blocks: list[dict[str, Any]],
    new_blocks: list[dict[str, Any]],
    message_text: str,
    is_action: bool,
    save_session: bool = False,
) -> dict[str, Any]:
    if is_action:
        new_blocks = without_action_echo(new_blocks, message_text)

    blocks = with_unique_block_ids([*current_blocks, *new_blocks], [])
    request.session[ACTIVE_CONVERSATION_BLOCKS_KEY] = blocks[-80:]
    request.session.modified = True
    if save_session:
        request.session.save()
    return conversation_a2ui_response(request.session[ACTIVE_CONVERSATION_BLOCKS_KEY])


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def conversation_agent_error_payload(exc: AgentResponseError) -> dict[str, Any]:
    code = conversation_agent_error_code(str(exc))
    return {
        "detail": conversation_agent_error_detail(code),
        "code": code,
        "developer_detail": conversation_agent_developer_detail(code),
        "disable_input": True,
    }


def conversation_agent_error_code(reason: str) -> str:
    normalized = reason.lower()
    if "no está configurado" in normalized or "api_key" in normalized or "api key" in normalized:
        return "agent_not_configured"
    if "json" in normalized or "decisión" in normalized or "decision" in normalized:
        return "agent_invalid_response"
    if "request" in normalized or "timeout" in normalized or "conectar" in normalized or "connection" in normalized:
        return "agent_unavailable"
    return "agent_error"


def conversation_agent_error_detail(code: str) -> str:
    if code == "agent_not_configured":
        return "No puedo conectar con el agente de conversación ahora mismo. No voy a inventar recomendaciones de carga."
    if code == "agent_unavailable":
        return "El agente de conversación no está disponible ahora mismo. Reintenta cuando la conexión esté recuperada."
    if code == "agent_invalid_response":
        return "El agente no devolvió una respuesta válida para mostrar con seguridad. Reintenta en unos segundos."
    return "No he podido completar esta respuesta con el agente de conversación. Reintenta en unos segundos."


def conversation_agent_developer_detail(code: str) -> str:
    details = {
        "agent_not_configured": "Revisa KALMIO_DEEPSEEK_API_KEY/DEEPSEEK_API_KEY y KALMIO_CONVERSATION_AGENT_MODE.",
        "agent_unavailable": "Revisa conectividad con el proveedor del agente y timeouts.",
        "agent_invalid_response": "Revisa trazas del agente y validación JSON/A2UI.",
    }
    return details.get(code, "Revisa backend/.tmp/agent-traces.jsonl y la configuración del agente.")


def conversation_message_text(payload: ConversationMessageRequest) -> tuple[str, bool]:
    if payload.action is not None:
        if payload.version != A2UI_PROTOCOL_VERSION:
            return "", True
        action = schema_to_dict(payload.action)
        return action_payload_to_text(action), True
    return (payload.text or "").strip(), False


def schema_to_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)


def without_action_echo(blocks: list[dict], message_text: str) -> list[dict]:
    return [
        block
        for block in blocks
        if not (
            block.get("type") == "UserMessage"
            and isinstance(block.get("props"), dict)
            and str(block["props"].get("text") or "").strip() == message_text
        )
    ]


def with_unique_block_ids(blocks: list[dict], existing_blocks: list[dict]) -> list[dict]:
    used_ids = {
        str(block.get("id") or "").strip()
        for block in existing_blocks
        if isinstance(block, dict) and str(block.get("id") or "").strip()
    }
    unique_blocks = []
    for index, item in enumerate(blocks):
        if not isinstance(item, dict):
            unique_blocks.append(item)
            continue
        base_id = str(item.get("id") or f"block-{index}").strip() or f"block-{index}"
        block_id = base_id
        counter = 2
        while block_id in used_ids:
            block_id = f"{base_id}-{counter}"
            counter += 1
        used_ids.add(block_id)
        unique_blocks.append({**item, "id": block_id})
    return unique_blocks


@router.get("/conversation", response={200: RoutePlanResponse, 404: RoutePlanError})
def get_active_conversation(request):
    active_plan = request.session.get(ACTIVE_CONVERSATION_PLAN_KEY)
    if not active_plan:
        return Response({"detail": "No hay una conversación de ruta activa en esta sesión."}, status=404)
    return active_plan


@router.post(
    "/conversation/route",
    response={200: RoutePlanResponse, 403: RoutePlanError, 424: RoutePlanError, 422: RoutePlanError, 429: RoutePlanError},
)
def create_conversation_route_plan(request, payload: ConversationRoutePlanRequest):
    csrf_response = check_csrf(request)
    if csrf_response:
        return Response({"detail": "CSRF verification failed."}, status=403)
    if not request.session.session_key:
        request.session.create()

    throttle = check_conversation_throttle(request)
    if not throttle.allowed:
        return Response(
            {
                "detail": (
                    f"Demasiadas peticiones de ruta en esta sesión. "
                    f"Vuelve a intentarlo en {max(1, throttle.window_seconds // 60)} minutos."
                )
            },
            status=429,
        )
    record_conversation_attempt(request)

    try:
        plan = build_plan_from_payload(
            payload=payload,
            vehicle=vehicle_context_from_payload(payload),
            preferences=preferences_from_payload(payload),
        )
    except RoutingProviderError as exc:
        return Response({"detail": str(exc)}, status=424)
    except PlanningDataError as exc:
        return Response({"detail": str(exc)}, status=422)

    serialized = serialize_plan(plan, payload)
    if not request.session.session_key:
        request.session.create()
    request.session[ACTIVE_CONVERSATION_PLAN_KEY] = serialized
    return serialized


@router.delete(
    "/conversation",
    response={200: RoutePlanError, 403: RoutePlanError},
)
def delete_active_conversation(request):
    csrf_response = check_csrf(request)
    if csrf_response:
        return Response({"detail": "CSRF verification failed."}, status=403)

    request.session.pop(ACTIVE_CONVERSATION_PLAN_KEY, None)
    request.session.pop(ACTIVE_CONVERSATION_BLOCKS_KEY, None)
    request.session.save()
    return {"detail": "Conversación eliminada."}


@router.post(
    "/plans/route",
    auth=session_auth,
    response={200: RoutePlanResponse, 401: RoutePlanError, 403: RoutePlanError, 424: RoutePlanError, 422: RoutePlanError},
)
def create_route_plan(request, payload: RoutePlanRequest):
    if not request.user.is_authenticated:
        return Response({"detail": "Inicia sesión para guardar y consultar planes de ruta."}, status=401)

    csrf_response = check_csrf(request)
    if csrf_response:
        return Response({"detail": "CSRF verification failed."}, status=403)

    try:
        plan = build_plan_from_payload(payload=payload, vehicle=None, preferences=default_preferences())
    except RoutingProviderError as exc:
        return Response({"detail": str(exc)}, status=424)
    except PlanningDataError as exc:
        return Response({"detail": str(exc)}, status=422)

    if plan.planning_level == "chargers_only":
        return serialize_plan(plan, payload)

    route_plan = save_route_plan(plan, payload, request.user)
    return serialize_plan(plan, payload, route_plan)


@router.get("/plans/route", auth=session_auth, response={200: list[RoutePlanResponse], 401: RoutePlanError})
def list_route_plans(request, limit: int = Query(20, ge=1, le=100)):
    if not request.user.is_authenticated:
        return Response({"detail": "Inicia sesión para consultar tus planes de ruta."}, status=401)

    plans = RoutePlan.objects.select_related("recommendation_station").filter(user=request.user)[:limit]
    return [serialize_saved_plan(plan) for plan in plans]


def build_plan_from_payload(
    *,
    payload: RoutePlanRequest,
    vehicle: VehicleContext | None,
    preferences: Preferences,
) -> ProductionPlanResult:
    origin = Coordinate(lat=payload.origin.lat, lon=payload.origin.lon)
    destination = Coordinate(lat=payload.destination.lat, lon=payload.destination.lon)
    route = get_route_provider().route(origin, destination)
    return plan_route_with_persisted_stations(
        origin=origin,
        destination=destination,
        route=route,
        vehicle=vehicle,
        preferences=preferences,
        corridor_radius_km=payload.corridor_radius_km,
    )


def save_route_plan(plan: ProductionPlanResult, payload: RoutePlanRequest, user) -> RoutePlan:
    if plan.planning_level != "ev_plan" or plan.energy_kwh is None or plan.arrival_battery_percent is None:
        raise PlanningDataError("Solo los planes EV completos se pueden guardar en el historial.")

    serialized = serialize_plan(plan, payload)
    return RoutePlan.objects.create(
        user=user,
        origin_label=payload.origin_label,
        destination_label=payload.destination_label,
        origin_latitude=payload.origin.lat,
        origin_longitude=payload.origin.lon,
        destination_latitude=payload.destination.lat,
        destination_longitude=payload.destination.lon,
        distance_km=plan.route.distance_km,
        duration_min=plan.route.duration_min,
        energy_kwh=plan.energy_kwh,
        arrival_battery_percent=plan.arrival_battery_percent,
        recommendation_station_id=plan.recommendation.station["id"],
        recommendation_snapshot=serialized["recommendation"],
        alternatives_snapshot=serialized["alternatives"],
        warnings=serialized["warnings"],
        request_payload=payload.dict(),
    )


def default_preferences() -> Preferences:
    return Preferences(
        reserve_min_percent=20,
        prefer_fast=False,
        prefer_cheap=False,
        prefer_low_stress=True,
        prefer_services=True,
        prefer_large_hubs=True,
        avoid_single_connector=True,
        max_useful_power_kw=None,
    )


def vehicle_context_from_payload(payload: ConversationRoutePlanRequest) -> VehicleContext | None:
    if payload.vehicle is None:
        return None
    return VehicleContext(
        battery_percent=payload.vehicle.battery,
        usable_battery_kwh=payload.vehicle.usable_battery_kwh,
        consumption_kwh_per_100km=payload.vehicle.consumption_kwh_per_100km,
        connector=payload.vehicle.connector,
        max_charge_kw=payload.vehicle.max_charge_kw,
    )


def preferences_from_payload(payload: ConversationRoutePlanRequest) -> Preferences:
    return Preferences(
        reserve_min_percent=payload.preferences.reserve_min_percent,
        prefer_fast=payload.preferences.prefer_fast,
        prefer_cheap=payload.preferences.prefer_cheap,
        prefer_low_stress=payload.preferences.prefer_low_stress,
        prefer_services=payload.preferences.prefer_services,
        prefer_large_hubs=payload.preferences.prefer_large_hubs,
        avoid_single_connector=payload.preferences.avoid_single_connector,
        max_useful_power_kw=payload.preferences.max_useful_power_kw,
    )


def serialize_plan(plan: ProductionPlanResult, payload: RoutePlanRequest, route_plan: RoutePlan | None = None) -> dict:
    warnings = [
        *plan.warnings,
        "El tiempo de acceso al punto de carga se estima por distancia a la geometría de ruta; confirma navegación final.",
    ]
    if plan.planning_level == "chargers_only":
        warnings.append("No uses esta respuesta como garantía de llegada: no hay datos de autonomía ni compatibilidad.")

    recommendation = serialize_station(plan.recommendation)
    alternatives = [serialize_station(station) for station in plan.alternatives]
    return {
        "id": str(route_plan.public_id) if route_plan else None,
        "created_at": route_plan.created_at if route_plan else None,
        "planning_level": plan.planning_level,
        "origin_label": payload.origin_label,
        "destination_label": payload.destination_label,
        "distance_km": plan.route.distance_km,
        "duration_min": plan.route.duration_min,
        "energy_kwh": plan.energy_kwh,
        "arrival_battery_percent": plan.arrival_battery_percent,
        "recommendation": recommendation,
        "alternatives": alternatives,
        "warnings": warnings,
        "route_provider": route_provider_result(plan, payload),
        "corridor_stations": corridor_stations_result(payload.corridor_radius_km, recommendation, alternatives),
        "energy_validation": energy_validation_result(plan, payload),
        "ranking": ranking_result(recommendation, alternatives),
        "unsatisfied_constraints": plan.unsatisfied_constraints,
    }


def serialize_saved_plan(route_plan: RoutePlan) -> dict:
    recommendation = route_plan.recommendation_snapshot
    alternatives = route_plan.alternatives_snapshot
    return {
        "id": str(route_plan.public_id),
        "created_at": route_plan.created_at,
        "planning_level": "ev_plan",
        "origin_label": route_plan.origin_label,
        "destination_label": route_plan.destination_label,
        "distance_km": float(route_plan.distance_km),
        "duration_min": route_plan.duration_min,
        "energy_kwh": float(route_plan.energy_kwh),
        "arrival_battery_percent": float(route_plan.arrival_battery_percent),
        "recommendation": recommendation,
        "alternatives": alternatives,
        "warnings": route_plan.warnings,
        "route_provider": {
            "provider": "stored",
            "origin": {
                "label": route_plan.origin_label,
                "lat": float(route_plan.origin_latitude),
                "lon": float(route_plan.origin_longitude),
            },
            "destination": {
                "label": route_plan.destination_label,
                "lat": float(route_plan.destination_latitude),
                "lon": float(route_plan.destination_longitude),
            },
            "distance_km": float(route_plan.distance_km),
            "duration_min": route_plan.duration_min,
            "geometry_precision": "not_stored",
        },
        "corridor_stations": corridor_stations_result(None, recommendation, alternatives),
        "energy_validation": {
            "status": "validated",
            "planning_level": "ev_plan",
            "energy_kwh": float(route_plan.energy_kwh),
            "arrival_battery_percent": float(route_plan.arrival_battery_percent),
            "reserve_min_percent": None,
            "warnings": route_plan.warnings,
        },
        "ranking": ranking_result(recommendation, alternatives),
        "unsatisfied_constraints": [],
    }


def serialize_station(station_score) -> dict:
    station = station_score.station
    return {
        "id": station["id"],
        "external_id": station["external_id"],
        "name": station["name"],
        "power_kw": station["power_kw"],
        "connector": station["connector"],
        "available_connectors": station["available_connectors"],
        "distance_to_route_km": station["distance_to_route_km"],
        "estimated_access_min": station["detour_min"],
        "price_eur_kwh": station["price_eur_kwh"],
        "price_is_estimated": station["price_is_estimated"],
        "latitude": station["lat"],
        "longitude": station["lon"],
        "score": station_score.score,
        "reasons": station_score.reasons,
    }


def route_provider_result(plan: ProductionPlanResult, payload: RoutePlanRequest) -> dict:
    return {
        "provider": "configured_route_provider",
        "origin": {
            "label": payload.origin_label,
            "lat": payload.origin.lat,
            "lon": payload.origin.lon,
        },
        "destination": {
            "label": payload.destination_label,
            "lat": payload.destination.lat,
            "lon": payload.destination.lon,
        },
        "distance_km": plan.route.distance_km,
        "duration_min": plan.route.duration_min,
        "geometry_precision": "provider",
    }


def corridor_stations_result(corridor_radius_km: float | None, recommendation: dict, alternatives: list[dict]) -> dict:
    stations = [recommendation, *alternatives]
    return {
        "corridor_radius_km": corridor_radius_km,
        "stations": stations,
        "station_count": len(stations),
        "source": "authorized_charger_imports",
    }


def energy_validation_result(plan: ProductionPlanResult, payload: RoutePlanRequest) -> dict:
    reserve_min_percent = getattr(getattr(payload, "preferences", None), "reserve_min_percent", None)
    return {
        "status": "validated" if plan.planning_level == "ev_plan" else "not_validated",
        "planning_level": plan.planning_level,
        "energy_kwh": plan.energy_kwh,
        "arrival_battery_percent": plan.arrival_battery_percent,
        "reserve_min_percent": reserve_min_percent,
        "warnings": plan.warnings,
    }


def ranking_result(recommendation: dict, alternatives: list[dict]) -> dict:
    ranked = [recommendation, *alternatives]
    return {
        "primary_station_id": recommendation.get("id"),
        "candidates": [
            {
                "station_id": station.get("id"),
                "external_id": station.get("external_id"),
                "name": station.get("name"),
                "score": station.get("score"),
                "reasons": station.get("reasons", []),
            }
            for station in ranked
        ],
    }
