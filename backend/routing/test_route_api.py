import json
from datetime import timedelta
from decimal import Decimal

import pytest
from accounts.models import AuthThrottle
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from charging.models import AvailabilitySnapshot, Connector, DataSource, EVSE, Operator, ReliabilityScore, Station, Tariff
from routing.a2ui_protocol import A2UI_PROTOCOL_VERSION, KALMIO_A2UI_CATALOG_ID, KALMIO_A2UI_SURFACE_ID
from routing.api import ACTIVE_CONVERSATION_BLOCKS_KEY
from routing.agent import (
    AgentResponseError,
    a2ui_contract_issues,
    blocks_from_tool_result,
    codex_prompt,
    contextualized_prompt,
    decode_codex_json,
    parse_openai_compatible_decision,
    run_deepseek_decision,
    validate_blocks,
)
from routing.instrumentation import estimate_deepseek_cost, record_trace_event
from routing.models import RoutePlan
from routing.production_planner import score_exploration_station, station_to_score_payload
from routing.providers import Coordinate, ProviderRoute, RoutingProviderError
from routing.scoring import Preferences
from routing.tools import parse_preferences_arg, resolve_location_tool, search_destination_chargers_tool


class StaticRouteProvider:
    def route(self, origin: Coordinate, destination: Coordinate) -> ProviderRoute:
        return ProviderRoute(
            distance_km=520,
            duration_min=355,
            geometry=[
                origin,
                Coordinate(lat=38.35, lon=-2.4),
                Coordinate(lat=38.85, lon=-1.1),
                destination,
            ],
        )


class FailingRouteProvider:
    def route(self, origin: Coordinate, destination: Coordinate) -> ProviderRoute:
        raise RoutingProviderError("proveedor no disponible")


def route_payload(**overrides):
    payload = {
        "origin": {"lat": 37.8882, "lon": -4.7794},
        "destination": {"lat": 39.4699, "lon": -0.3763},
        "origin_label": "Córdoba",
        "destination_label": "Valencia",
        "corridor_radius_km": 35,
    }
    payload.update(overrides)
    return payload


def conversation_payload(**overrides):
    payload = {
        **route_payload(),
        "vehicle": {
            "model": "Mi EV",
            "battery": 58,
            "usable_battery_kwh": 64,
            "consumption_kwh_per_100km": 17.8,
            "connector": "CCS2",
            "max_charge_kw": 150,
        },
        "preferences": {
            "reserve_min_percent": 20,
            "prefer_fast": False,
            "prefer_cheap": False,
            "prefer_low_stress": True,
            "prefer_services": True,
            "prefer_large_hubs": True,
            "avoid_single_connector": True,
        },
    }
    payload.update(overrides)
    return payload


def blocks_from_a2ui_response(response_or_payload):
    payload = response_or_payload.json() if hasattr(response_or_payload, "json") else response_or_payload
    blocks = []
    for message in payload["messages"]:
        update_components = message.get("updateComponents")
        if not isinstance(update_components, dict):
            continue
        for component in update_components.get("components", []):
            props = {
                key: value
                for key, value in component.items()
                if key not in {"id", "component", "version"}
            }
            blocks.append(
                {
                    "id": component["id"],
                    "type": component["component"],
                    "version": component.get("version", 1),
                    "props": props,
                }
            )
    return blocks


@pytest.fixture
def real_station(db):
    source = DataSource.objects.create(name="Authorized provider", kind="ocpi", is_authorized=True)
    operator = Operator.objects.create(name="Real Operator")
    station = Station.objects.create(
        external_id="real-almansa-001",
        operator=operator,
        data_source=source,
        name="Almansa HPC",
        address="A-31 Almansa",
        latitude=Decimal("38.870000"),
        longitude=Decimal("-1.090000"),
        amenities=["restaurant", "bathroom"],
        is_sample_data=False,
    )
    evse = EVSE.objects.create(station=station, evse_uid="real-almansa-001-1", max_power_kw=180, status="available")
    Connector.objects.create(evse=evse, connector_type="CCS2", max_power_kw=180)
    Tariff.objects.create(station=station, price_per_kwh=Decimal("0.490"), is_estimated=False)
    ReliabilityScore.objects.create(station=station, score=88, reasons=["provider_history"])
    return station


@pytest.fixture
def route_user(db):
    return get_user_model().objects.create_user(username="driver@example.com", email="driver@example.com", password="safe-password-123")


@pytest.fixture(autouse=True)
def clear_conversation_throttles(db):
    AuthThrottle.objects.all().delete()
    yield
    AuthThrottle.objects.all().delete()


@pytest.mark.django_db
def test_anonymous_session_can_create_and_read_active_conversation(client, monkeypatch, real_station):
    monkeypatch.setattr("routing.api.get_route_provider", lambda: StaticRouteProvider())

    response = client.post(
        "/api/conversation/route",
        data=conversation_payload(),
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] is None
    assert body["created_at"] is None
    assert body["planning_level"] == "ev_plan"
    assert body["recommendation"]["external_id"] == real_station.external_id
    assert "La ruta completa necesita carga" in body["warnings"][0]
    assert RoutePlan.objects.count() == 0

    conversation_response = client.get("/api/conversation")
    assert conversation_response.status_code == 200
    assert conversation_response.json()["recommendation"]["external_id"] == real_station.external_id


@pytest.mark.django_db
def test_conversation_messages_initializes_a2ui_blocks(client):
    response = client.get("/api/conversation/messages")

    assert response.status_code == 200
    body = response.json()
    assert body["messages"][0] == {
        "version": A2UI_PROTOCOL_VERSION,
        "createSurface": {
            "surfaceId": KALMIO_A2UI_SURFACE_ID,
            "catalogId": KALMIO_A2UI_CATALOG_ID,
            "sendDataModel": True,
        },
    }
    assert body["messages"][1]["updateComponents"]["surfaceId"] == KALMIO_A2UI_SURFACE_ID
    assert body["messages"][1]["updateComponents"]["components"][0]["component"] == "AssistantMessage"
    assert body["messages"][2]["updateDataModel"]["path"] == "/"
    blocks = blocks_from_a2ui_response(body)
    assert blocks[0]["type"] == "AssistantMessage"
    assert blocks[1]["type"] == "PreferenceChips"
    assert "blocks" not in body


@pytest.mark.django_db
def test_conversation_message_accepts_a2ui_action_transport_without_visible_action_echo(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        assert 'Acción A2UI: refine_search con contexto {"radiusKm": 80}' in message
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "assistant-action-result",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {"text": "Amplío la búsqueda a 80 km."},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={
            "version": A2UI_PROTOCOL_VERSION,
            "action": {
                "name": "refine_search",
                "surfaceId": KALMIO_A2UI_SURFACE_ID,
                "sourceComponentId": "actions-1",
                "timestamp": "2026-06-15T20:00:00.000Z",
                "context": {"radiusKm": 80},
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["messages"][1]["updateComponents"]["components"][-1]["component"] == "AssistantMessage"
    assert not any(
        block["type"] == "UserMessage" and "Acción A2UI" in block["props"].get("text", "")
        for block in blocks_from_a2ui_response(body)
    )


@pytest.mark.django_db
def test_conversation_message_handles_destination_charging_without_route_planner(client, real_station):
    response = client.post(
        "/api/conversation/message",
        data={"text": "Quiero cargadores cerca de un hotel en Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    block_types = [block["type"] for block in blocks_from_a2ui_response(body)]
    assert "UserMessage" in block_types
    assert "DestinationChargingCard" in block_types
    assert "LocationDetailCard" in block_types
    assert "RouteSummaryCard" not in block_types
    assert RoutePlan.objects.count() == 0


@pytest.mark.django_db
def test_location_detail_card_normalizes_embedded_location_text():
    blocks = validate_blocks(
        [
            {
                "id": "location-detail",
                "type": "LocationDetailCard",
                "version": 1,
                "props": {
                    "location": "{'label': 'Córdoba', 'lat': 37.8882, 'lon': -4.7794}",
                    "lat": 37.8882,
                    "lon": -4.7794,
                },
            }
        ]
    )

    assert blocks[0]["props"]["label"] == "Córdoba"
    assert blocks[0]["props"]["precision"] == "approximate"
    assert blocks[0]["props"]["needsConfirmation"] is True


def test_urgent_charge_card_normalizes_nested_recommended_stop():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "UrgentChargeCard",
                "version": 1,
                "props": {
                    "batteryPercent": 18,
                    "recommendedStop": {
                        "name": "BALLENOIL-ES336090-COLON",
                        "distanceKm": 0.3,
                    },
                },
            }
        ]
    )

    assert blocks[0]["props"] == {
        "battery": 18,
        "nearest": "BALLENOIL-ES336090-COLON",
        "distanceKm": 0.3,
    }


def test_urgent_charge_card_normalizes_name_variant_from_codex():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "UrgentChargeCard",
                "version": 1,
                "props": {
                    "name": "BALLENOIL-ES336090-COLON",
                    "distanceKm": 0.3,
                },
            }
        ]
    )

    assert blocks[0]["props"]["nearest"] == "BALLENOIL-ES336090-COLON"
    assert blocks[0]["props"]["distanceKm"] == 0.3


def test_urgent_charge_card_normalizes_station_name_variant_from_codex():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "UrgentChargeCard",
                "version": 1,
                "props": {
                    "stationName": "BALLENOIL-ES336090-COLON",
                    "distanceKm": 0.3,
                },
            }
        ]
    )

    assert blocks[0]["props"]["nearest"] == "BALLENOIL-ES336090-COLON"


def test_destination_charging_card_normalizes_hotel_location_label():
    blocks = validate_blocks(
        [
            {
                "id": "destination",
                "type": "DestinationChargingCard",
                "version": 1,
                "props": {"locationLabel": "Valencia centro", "needsConfirmation": True},
            }
        ]
    )

    assert blocks[0]["props"]["destination"] == "Valencia centro"


def test_stay_planning_card_normalizes_stay_variants_and_extracts_primary_stop():
    blocks = validate_blocks(
        [
            {
                "id": "stay",
                "type": "StayPlanningCard",
                "version": 1,
                "props": {
                    "durationText": "1 semana",
                    "locationLabel": "Cádiz",
                    "primaryStop": {
                        "name": "ONCE DZ Cádiz",
                        "powerKw": 22,
                        "distanceKm": 0.23,
                    },
                },
            }
        ]
    )

    assert blocks[0]["props"] == {"nights": 7, "city": "Cádiz", "recommendation": "ONCE DZ Cádiz"}
    assert blocks[1]["type"] == "RecommendedStopCard"
    assert blocks[1]["props"]["name"] == "ONCE DZ Cádiz"


def test_urgent_tool_fallback_preserves_user_battery():
    blocks = blocks_from_tool_result(
        {
            "ok": True,
            "tool": "search_destination_chargers",
            "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
            "stops": [{"name": "Córdoba Centro HPC", "distanceKm": 1.4, "powerKw": 150}],
        },
        message="Necesito cargar ya. Estoy en Córdoba con un 18%",
    )

    urgent_block = next(block for block in blocks if block["type"] == "UrgentChargeCard")
    assert urgent_block["props"]["battery"] == 18


def test_resolve_location_tool_accepts_accented_city_inside_zone_text():
    result = resolve_location_tool({"query": "Paseo de la Victoria de Córdoba"})

    assert result == {"ok": True, "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794}}


def test_resolve_location_tool_knows_new_route_matrix_cities():
    assert resolve_location_tool({"query": "Málaga"})["location"]["label"] == "Málaga"
    assert resolve_location_tool({"query": "Bilbao"})["location"]["label"] == "Bilbao"
    assert resolve_location_tool({"query": "Almansa"})["location"]["label"] == "Almansa"
    assert resolve_location_tool({"query": "cerca de la Alhambra"})["location"]["label"] == "Alhambra, Granada"


@pytest.mark.django_db
def test_search_destination_chargers_tool_exposes_traced_comfort_and_reliability(real_station):
    result = search_destination_chargers_tool(
        {
            "location": {"label": "Almansa", "lat": 38.87, "lon": -1.09},
            "connector": "CCS2",
            "radius_km": 5,
            "limit": 1,
        }
    )

    stop = result["stops"][0]
    assert stop["name"] == real_station.name
    assert stop["amenities"] == ["restaurant", "bathroom"]
    assert stop["reliability"] == 88
    assert stop["address"] == "A-31 Almansa"


def test_parse_preferences_arg_accepts_max_useful_power_cap():
    preferences = parse_preferences_arg({"reserve_min_percent": 20, "max_useful_power_kw": 100})

    assert preferences.max_useful_power_kw == 100


def test_score_exploration_station_does_not_overweight_power_above_user_cap():
    station = {
        "power_kw": 240,
        "available_connectors": 2,
        "connector_count": 2,
        "availability_age_min": 10,
        "reliability": 70,
        "detour_min": 2,
        "price_eur_kwh": None,
        "services": [],
    }
    preferences = Preferences(
        reserve_min_percent=20,
        prefer_fast=False,
        prefer_cheap=False,
        prefer_low_stress=True,
        prefer_services=True,
        prefer_large_hubs=True,
        avoid_single_connector=True,
    )

    uncapped = score_exploration_station(station, preferences, "safe")
    capped = score_exploration_station(
        station,
        Preferences(**{**preferences.__dict__, "max_useful_power_kw": 100}),
        "safe",
    )

    assert "Alta potencia" in uncapped.reasons
    assert "Alta potencia" not in capped.reasons
    assert "Carga rápida" in capped.reasons
    assert "Potencia por encima del máximo útil no sobreponderada" in capped.reasons
    assert capped.score < uncapped.score


def test_codex_prompt_guides_followups_without_backend_intent_mapping():
    prompt = codex_prompt("Me equivoqué, estoy en Valencia centro")

    assert "No pidas destino para una carga urgente" in prompt
    assert "Si el usuario corrige la ubicación" in prompt
    assert "conserva batería, conector y preferencias" in prompt
    assert "no puedes ubicar esa calle exacta" in prompt
    assert "sin perfil de vehículo" in prompt
    assert "planningLevel=chargers_only" in prompt
    assert "DestinationChargingCard + AlternativeStopsList" in prompt
    assert "preferences.max_useful_power_kw" in prompt
    assert "no presentes la potencia superior como ventaja" in prompt


def test_codex_prompt_exposes_max_useful_power_tool_argument():
    prompt = codex_prompt("Mi coche carga máximo a 100 kW, no necesito ultrarrápidos")

    assert '"max_useful_power_kw":null' in prompt
    assert "pasa X como preferences.max_useful_power_kw" in prompt
    assert "que el coche no aprovechará más de 100 kW" in prompt


def test_decode_codex_json_accepts_stdout_when_output_file_is_empty():
    payload = decode_codex_json("", '{"type":"tool_call","tool":"resolve_location","args":{"query":"Córdoba"}}')

    assert payload["type"] == "tool_call"
    assert payload["args"]["query"] == "Córdoba"


def test_decode_codex_json_extracts_fenced_or_wrapped_json():
    fenced = '```json\n{"type":"final","blocks":[]}\n```'
    wrapped = 'Respuesta:\n{"type":"final","blocks":[]}\nFin.'

    assert decode_codex_json(fenced)["type"] == "final"
    assert decode_codex_json(wrapped)["blocks"] == []


def test_deepseek_decision_parser_accepts_native_tool_call():
    decision = parse_openai_compatible_decision(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "resolve_location",
                        "arguments": '{"query":"Córdoba"}',
                    }
                }
            ]
        }
    )

    assert decision == {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Córdoba"}}


def test_deepseek_decision_parser_accepts_json_final_content():
    decision = parse_openai_compatible_decision(
        {
            "content": (
                '{"type":"final","blocks":[{"id":"assistant","type":"AssistantMessage",'
                '"version":1,"props":{"text":"Respuesta validable."}}]}'
            )
        }
    )

    assert decision["type"] == "final"
    assert decision["blocks"][0]["type"] == "AssistantMessage"


def test_deepseek_repair_decision_disables_native_tools(monkeypatch):
    calls = []

    def fake_deepseek_decision(prompt, allow_tools=True):
        calls.append((prompt, allow_tools))
        return {"type": "final", "blocks": []}

    monkeypatch.setattr("routing.agent.call_deepseek_decision", fake_deepseek_decision)

    decision = run_deepseek_decision(
        "Busca cargadores cerca de Valencia",
        repair_issues=["AlternativeStopsList necesita datos trazables."],
        candidate_blocks=[],
    )

    assert decision["type"] == "final"
    assert calls[0][1] is False


def test_deepseek_cost_estimate_uses_provider_cache_breakdown(settings):
    settings.KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_HIT_PER_MILLION_USD = 0.0028
    settings.KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_MISS_PER_MILLION_USD = 0.14
    settings.KALMIO_DEEPSEEK_PRICE_OUTPUT_PER_MILLION_USD = 0.28

    cost = estimate_deepseek_cost(
        {
            "inputTokens": 10_000,
            "cacheHitInputTokens": 4_000,
            "cacheMissInputTokens": 6_000,
            "outputTokens": 2_000,
        }
    )

    assert cost["basis"] == "provider_cache_breakdown"
    assert cost["totalCostUsd"] == 0.0014112


def test_agent_trace_writes_jsonl_without_payloads_by_default(settings, tmp_path):
    trace_file = tmp_path / "agent-traces.jsonl"
    settings.KALMIO_AGENT_TRACE_ENABLED = True
    settings.KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS = False
    settings.KALMIO_AGENT_TRACE_FILE = str(trace_file)

    record_trace_event(
        event="llm_api_call",
        name="chat.completions.create",
        status="ok",
        provider="deepseek",
        model="deepseek-v4-flash",
        request_payload={"api_key": "secret", "prompt": "hola"},
        response_payload={"content": "respuesta"},
    )

    payload = json.loads(trace_file.read_text(encoding="utf-8").strip())
    assert payload["event"] == "llm_api_call"
    assert "request" not in payload
    assert "response" not in payload


def test_contextualized_prompt_summarizes_explicit_vehicle_facts_for_codex():
    prompt = contextualized_prompt(
        "Me equivoqué, estoy en Valencia centro",
        [
            {
                "id": "user-1",
                "type": "UserMessage",
                "version": 1,
                "props": {"text": "Necesito cargar ya. Estoy en Córdoba con un 18% y CCS2"},
            }
        ],
    )

    assert "batería 18%" in prompt
    assert "conector CCS2" in prompt
    assert "Mensaje actual del usuario: Me equivoqué, estoy en Valencia centro" in prompt


def test_contextualized_prompt_adds_known_location_hint_for_hotel_followup():
    prompt = contextualized_prompt(
        "Hotel Meliá cordoba",
        [
            {
                "id": "clarify-hotel",
                "type": "ClarifyingQuestionCard",
                "version": 1,
                "props": {"question": "¿Qué hotel o zona exacta?", "fields": ["hotel", "city_or_zone"]},
            }
        ],
    )

    assert "Pista de ubicación conocida detectada en el mensaje actual" in prompt
    assert "Córdoba (37.8882, -4.7794)" in prompt
    assert "no una decisión de intención" in prompt


@pytest.mark.django_db
def test_conversation_message_preserves_urgent_charge_intent_for_location_followup(client):
    source = DataSource.objects.create(name="Authorized provider Córdoba", kind="ocpi", is_authorized=True)
    operator = Operator.objects.create(name="Córdoba Operator")
    station = Station.objects.create(
        external_id="real-cordoba-001",
        operator=operator,
        data_source=source,
        name="Córdoba Centro HPC",
        address="Córdoba",
        latitude=Decimal("37.890000"),
        longitude=Decimal("-4.780000"),
        amenities=["bathroom"],
        is_sample_data=False,
    )
    evse = EVSE.objects.create(station=station, evse_uid="real-cordoba-001-1", max_power_kw=150, status="available")
    Connector.objects.create(evse=evse, connector_type="CCS2", max_power_kw=150)
    ReliabilityScore.objects.create(station=station, score=84, reasons=["provider_history"])

    first_response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya"},
        content_type="application/json",
    )

    assert first_response.status_code == 200
    assert blocks_from_a2ui_response(first_response)[-1]["type"] == "LocationRequestCard"

    second_response = client.post(
        "/api/conversation/message",
        data={"text": "En cordoba"},
        content_type="application/json",
    )

    assert second_response.status_code == 200
    blocks = blocks_from_a2ui_response(second_response)
    latest_user_index = max(
        index
        for index, item in enumerate(blocks)
        if item["type"] == "UserMessage" and item["props"]["text"] == "En cordoba"
    )
    new_blocks = blocks[latest_user_index + 1 :]
    new_block_types = [block["type"] for block in new_blocks]
    assert "UrgentChargeCard" in new_block_types
    assert "AlternativeStopsList" in new_block_types
    assert "ClarifyingQuestionCard" not in new_block_types
    assert "LocationRequestCard" not in new_block_types
    urgent_block = next(block for block in new_blocks if block["type"] == "UrgentChargeCard")
    assert urgent_block["props"]["nearest"] == station.name


@pytest.mark.django_db
def test_codex_hotel_followup_with_known_city_can_search_from_location_hint(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    source = DataSource.objects.create(name="Authorized provider Córdoba", kind="ocpi", is_authorized=True)
    operator = Operator.objects.create(name="Córdoba Operator")
    station = Station.objects.create(
        external_id="real-cordoba-hotel-001",
        operator=operator,
        data_source=source,
        name="Córdoba Centro Hotel HPC",
        address="Córdoba",
        latitude=Decimal("37.890000"),
        longitude=Decimal("-4.780000"),
        amenities=["hotel"],
        is_sample_data=False,
    )
    evse = EVSE.objects.create(station=station, evse_uid="real-cordoba-hotel-001-1", max_power_kw=150, status="available")
    Connector.objects.create(evse=evse, connector_type="CCS2", max_power_kw=150)
    messages_seen = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        messages_seen.append(message)
        if "Hotel Meliá cordoba" not in message:
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "clarify-hotel",
                        "type": "ClarifyingQuestionCard",
                        "version": 1,
                        "props": {
                            "question": "¿Qué hotel o qué ciudad/zona quieres usar?",
                            "fields": ["Nombre del hotel", "Ciudad o zona"],
                        },
                    }
                ],
            }
        if not tool_history:
            assert "Pista de ubicación conocida detectada en el mensaje actual" in message
            assert "Córdoba (37.8882, -4.7794)" in message
            return {
                "type": "tool_call",
                "tool": "search_destination_chargers",
                "args": {
                    "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                    "radius_km": 80,
                    "limit": 3,
                },
            }
        tool_result = tool_history[-1]["result"]
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "destination-cordoba",
                    "type": "DestinationChargingCard",
                    "version": 1,
                    "props": {"destination": "Córdoba", "needsConfirmation": True},
                },
                {
                    "id": "stops-cordoba",
                    "type": "AlternativeStopsList",
                    "version": 1,
                    "props": {"stops": tool_result["stops"]},
                },
                {
                    "id": "risk-cordoba",
                    "type": "RiskExplanationCard",
                    "version": 1,
                    "props": {
                        "level": "medio",
                        "text": "Confirma acceso final, tarifa y disponibilidad antes de depender de estos cargadores.",
                    },
                },
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    first_response = client.post(
        "/api/conversation/message",
        data={"text": "Cargadores cerca del hotel"},
        content_type="application/json",
    )
    assert first_response.status_code == 200

    second_response = client.post(
        "/api/conversation/message",
        data={"text": "Hotel Meliá cordoba"},
        content_type="application/json",
    )

    assert second_response.status_code == 200
    assert len(messages_seen) == 3
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks_from_a2ui_response(second_response))
    assert "No he podido completar esta respuesta con fiabilidad" not in rendered_text
    assert station.name in rendered_text


@pytest.mark.django_db
def test_local_conversation_uses_history_for_followup_after_urgent_recommendation(client):
    source = DataSource.objects.create(name="Authorized provider Córdoba", kind="ocpi", is_authorized=True)
    operator = Operator.objects.create(name="Córdoba Operator")
    station = Station.objects.create(
        external_id="real-cordoba-002",
        operator=operator,
        data_source=source,
        name="Córdoba Centro HPC",
        address="Córdoba",
        latitude=Decimal("37.880900"),
        longitude=Decimal("-4.782300"),
        amenities=["bathroom"],
        is_sample_data=False,
    )
    evse = EVSE.objects.create(station=station, evse_uid="real-cordoba-002-1", max_power_kw=150, status="available")
    Connector.objects.create(evse=evse, connector_type="CCS2", max_power_kw=150)
    ReliabilityScore.objects.create(station=station, score=84, reasons=["provider_history"])

    client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya"},
        content_type="application/json",
    )
    location_response = client.post(
        "/api/conversation/message",
        data={"text": "Estoy en 37.880729, -4.782446"},
        content_type="application/json",
    )
    assert location_response.status_code == 200
    assert any(block["type"] == "UrgentChargeCard" for block in blocks_from_a2ui_response(location_response))

    battery_response = client.post(
        "/api/conversation/message",
        data={"text": "Tengo un 20%"},
        content_type="application/json",
    )

    assert battery_response.status_code == 200
    blocks = blocks_from_a2ui_response(battery_response)
    latest_user_index = max(
        index
        for index, item in enumerate(blocks)
        if item["type"] == "UserMessage" and item["props"]["text"] == "Tengo un 20%"
    )
    new_blocks = blocks[latest_user_index + 1 :]
    new_block_types = [block["type"] for block in new_blocks]
    assert "UrgentChargeCard" in new_block_types
    assert "AlternativeStopsList" in new_block_types
    assert "ClarifyingQuestionCard" not in new_block_types

    urgent_block = next(block for block in new_blocks if block["type"] == "UrgentChargeCard")
    assert urgent_block["props"]["nearest"] == station.name


@pytest.mark.django_db
def test_codex_conversation_agent_interprets_vehicle_followup_from_available_transcript(
    client, settings, monkeypatch
):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    captured_messages = []
    session = client.session
    session[ACTIVE_CONVERSATION_BLOCKS_KEY] = [
        {"id": "user-urgent", "type": "UserMessage", "version": 1, "props": {"text": "Necesito cargar ya"}},
        {
            "id": "location-request",
            "type": "LocationRequestCard",
            "version": 1,
            "props": {
                "reason": "urgent_charge",
                "title": "Necesito tu ubicación",
                "body": "Comparte ubicación para buscar cargadores.",
            },
        },
        {
            "id": "user-location",
            "type": "UserMessage",
            "version": 1,
            "props": {"text": "Estoy en 37.880729, -4.782446"},
        },
        {
            "id": "urgent-result",
            "type": "UrgentChargeCard",
            "version": 1,
            "props": {"battery": None, "nearest": "Eurostars Maimonides - 135", "distanceKm": 0.16},
        },
    ]
    session.save()

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        captured_messages.append(message)
        blocks = [
            {
                "id": "urgent-with-battery",
                "type": "UrgentChargeCard",
                "version": 1,
                "props": {
                    "battery": 20,
                    "nearest": "Eurostars Maimonides - 135",
                    "distanceKm": 0.16,
                },
            }
        ]
        if repair_issues:
            blocks.append(
                {
                    "id": "urgent-risk",
                    "type": "RiskExplanationCard",
                    "version": 1,
                    "props": {
                        "level": "medio",
                        "text": "Confirma acceso final, tarifa y disponibilidad antes de depender del cargador.",
                    },
                }
            )
        return {
            "type": "final",
            "blocks": blocks,
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Tengo un 20%"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert captured_messages
    assert "Usuario: Necesito cargar ya" in captured_messages[0]
    assert "Usuario: Estoy en 37.880729, -4.782446" in captured_messages[0]
    assert "Resultado previo de carga urgente" in captured_messages[0]
    assert "Mensaje actual del usuario: Tengo un 20%" in captured_messages[0]
    latest_urgent_block = next(
        block for block in reversed(blocks_from_a2ui_response(response)) if block["type"] == "UrgentChargeCard"
    )
    assert latest_urgent_block["props"]["battery"] == 20


@pytest.mark.django_db
def test_codex_conversation_agent_does_not_repair_component_choice_from_urgent_history(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []
    session = client.session
    session[ACTIVE_CONVERSATION_BLOCKS_KEY] = [
        {"id": "user-urgent", "type": "UserMessage", "version": 1, "props": {"text": "Necesito cargar ya"}},
        {
            "id": "location-request",
            "type": "LocationRequestCard",
            "version": 1,
            "props": {
                "reason": "urgent_charge",
                "title": "Necesito tu ubicación",
                "body": "Comparte ubicación para buscar cargadores.",
            },
        },
    ]
    session.save()

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        if repair_issues:
            repair_requests.append(repair_issues)
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "wrong-destination",
                    "type": "DestinationChargingCard",
                    "version": 1,
                    "props": {"destination": "Córdoba", "needsConfirmation": True},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Estoy en Córdoba con un 18%"},
        content_type="application/json",
    )

    assert response.status_code == 200
    new_blocks = blocks_from_a2ui_response(response)[len(session[ACTIVE_CONVERSATION_BLOCKS_KEY]) :]
    block_types = [block["type"] for block in new_blocks]
    assert repair_requests == []
    assert "DestinationChargingCard" in block_types
    assert "UrgentChargeCard" not in block_types


@pytest.mark.django_db
def test_codex_conversation_agent_executes_allowlisted_tool(client, settings, monkeypatch, real_station):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        if not tool_history:
            return {
                "type": "tool_call",
                "tool": "search_destination_chargers",
                "args": {
                    "location": {"label": "Almansa", "lat": 38.87, "lon": -1.09},
                    "radius_km": 5,
                    "limit": 2,
                },
            }
        tool_result = tool_history[-1]["result"]
        assert tool_result["ok"] is True
        assert tool_result["stops"][0]["name"] == real_station.name
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "destination-from-tool",
                    "type": "DestinationChargingCard",
                    "version": 1,
                    "props": {"destination": "Almansa", "needsConfirmation": True},
                },
                {
                    "id": "stops-from-tool",
                    "type": "AlternativeStopsList",
                    "version": 1,
                    "props": {"stops": tool_result["stops"]},
                },
                {
                    "id": "risk-from-tool",
                    "type": "RiskExplanationCard",
                    "version": 1,
                    "props": {"level": "medio", "text": "Confirma disponibilidad antes de depender de estos cargadores."},
                },
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de mi hotel en Almansa"},
        content_type="application/json",
    )

    assert response.status_code == 200
    blocks = blocks_from_a2ui_response(response)
    block_types = [block["type"] for block in blocks]
    assert "UserMessage" in block_types
    assert "AlternativeStopsList" in block_types
    stops_block = next(block for block in blocks if block["type"] == "AlternativeStopsList")
    assert stops_block["props"]["stops"][0]["name"] == real_station.name


@pytest.mark.django_db
def test_deepseek_conversation_agent_uses_same_tool_and_a2ui_validation_loop(
    client, settings, monkeypatch, real_station, tmp_path
):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    settings.KALMIO_AGENT_TRACE_ENABLED = True
    settings.KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS = True
    settings.KALMIO_AGENT_TRACE_FILE = str(tmp_path / "agent-traces.jsonl")
    calls = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        calls.append((len(tool_history), repair_issues or []))
        if not tool_history:
            return {
                "type": "tool_call",
                "tool": "search_destination_chargers",
                "args": {
                    "location": {"label": "Almansa", "lat": 38.87, "lon": -1.09},
                    "radius_km": 5,
                    "limit": 1,
                },
            }
        tool_result = tool_history[-1]["result"]
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "destination-deepseek",
                    "type": "DestinationChargingCard",
                    "version": 1,
                    "props": {"destination": "Almansa", "needsConfirmation": True},
                },
                {
                    "id": "stops-deepseek",
                    "type": "AlternativeStopsList",
                    "version": 1,
                    "props": {"stops": tool_result["stops"]},
                },
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de mi hotel en Almansa"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert calls == [(0, []), (1, [])]
    stops_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "AlternativeStopsList")
    assert stops_block["props"]["stops"][0]["name"] == real_station.name
    trace_events = [
        json.loads(line)
        for line in (tmp_path / "agent-traces.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tool_event = next(event for event in trace_events if event["event"] == "internal_tool_call")
    assert tool_event["name"] == "search_destination_chargers"
    assert tool_event["metadata"]["stopCount"] == 1
    assert tool_event["request"]["location"]["label"] == "Almansa"


@pytest.mark.django_db
def test_codex_conversation_agent_rejects_unknown_tool_with_a2ui_risk(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"

    def fake_codex_decision(message, tool_history=None):
        return {"type": "tool_call", "tool": "delete_everything", "args": {}}

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Haz algo no permitido"},
        content_type="application/json",
    )

    assert response.status_code == 200
    risk_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "RiskExplanationCard")
    assert "No puedo hacer esa acción desde el chat" in risk_block["props"]["text"]


@pytest.mark.django_db
def test_codex_allowed_tool_failure_returns_to_agent_for_contextual_final(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    calls = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        calls.append((len(tool_history), repair_issues or []))
        if not tool_history:
            return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Paseo de la Victoria"}}
        assert tool_history[-1]["result"]["ok"] is False
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "street-not-resolved",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {
                        "text": (
                            "No puedo ubicar esa calle exacta todavía; puedo buscar usando Córdoba "
                            "como aproximación o usar coordenadas."
                        )
                    },
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Y en el Paseo de la Victoria?"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert calls == [(0, []), (1, [])]
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks_from_a2ui_response(response))
    assert "No puedo ubicar esa calle exacta todavía" in rendered_text
    assert "No he podido cerrar una respuesta fiable" not in rendered_text


@pytest.mark.django_db
def test_codex_destination_card_with_embedded_stops_requires_traced_station_data(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        if repair_issues:
            repair_requests.append(repair_issues)
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "safe-text-only",
                        "type": "AssistantMessage",
                        "version": 1,
                        "props": {
                            "text": "Necesito validar cargadores autorizados antes de listar estaciones concretas."
                        },
                    }
                ],
            }
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "destination-from-codex",
                    "type": "DestinationChargingCard",
                    "version": 1,
                    "props": {
                        "location": "Valencia",
                        "approximate": True,
                        "stops": [{"name": "Cargador real", "powerKw": 50, "distanceKm": 1.2}],
                    },
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Cargadores cerca de hotel en Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    blocks = blocks_from_a2ui_response(response)
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks)
    assert repair_requests
    assert "sin resultado de herramienta trazable" in repair_requests[0][0]
    assert "Cargador real" not in rendered_text
    assert any(block["type"] == "AssistantMessage" for block in blocks)


@pytest.mark.django_db
def test_codex_conversation_agent_allows_bounded_tool_chain(client, settings, monkeypatch, real_station):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    calls = []
    source = DataSource.objects.create(name="Authorized provider Valencia", kind="ocpi", is_authorized=True)
    operator = Operator.objects.create(name="Valencia Operator")
    valencia_station = Station.objects.create(
        external_id="real-valencia-001",
        operator=operator,
        data_source=source,
        name="Valencia Centro HPC",
        address="Valencia",
        latitude=Decimal("39.470000"),
        longitude=Decimal("-0.380000"),
        amenities=["hotel"],
        is_sample_data=False,
    )
    evse = EVSE.objects.create(
        station=valencia_station,
        evse_uid="real-valencia-001-1",
        max_power_kw=150,
        status="available",
    )
    Connector.objects.create(evse=evse, connector_type="CCS2", max_power_kw=150)

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        calls.append(len(tool_history))
        if len(tool_history) == 0:
            return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Valencia"}}
        if len(tool_history) == 1:
            location = tool_history[-1]["result"]["location"]
            return {
                "type": "tool_call",
                "tool": "search_destination_chargers",
                "args": {"location": location, "radius_km": 80, "limit": 2},
            }
        assert tool_history[-1]["result"]["tool"] == "search_destination_chargers"
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "destination-from-chain",
                    "type": "DestinationChargingCard",
                    "version": 1,
                    "props": {"destination": "Valencia", "needsConfirmation": True},
                },
                {
                    "id": "stops-from-chain",
                    "type": "AlternativeStopsList",
                    "version": 1,
                    "props": {"stops": tool_history[-1]["result"]["stops"]},
                },
                {
                    "id": "risk-from-chain",
                    "type": "RiskExplanationCard",
                    "version": 1,
                    "props": {"level": "medio", "text": "Confirma disponibilidad antes de depender de estos cargadores."},
                },
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert calls == [0, 1, 2]
    blocks = blocks_from_a2ui_response(response)
    assert any(block["type"] == "DestinationChargingCard" for block in blocks)
    stops_block = next(block for block in blocks if block["type"] == "AlternativeStopsList")
    assert stops_block["props"]["stops"][0]["name"] == valencia_station.name


@pytest.mark.django_db
def test_codex_conversation_agent_allows_agent_chosen_text_final_after_tool(client, settings, monkeypatch, real_station):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        if not tool_history:
            return {
                "type": "tool_call",
                "tool": "search_destination_chargers",
                "args": {
                    "location": {"label": "Almansa", "lat": 38.87, "lon": -1.09},
                    "radius_km": 5,
                    "limit": 2,
                },
            }
        if repair_issues:
            repair_requests.append(repair_issues)
            return {"type": "final", "blocks": []}
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "text-only",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {"text": f"He encontrado {real_station.name}."},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de mi hotel en Almansa"},
        content_type="application/json",
    )

    assert response.status_code == 200
    blocks = blocks_from_a2ui_response(response)
    block_types = [block["type"] for block in blocks]
    assert repair_requests == []
    assert "AssistantMessage" in block_types
    assert real_station.name in " ".join(str(block.get("props", {})) for block in blocks)


@pytest.mark.django_db
def test_codex_conversation_agent_repairs_untraced_structured_station_data(client, settings, monkeypatch, real_station):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        if not tool_history:
            return {
                "type": "tool_call",
                "tool": "search_destination_chargers",
                "args": {
                    "location": {"label": "Almansa", "lat": 38.87, "lon": -1.09},
                    "radius_km": 5,
                    "limit": 2,
                },
            }
        tool_result = tool_history[-1]["result"]
        if repair_issues:
            repair_requests.append(repair_issues)
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "stops-repaired",
                        "type": "AlternativeStopsList",
                        "version": 1,
                        "props": {"stops": tool_result["stops"]},
                    }
                ],
            }
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "invented-stop",
                    "type": "AlternativeStopsList",
                    "version": 1,
                    "props": {"stops": [{"name": "Fake HPC", "powerKw": 350, "distanceKm": 0.1}]},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de mi hotel en Almansa"},
        content_type="application/json",
    )

    assert response.status_code == 200
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks_from_a2ui_response(response))
    assert repair_requests
    assert "Fake HPC" not in rendered_text
    assert real_station.name in rendered_text


@pytest.mark.django_db
def test_codex_conversation_agent_repairs_generic_urgent_nearest_when_tool_has_station(
    client, settings, monkeypatch, real_station
):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        if not tool_history:
            return {
                "type": "tool_call",
                "tool": "search_destination_chargers",
                "args": {
                    "location": {"label": "Almansa", "lat": 38.87, "lon": -1.09},
                    "radius_km": 5,
                    "limit": 2,
                },
            }
        tool_result = tool_history[-1]["result"]
        if repair_issues:
            repair_requests.append(repair_issues)
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "urgent-repaired",
                        "type": "UrgentChargeCard",
                        "version": 1,
                        "props": {
                            "nearest": tool_result["stops"][0]["name"],
                            "distanceKm": tool_result["stops"][0]["distanceKm"],
                        },
                    }
                ],
            }
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "urgent-generic",
                    "type": "UrgentChargeCard",
                    "version": 1,
                    "props": {"nearest": "Cargador cercano por confirmar", "distanceKm": 0.1},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya cerca de Almansa"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert repair_requests
    assert "debe usar una estación trazable" in repair_requests[0][0]
    urgent_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "UrgentChargeCard")
    assert urgent_block["props"]["nearest"] == real_station.name


@pytest.mark.django_db
def test_codex_conversation_agent_repairs_missing_urgent_battery_from_explicit_user_context(
    client, settings, monkeypatch, real_station
):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        if not tool_history:
            return {
                "type": "tool_call",
                "tool": "search_destination_chargers",
                "args": {
                    "location": {"label": "Almansa", "lat": 38.87, "lon": -1.09},
                    "radius_km": 5,
                    "limit": 1,
                },
            }
        tool_result = tool_history[-1]["result"]
        if repair_issues:
            repair_requests.append(repair_issues)
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "urgent-with-battery",
                        "type": "UrgentChargeCard",
                        "version": 1,
                        "props": {
                            "battery": 12,
                            "nearest": tool_result["stops"][0]["name"],
                            "distanceKm": tool_result["stops"][0]["distanceKm"],
                        },
                    }
                ],
            }
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "urgent-without-battery",
                    "type": "UrgentChargeCard",
                    "version": 1,
                    "props": {
                        "nearest": tool_result["stops"][0]["name"],
                        "distanceKm": tool_result["stops"][0]["distanceKm"],
                    },
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya, estoy al 12% en Almansa"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert repair_requests
    assert "debe conservar la batería explícita" in repair_requests[0][0]
    urgent_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "UrgentChargeCard")
    assert urgent_block["props"]["battery"] == 12


@pytest.mark.django_db
def test_codex_conversation_agent_repairs_vague_risk_copy(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        if repair_issues:
            repair_requests.append(repair_issues)
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "risk-specific",
                        "type": "RiskExplanationCard",
                        "version": 1,
                        "props": {
                            "level": "medio",
                            "text": "Confirma acceso final, tarifa y disponibilidad porque los datos pueden cambiar.",
                        },
                    }
                ],
            }
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "risk-vague",
                    "type": "RiskExplanationCard",
                    "version": 1,
                    "props": {"level": "medio", "text": "Antes de salir"},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Tengo poca batería y voy con niños"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert repair_requests
    assert "RiskExplanationCard.text debe explicar" in repair_requests[0][0]
    risk_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "RiskExplanationCard")
    assert "Confirma acceso final" in risk_block["props"]["text"]


@pytest.mark.django_db
def test_codex_conversation_agent_repairs_unsupported_action_buttons(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        if repair_issues:
            repair_requests.append(repair_issues)
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "safe-action-text",
                        "type": "AssistantMessage",
                        "version": 1,
                        "props": {"text": "Puedo ayudarte a ajustar la búsqueda desde el chat."},
                    }
                ],
            }
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "unsupported-actions",
                    "type": "ActionButtons",
                    "version": 1,
                    "props": {"actions": [{"label": "Ver alternativas", "action": "show_alternatives"}]},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Quiero revisar alternativas"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert repair_requests
    assert any("event, functionCall.openUrl" in issue for issue in repair_requests[0])
    block_types = [block["type"] for block in blocks_from_a2ui_response(response)]
    assert "ActionButtons" not in block_types
    assert "AssistantMessage" in block_types


def test_action_buttons_accept_protocol_event_and_function_call():
    issues = a2ui_contract_issues(
        [
            {
                "id": "actions",
                "type": "ActionButtons",
                "version": 1,
                "props": {
                    "actions": [
                        {
                            "label": "Abrir en Maps",
                            "functionCall": {
                                "call": "openUrl",
                                "args": {"url": "https://www.google.com/maps/search/?api=1&query=37.88,-4.78"},
                            },
                        },
                        {
                            "label": "Ajustar búsqueda",
                            "event": {"name": "refine_search", "context": {"radiusKm": 80}},
                        },
                    ]
                },
            }
        ],
        [],
    )

    assert issues == []


def test_assistant_message_requires_approximation_when_hotel_resolves_only_to_city():
    issues = a2ui_contract_issues(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Estos son los cargadores autorizados cerca del Hotel Meliá Córdoba (Plaza de Colón)."
                },
            }
        ],
        [
            {
                "call": {"tool": "resolve_location", "args": {"query": "Hotel Meliá Córdoba"}},
                "result": {"ok": True, "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794}},
            }
        ],
    )

    assert any("solo resolvió 'Córdoba'" in issue for issue in issues)


def test_assistant_message_allows_explicit_approximation_for_hotel_city_resolution():
    issues = a2ui_contract_issues(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "No tengo la ubicación exacta del Hotel Meliá Córdoba; uso Córdoba como aproximación."
                },
            }
        ],
        [
            {
                "call": {"tool": "resolve_location", "args": {"query": "Hotel Meliá Córdoba"}},
                "result": {"ok": True, "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794}},
            }
        ],
    )

    assert issues == []


@pytest.mark.django_db
def test_codex_conversation_agent_stops_repeated_tool_call(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Valencia"}}

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    risk_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "RiskExplanationCard")
    assert "No he podido completar esta respuesta con fiabilidad" in risk_block["props"]["text"]


@pytest.mark.django_db
def test_codex_conversation_agent_recovers_repeated_tool_call_with_final_retry(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    calls = []
    trace_events = []
    repeated_args = {
        "location": {"label": "Córdoba (cerca de Mezquita)", "lat": 37.880729, "lon": -4.782446},
        "radius_km": 80,
        "limit": 6,
    }
    tool_result = {
        "ok": True,
        "tool": "search_destination_chargers",
        "location": repeated_args["location"],
        "stops": [
            {
                "name": "Parking Calle Sevilla Nº5 - Córdoba",
                "powerKw": 22,
                "distanceKm": 0.38,
                "availableEvses": 2,
                "connectorTypes": ["TYPE2"],
                "lat": 37.883857,
                "lon": -4.780831,
            }
        ],
        "warnings": ["Confirma acceso final, tarifa y disponibilidad antes de depender de ellos."],
    }

    def fake_execute_conversation_tool(tool_call):
        assert tool_call.name == "search_destination_chargers"
        assert tool_call.args == repeated_args
        return tool_result

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        calls.append((len(tool_history), repair_issues or []))
        if repair_issues:
            assert any("repitió la herramienta" in issue for issue in repair_issues)
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "more-power-message",
                        "type": "AssistantMessage",
                        "version": 1,
                        "props": {
                            "text": "La opción con más potencia en los datos validados es Parking Calle Sevilla Nº5."
                        },
                    },
                    {
                        "id": "more-power-stops",
                        "type": "AlternativeStopsList",
                        "version": 1,
                        "props": {"stops": tool_history[-1]["result"]["stops"]},
                    },
                ],
            }
        return {"type": "tool_call", "tool": "search_destination_chargers", "args": repeated_args}

    def fake_record_trace_event(**kwargs):
        trace_events.append(kwargs)

    monkeypatch.setattr("routing.agent.execute_conversation_tool", fake_execute_conversation_tool)
    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)
    monkeypatch.setattr("routing.agent.record_trace_event", fake_record_trace_event)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Algo que tenga más potencia?"},
        content_type="application/json",
    )

    assert response.status_code == 200
    blocks = blocks_from_a2ui_response(response)
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks)
    assert [count for count, _issues in calls] == [0, 1, 1]
    assert calls[2][1]
    assert "No he podido cerrar una respuesta fiable" not in rendered_text
    assert "Parking Calle Sevilla Nº5" in rendered_text
    guardrail_event = next(event for event in trace_events if event["event"] == "agent_guardrail")
    assert guardrail_event["name"] == "repeated_tool_call"
    assert guardrail_event["status"] == "warning"


@pytest.mark.django_db
def test_codex_conversation_agent_stops_at_tool_budget(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    settings.KALMIO_CODEX_MAX_TOOL_CALLS = 1

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        if not tool_history:
            return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Valencia"}}
        return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Madrid"}}

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    risk_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "RiskExplanationCard")
    assert "No he podido completar esta respuesta con fiabilidad" in risk_block["props"]["text"]


@pytest.mark.django_db
def test_local_conversation_agent_failure_uses_dev_fallback_without_technical_detail(client, monkeypatch):
    def failing_agent(message, history_blocks=None):
        raise AgentResponseError("Codex local no devolvió JSON válido.")

    monkeypatch.setattr("routing.api.run_conversation_agent", failing_agent)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya"},
        content_type="application/json",
    )

    assert response.status_code == 200
    blocks = blocks_from_a2ui_response(response)
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks)
    assert "Codex" not in rendered_text
    assert "JSON" not in rendered_text
    block_types = [block["type"] for block in blocks]
    assert "UserMessage" in block_types
    assert "LocationRequestCard" in block_types
    assert "RiskExplanationCard" not in block_types


@pytest.mark.django_db
def test_codex_conversation_agent_failure_uses_minimal_safe_fallback(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"

    def failing_agent(message, history_blocks=None):
        raise AgentResponseError("Codex local no devolvió JSON válido.")

    monkeypatch.setattr("routing.api.run_conversation_agent", failing_agent)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya"},
        content_type="application/json",
    )

    assert response.status_code == 200
    blocks = blocks_from_a2ui_response(response)
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks)
    assert "Codex" not in rendered_text
    assert "JSON" not in rendered_text
    block_types = [block["type"] for block in blocks]
    assert "UserMessage" in block_types
    assert "AssistantMessage" in block_types
    assert "ClarifyingQuestionCard" in block_types
    assert "LocationRequestCard" not in block_types
    assert "UrgentChargeCard" not in block_types


@pytest.mark.django_db
def test_codex_urgent_response_does_not_repair_component_choice_by_intent(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        if repair_issues:
            repair_requests.append(repair_issues)
            return {"type": "final", "blocks": []}
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "wrong-destination",
                    "type": "DestinationChargingCard",
                    "version": 1,
                    "props": {"destination": "Córdoba", "needsConfirmation": True},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya en Córdoba con 18%"},
        content_type="application/json",
    )

    assert response.status_code == 200
    block_types = [block["type"] for block in blocks_from_a2ui_response(response)]
    assert repair_requests == []
    assert "DestinationChargingCard" in block_types
    assert "UrgentChargeCard" not in block_types


@pytest.mark.django_db
def test_anonymous_conversation_without_vehicle_returns_chargers_only(client, monkeypatch, real_station):
    monkeypatch.setattr("routing.api.get_route_provider", lambda: StaticRouteProvider())

    response = client.post(
        "/api/conversation/route",
        data=route_payload(),
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planning_level"] == "chargers_only"
    assert body["id"] is None
    assert body["energy_kwh"] is None
    assert body["arrival_battery_percent"] is None
    assert body["recommendation"]["external_id"] == real_station.external_id
    assert body["recommendation"]["connector"] == "CCS2"
    assert "Sin datos de autonomía" in body["warnings"][0]
    assert RoutePlan.objects.count() == 0


@pytest.mark.django_db
def test_anonymous_conversation_uses_throttle_limit(client, monkeypatch, settings, real_station):
    settings.KALMIO_ROUTE_CONVERSATION_THROTTLE_LIMIT = 2
    settings.KALMIO_ROUTE_CONVERSATION_THROTTLE_WINDOW_SECONDS = 120
    client = Client(enforce_csrf_checks=True)
    csrf_token = client.get("/api/auth/csrf").json()["csrf_token"]
    monkeypatch.setattr("routing.api.get_route_provider", lambda: StaticRouteProvider())

    for _ in range(2):
        response = client.post(
            "/api/conversation/route",
            data=conversation_payload(),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        assert response.status_code == 200

    response = client.post(
        "/api/conversation/route",
        data=conversation_payload(),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 429
    assert "Demasiadas peticiones de ruta en esta sesión" in response.json()["detail"]
    assert AuthThrottle.objects.count() == 1


@pytest.mark.django_db
def test_delete_active_conversation_clears_session_plan(client, monkeypatch, real_station):
    monkeypatch.setattr("routing.api.get_route_provider", lambda: StaticRouteProvider())
    client = Client(enforce_csrf_checks=True)
    csrf_token = client.get("/api/auth/csrf").json()["csrf_token"]

    create_response = client.post(
        "/api/conversation/route",
        data=conversation_payload(),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert create_response.status_code == 200
    assert client.get("/api/conversation").status_code == 200

    clear_response = client.delete("/api/conversation", HTTP_X_CSRFTOKEN=csrf_token)
    assert clear_response.status_code == 200
    assert client.get("/api/conversation").status_code == 404


@pytest.mark.django_db
def test_anonymous_conversation_rejects_missing_csrf(monkeypatch, real_station):
    monkeypatch.setattr("routing.api.get_route_provider", lambda: StaticRouteProvider())
    client = Client(enforce_csrf_checks=True)

    response = client.post(
        "/api/conversation/route",
        data=conversation_payload(),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert RoutePlan.objects.count() == 0


@pytest.mark.django_db
def test_anonymous_conversation_accepts_valid_csrf(monkeypatch, real_station):
    monkeypatch.setattr("routing.api.get_route_provider", lambda: StaticRouteProvider())
    client = Client(enforce_csrf_checks=True)
    csrf_response = client.get("/api/auth/csrf")
    csrf_token = csrf_response.json()["csrf_token"]

    response = client.post(
        "/api/conversation/route",
        data=conversation_payload(),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_route_plan_returns_chargers_only_without_vehicle_profile(client, monkeypatch, real_station, route_user):
    monkeypatch.setattr("routing.api.get_route_provider", lambda: StaticRouteProvider())
    client.force_login(route_user)

    response = client.post(
        "/api/plans/route",
        data=route_payload(),
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] is None
    assert body["created_at"] is None
    assert body["planning_level"] == "chargers_only"
    assert body["distance_km"] == 520
    assert body["energy_kwh"] is None
    assert body["arrival_battery_percent"] is None
    assert body["recommendation"]["external_id"] == real_station.external_id
    assert "is_sample_data" not in body["recommendation"]
    assert body["recommendation"]["price_is_estimated"] is False
    assert "Sin datos de autonomía" in body["warnings"][0]
    assert RoutePlan.objects.count() == 0

    list_response = client.get("/api/plans/route")
    assert list_response.status_code == 200
    assert list_response.json() == []


@pytest.mark.django_db
def test_route_plan_reports_missing_station_data(client, monkeypatch, route_user):
    monkeypatch.setattr("routing.api.get_route_provider", lambda: StaticRouteProvider())
    client.force_login(route_user)

    response = client.post(
        "/api/plans/route",
        data=route_payload(),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert "No hay estaciones autorizadas" in response.json()["detail"]
    assert RoutePlan.objects.count() == 0


@pytest.mark.django_db
def test_route_plan_reports_routing_provider_failure(client, monkeypatch, real_station, route_user):
    monkeypatch.setattr("routing.api.get_route_provider", lambda: FailingRouteProvider())
    client.force_login(route_user)

    response = client.post(
        "/api/plans/route",
        data=route_payload(),
        content_type="application/json",
    )

    assert response.status_code == 424
    assert response.json()["detail"] == "proveedor no disponible"
    assert RoutePlan.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.django_db
def test_route_plan_requires_authenticated_user(client):
    response = client.get("/api/plans/route")

    assert response.status_code == 401


@pytest.mark.django_db
def test_route_plan_rejects_out_of_range_coordinates(client, route_user):
    client.force_login(route_user)

    response = client.post(
        "/api/plans/route",
        data=route_payload(origin={"lat": 120, "lon": -4.7794}),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert RoutePlan.objects.count() == 0


@pytest.mark.django_db
def test_route_plan_rejects_oversized_labels(client, route_user):
    client.force_login(route_user)

    response = client.post(
        "/api/plans/route",
        data=route_payload(origin_label="A" * 161),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert RoutePlan.objects.count() == 0


@pytest.mark.django_db
def test_station_score_payload_uses_real_availability_snapshot(real_station):
    evse = real_station.evses.get()
    AvailabilitySnapshot.objects.create(
        evse=evse,
        source=real_station.data_source,
        status="available",
        observed_at=timezone.now() - timedelta(minutes=17),
    )

    payload = station_to_score_payload(real_station, "CCS2", 1.2)

    assert payload["available_connectors"] == 1
    assert 16 <= payload["availability_age_min"] <= 18


@pytest.mark.django_db
def test_station_score_payload_does_not_invent_availability(real_station):
    evse = real_station.evses.get()
    evse.status = "unknown"
    evse.save(update_fields=["status"])

    payload = station_to_score_payload(real_station, "CCS2", 1.2)

    assert payload["available_connectors"] == 0
    assert payload["availability_age_min"] is None
