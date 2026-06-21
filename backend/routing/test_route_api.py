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
    conversation_agent_prompt,
    contextualized_prompt,
    decode_agent_json,
    parse_openai_compatible_decision,
    run_deepseek_decision,
    station_search_result_prompt,
    tool_call_argument_grounding_issues,
    validate_blocks,
)
from routing.instrumentation import estimate_deepseek_cost, record_trace_event
from routing.models import RoutePlan
from routing.production_planner import score_exploration_station, station_to_score_payload
from routing.providers import Coordinate, ProviderRoute, RoutingProviderError
from routing.scoring import Preferences
from routing.tools import (
    ConversationToolError,
    parse_location_arg,
    parse_preferences_arg,
    parse_vehicle_arg,
    plan_route_tool,
    resolve_location_tool,
    search_destination_chargers_tool,
)


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
    assert [block["type"] for block in blocks] == ["AssistantMessage"]
    assert "blocks" not in body


@pytest.mark.django_db
def test_conversation_message_accepts_a2ui_action_transport_without_visible_action_echo(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

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
    blocks = blocks_from_a2ui_response(body)
    block_types = [block["type"] for block in blocks]
    assert "UserMessage" in block_types
    assert "AssistantMessage" in block_types
    assert any("Valencia" in str(block.get("props", {})) for block in blocks if block["type"] == "AssistantMessage")
    assert "RouteSummaryCard" not in block_types
    assert RoutePlan.objects.count() == 0


@pytest.mark.django_db
def test_removed_place_detail_card_renders_as_unknown_fallback():
    blocks = validate_blocks(
        [
            {
                "id": "place-detail",
                "type": "PlaceDetailCard",
                "version": 1,
                "props": {
                    "location": "{'label': 'Córdoba', 'lat': 37.8882, 'lon': -4.7794}",
                    "lat": 37.8882,
                    "lon": -4.7794,
                },
            }
        ]
    )

    assert blocks[0]["type"] == "ErrorFallbackCard"
    assert blocks[0]["props"]["originalType"] == "PlaceDetailCard"


def test_urgent_charge_card_normalizes_nested_recommended_stop():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
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
        "name": "BALLENOIL-ES336090-COLON",
        "stationName": "BALLENOIL-ES336090-COLON",
        "distanceKm": 0.3,
    }


def test_urgent_charge_card_normalizes_name_variant_from_agent():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "name": "BALLENOIL-ES336090-COLON",
                    "distanceKm": 0.3,
                },
            }
        ]
    )

    assert blocks[0]["props"]["name"] == "BALLENOIL-ES336090-COLON"
    assert blocks[0]["props"]["stationName"] == "BALLENOIL-ES336090-COLON"
    assert blocks[0]["props"]["distanceKm"] == 0.3


def test_urgent_charge_card_normalizes_station_name_variant_from_agent():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "stationName": "BALLENOIL-ES336090-COLON",
                    "distanceKm": 0.3,
                },
            }
        ]
    )

    assert blocks[0]["props"]["name"] == "BALLENOIL-ES336090-COLON"
    assert blocks[0]["props"]["stationName"] == "BALLENOIL-ES336090-COLON"


def test_urgent_charge_card_normalizes_nested_station_variant_without_adding_ui():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "battery": 12,
                    "station": {
                        "name": "BALLENOIL-ES336090-COLON",
                        "distanceKm": 0.3,
                    },
                    "risk": "Batería muy baja.",
                    "alternatives": [
                        {
                            "name": "Parking Calle Sevilla Nº5 - Córdoba",
                            "distanceKm": 0.5,
                        }
                    ],
                },
            }
        ]
    )

    assert len(blocks) == 1
    assert blocks[0]["props"] == {
        "name": "BALLENOIL-ES336090-COLON",
        "stationName": "BALLENOIL-ES336090-COLON",
        "distanceKm": 0.3,
        "risk": "Batería muy baja.",
    }


def test_urgent_charge_card_normalizes_nested_nearest_station_name():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "battery": 12,
                    "nearest": {
                        "stationName": "BALLENOIL-ES336090-COLON",
                        "distanceKm": 0.3,
                    },
                },
            }
        ]
    )

    assert blocks[0]["props"] == {
        "name": "BALLENOIL-ES336090-COLON",
        "stationName": "BALLENOIL-ES336090-COLON",
        "distanceKm": 0.3,
    }


def test_urgent_charge_card_ignores_boolean_nearest_when_station_name_exists():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "battery": 8,
                    "nearest": True,
                    "stationName": "Parking Calle Sevilla Nº5 - Córdoba",
                    "distanceKm": 0.5,
                },
            }
        ]
    )

    assert blocks[0]["props"]["name"] == "Parking Calle Sevilla Nº5 - Córdoba"
    assert blocks[0]["props"]["stationName"] == "Parking Calle Sevilla Nº5 - Córdoba"


def test_urgent_charge_card_normalizes_non_numeric_battery_to_null():
    blocks = validate_blocks(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "battery": "baja",
                    "nearest": "BALLENOIL-ES336090-COLON",
                    "distanceKm": 0.3,
                    "risk": "Batería baja indicada sin porcentaje.",
                },
            }
        ]
    )

    assert "battery" not in blocks[0]["props"]
    assert blocks[0]["props"]["name"] == "BALLENOIL-ES336090-COLON"


def test_alternative_stops_list_normalizes_station_name_variant():
    blocks = validate_blocks(
        [
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {
                    "stops": [
                        {
                            "stationName": "Parking Calle Sevilla Nº5 - Córdoba",
                            "distance_km": 0.5,
                            "power_kw": 22,
                            "connector_types": ["TYPE2"],
                            "location": {"lat": 37.883857, "lon": -4.780831},
                        }
                    ]
                },
            }
        ]
    )

    assert blocks[0]["props"]["stations"][0] == {
        "stationName": "Parking Calle Sevilla Nº5 - Córdoba",
        "name": "Parking Calle Sevilla Nº5 - Córdoba",
        "distanceKm": 0.5,
        "powerKw": 22,
        "connectorTypes": ["TYPE2"],
        "lat": 37.883857,
        "lon": -4.780831,
    }


def test_station_list_dedupes_primary_station_already_rendered():
    blocks = validate_blocks(
        [
            {
                "id": "primary",
                "type": "StationPreviewCard",
                "version": 1,
                "props": {
                    "name": "BALLENOIL-ES336090-COLON",
                    "lat": 37.8882,
                    "lon": -4.7794,
                    "powerKw": 150,
                },
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {
                    "stations": [
                        {
                            "stationName": "BALLENOIL-ES336090-COLON",
                            "lat": 37.8882,
                            "lon": -4.7794,
                            "powerKw": 150,
                        },
                        {
                            "stationName": "Parking Calle Sevilla Nº5 - Córdoba",
                            "lat": 37.883857,
                            "lon": -4.780831,
                            "powerKw": 22,
                        },
                    ]
                },
            },
        ]
    )

    station_list = next(block for block in blocks if block["type"] == "StationList")
    assert [station["name"] for station in station_list["props"]["stations"]] == [
        "Parking Calle Sevilla Nº5 - Córdoba"
    ]


def test_station_list_removed_when_only_primary_station_is_repeated():
    blocks = validate_blocks(
        [
            {
                "id": "primary",
                "type": "StationPreviewCard",
                "version": 1,
                "props": {"name": "BALLENOIL-ES336090-COLON", "powerKw": 150},
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"stationName": "BALLENOIL-ES336090-COLON", "powerKw": 150}]},
            },
        ]
    )

    assert [block["type"] for block in blocks] == ["StationPreviewCard"]


def test_action_buttons_adds_label_for_open_url_function_call():
    blocks = validate_blocks(
        [
            {
                "id": "actions",
                "type": "ActionButtons",
                "version": 1,
                "props": {
                    "actions": [
                        {
                            "functionCall": {
                                "call": "openUrl",
                                "args": {
                                    "url": "https://www.google.com/maps/dir/?api=1&destination=37.883857,-4.780831"
                                },
                            }
                        }
                    ]
                },
            }
        ]
    )

    assert blocks[0]["props"]["actions"][0]["label"] == "Abrir en Google Maps"


def test_removed_destination_and_stay_cards_render_fallbacks():
    blocks = validate_blocks(
        [
            {
                "id": "destination",
                "type": "DestinationChargingCard",
                "version": 1,
                "props": {"locationLabel": "Valencia centro", "needsConfirmation": True},
            },
            {
                "id": "stay",
                "type": "StayPlanningCard",
                "version": 1,
                "props": {"duration": "finde", "context": "Estancia en Granada"},
            }
        ]
    )

    assert [block["type"] for block in blocks] == ["ErrorFallbackCard", "ErrorFallbackCard"]
    assert blocks[0]["props"]["originalType"] == "DestinationChargingCard"
    assert blocks[1]["props"]["originalType"] == "StayPlanningCard"


def test_removed_risk_explanation_card_renders_as_unknown_fallback():
    blocks = validate_blocks(
        [
            {
                "id": "risk",
                "type": "RiskExplanationCard",
                "version": 1,
                "props": {"risk": "Disponibilidad, acceso y tarifas pueden cambiar antes del viaje."},
            }
        ]
    )

    assert blocks[0]["type"] == "ErrorFallbackCard"
    assert blocks[0]["props"]["originalType"] == "RiskExplanationCard"


def test_urgent_tool_fallback_renders_station_without_repeating_user_battery():
    blocks = blocks_from_tool_result(
        {
            "ok": True,
            "tool": "search_destination_chargers",
            "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
            "stops": [{"name": "Córdoba Centro HPC", "distanceKm": 1.4, "powerKw": 150}],
        },
        message="Necesito cargar ya. Estoy en Córdoba con un 18%",
    )

    urgent_block = next(block for block in blocks if block["type"] == "StationPreviewCard")
    assert urgent_block["props"]["name"] == "Córdoba Centro HPC"
    assert urgent_block["props"]["stationName"] == "Córdoba Centro HPC"
    assert urgent_block["props"]["distanceKm"] == 1.4
    assert urgent_block["props"]["powerKw"] == 150
    assert "battery" not in urgent_block["props"]


def test_resolve_location_tool_accepts_accented_city_inside_zone_text():
    result = resolve_location_tool({"query": "Paseo de la Victoria de Córdoba"})

    assert result["ok"] is True
    assert result["location"]["label"] == "Córdoba"
    assert result["location"]["lat"] == 37.8882
    assert result["location"]["lon"] == -4.7794
    assert result["location"]["precision"] == "city_approximation"


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
    assert stop["pricePerKwhEur"] == 0.49
    assert stop["currency"] == "EUR"
    assert stop["priceIsEstimated"] is False


@pytest.mark.django_db
def test_search_destination_chargers_tool_omits_estimated_tariff_value(real_station):
    real_station.tariffs.update(is_estimated=True)

    result = search_destination_chargers_tool(
        {
            "location": {"label": "Almansa", "lat": 38.87, "lon": -1.09},
            "connector": "CCS2",
            "radius_km": 5,
            "limit": 1,
        }
    )

    stop = result["stops"][0]
    assert "pricePerKwhEur" not in stop
    assert "currency" not in stop
    assert stop["priceIsEstimated"] is True


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


def test_conversation_agent_prompt_guides_followups_without_backend_intent_mapping():
    prompt = conversation_agent_prompt("Me equivoqué, estoy en Valencia centro")

    assert "No pidas destino para una carga urgente" in prompt
    assert "No llames resolve_location con frases que no son ubicaciones concretas" in prompt
    assert "Si el usuario corrige la ubicación" in prompt
    assert "conserva batería, conector y preferencias" in prompt
    assert "no puedes ubicar esa calle exacta" in prompt
    assert "sin perfil de vehículo" in prompt
    assert "planningLevel=chargers_only" in prompt
    assert "StationPreviewCard + ActionButtons" in prompt
    assert "preferences.max_useful_power_kw" in prompt
    assert "No presentes la potencia superior como ventaja" in prompt
    assert "llama search_destination_chargers directamente" in prompt
    assert "ida y vuelta, volver, regreso" in prompt
    assert "pregunta por el origen" in prompt
    assert "Una ciudad conocida ya es ubicación suficiente" in prompt
    assert "no esperes hotel/zona exacta" in prompt
    assert "usa primero la ciudad/zona como aproximación verificable" in prompt
    assert "explica en AssistantMessage la ubicación usada" in prompt
    assert "no presentes el hotel exacto como ubicación validada" in prompt
    assert "unidad de decisión accionable" in prompt
    assert "no como una pila de tarjetas" in prompt
    assert "una card principal" in prompt
    assert "colócalos inmediatamente después de la card" in prompt
    assert "pie de acción de esa decisión" in prompt
    assert "nunca como bloque intermedio entre StationPreviewCard y ActionButtons" in prompt
    assert "no satures la primera respuesta" in prompt
    assert "no muestres StationList en esa primera respuesta" in prompt
    assert "ActionButtons inmediatamente después" in prompt
    assert "event.name='show_more_options'" in prompt
    assert "pedir más opciones" in prompt
    assert "no repitas la estación primaria dentro de StationList" in prompt
    assert "no ActionButtons" in prompt
    assert "tool_call no es un componente A2UI" in prompt
    assert "nunca debe aparecer dentro de blocks" in prompt
    assert "No llames plan_route con coordenadas vacías o 0,0" in prompt
    assert "AssistantMessage para explicar la ubicación usada y la incertidumbre de estancia" in prompt


def test_conversation_agent_prompt_exposes_max_useful_power_tool_argument():
    prompt = conversation_agent_prompt("Mi coche carga máximo a 100 kW, no necesito ultrarrápidos")

    assert '"max_useful_power_kw":null' in prompt
    assert "pasa X como preferences.max_useful_power_kw" in prompt
    assert "Tu coche no aprovechará más de X kW" in prompt
    assert "No basta con decir que no necesita ultrarrápidos" in prompt
    assert "No digas que has filtrado" in prompt


def test_conversation_agent_prompt_uses_city_first_for_destination_poi_searches():
    prompt = conversation_agent_prompt("Voy el finde a Granada y duermo cerca de la Alhambra")

    assert "usa Granada como primera búsqueda aproximada" in prompt
    assert "Granada/Alhambra como aproximación" in prompt


def test_station_search_result_prompt_anchors_destination_search_location():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Cádiz", "lat": 36.5271, "lon": -6.2886}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Cádiz", "lat": 36.5271, "lon": -6.2886},
                "stops": [{"name": "ONCE DZ Cádiz", "distanceKm": 0.23, "powerKw": 22}],
            },
        }
    ]

    prompt = station_search_result_prompt("Voy una semana a Cádiz y necesito cargar durante la estancia", tool_history)

    assert "explica en AssistantMessage la ubicación usada antes de las estaciones" in prompt
    assert "di que es una aproximación" in prompt
    assert "pide dirección, zona exacta o coordenadas" in prompt


def test_conversation_agent_prompt_compacts_route_geometry_tool_history():
    coordinates = [[-3.7 + index * 0.001, 40.4 - index * 0.001] for index in range(5000)]
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                    "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                "distanceKm": 356.7,
                "durationMin": 240,
                "routeGeometry": {"type": "LineString", "coordinates": coordinates},
                "recommendation": {
                    "name": "Moya Hub Honrubia",
                    "powerKw": 240,
                    "distanceKm": 1.23,
                    "lat": 39.602992,
                    "lon": -2.279669,
                    "availableEvses": 9,
                    "totalEvses": 12,
                    "connectorTypes": ["CCS2"],
                },
                "alternatives": [],
            },
        }
    ]

    prompt = conversation_agent_prompt("Tengo un Tesla Model Y y salgo con 45%. Madrid a Valencia", tool_history)

    assert "Historial de herramientas compactado" in prompt
    assert "routeGeometrySummary" in prompt
    assert '"pointCount": 5000' in prompt
    assert '"coordinates"' not in prompt
    assert "Moya Hub Honrubia" in prompt
    assert len(prompt) < len(json.dumps(tool_history, ensure_ascii=False))


def test_conversation_agent_prompt_compacts_rejected_map_blocks_for_repair():
    coordinates = [[-3.7 + index * 0.001, 40.4 - index * 0.001] for index in range(5000)]
    candidate_blocks = [
        {
            "id": "map",
            "type": "MapPreviewCard",
            "version": 1,
            "props": {
                "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                "routeGeometry": {"type": "LineString", "coordinates": coordinates},
                "primaryStation": {
                    "name": "Moya Hub Honrubia",
                    "powerKw": 240,
                    "distanceKm": 1.23,
                    "lat": 39.602992,
                    "lon": -2.279669,
                },
            },
        }
    ]

    prompt = conversation_agent_prompt(
        "Tengo un Tesla Model Y y salgo con 45%. Madrid a Valencia",
        tool_history=[],
        repair_issues=["MapPreviewCard necesita geometría trazable."],
        candidate_blocks=candidate_blocks,
    )

    assert "Bloques rechazados compactados" in prompt
    assert "routeGeometrySummary" in prompt
    assert '"pointCount": 5000' in prompt
    assert '"coordinates"' not in prompt
    assert "Moya Hub Honrubia" in prompt


def test_a2ui_contract_rejects_hard_power_filter_copy_when_rendering_over_cap_station():
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "preferences": {"max_useful_power_kw": 100},
                    "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                    "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "recommendation": {"name": "Moya Hub Honrubia", "powerKw": 240, "distanceKm": 1.23},
                "alternatives": [],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Tu coche carga hasta 100 kW, así que he filtrado paradas que no aprovecharías "
                        "más allá de esa potencia."
                    )
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Moya Hub Honrubia", "powerKw": 240, "distanceKm": 1.23},
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Tu coche no aprovechará los 240 kW; la potencia por encima de 100 kW no se premia."
                },
            },
        ]
    )

    issues = a2ui_contract_issues(blocks, tool_history)

    assert any("filtró o excluyó" in issue for issue in issues)


def test_a2ui_contract_allows_max_useful_power_copy_without_hard_filter_claim():
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "preferences": {"max_useful_power_kw": 100},
                    "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                    "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "recommendation": {"name": "Moya Hub Honrubia", "powerKw": 240, "distanceKm": 1.23},
                "alternatives": [],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Tu coche carga hasta 100 kW. La potencia superior no se premia en esta elección; "
                        "muestro esta parada por ubicación y servicios indicados."
                    )
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Moya Hub Honrubia", "powerKw": 240, "distanceKm": 1.23},
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Tu coche no aprovechará los 240 kW; faltan autonomía y consumo para validar llegada."
                },
            },
        ]
    )

    issues = a2ui_contract_issues(blocks, tool_history)

    assert issues == []


def test_conversation_agent_prompt_prioritizes_low_margin_urgent_order():
    prompt = conversation_agent_prompt("Estoy al 8% y no conozco la zona")

    assert "Con batería <=10%" in prompt
    assert "margen muy bajo" in prompt
    assert "ActionButtons con functionCall.openUrl es obligatorio" in prompt
    assert "antes de cualquier StationList" in prompt
    assert "no lo sustituyas por texto" in prompt
    assert "explica la batería baja en AssistantMessage" in prompt
    assert "metadata son opcionales y no se muestran al usuario" in prompt
    assert "AssistantMessage con el riesgo y la decisión, StationPreviewCard, ActionButtons" in prompt
    assert "solo después StationList si hace falta" in prompt


def test_conversation_agent_prompt_handles_qualitative_low_battery_and_children_amenities():
    prompt = conversation_agent_prompt("Tengo poca batería y voy con niños")

    assert "sin porcentaje explícito" in prompt
    assert "no inventes un número" in prompt
    assert "Orden exacto recomendado" in prompt
    assert "nunca pongas AssistantMessage ni StationList entre StationPreviewCard y ActionButtons" in prompt
    assert "si la herramienta trae amenities en la parada primaria" in prompt
    assert "debes mencionarlos brevemente por nombre" in prompt
    assert "no digas que están cerca, disponibles, son seguros, ideales, perfectos o aptos para niños" in prompt
    assert "Separa proximidad de servicios" in prompt
    assert "No uses superlativos globales" in prompt
    assert "según los datos disponibles" in prompt


def test_conversation_agent_prompt_keeps_service_preference_when_location_follows():
    prompt = conversation_agent_prompt("Busca una parada con baños y cafetería")

    assert "Preferencias de servicios como baños, cafetería, restaurante o comer" in prompt
    assert "Si el siguiente turno aporta ciudad, zona o coordenadas, conserva esa preferencia" in prompt
    assert "baños/cafetería/restaurante no están verificados" in prompt
    assert "'Estoy cerca de Almansa' después -> llama search_destination_chargers con Almansa" in prompt


def test_conversation_agent_prompt_limits_night_safety_claims():
    prompt = conversation_agent_prompt("No quiero cargar en sitios solitarios de noche")

    assert "Preferencias de seguridad nocturna o evitar sitios solitarios" in prompt
    assert "llama search_destination_chargers con esa ubicación" in prompt
    assert "no respondas solo con una ubicación resuelta" in prompt
    assert "no afirmes seguridad, vigilancia, iluminación, afluencia" in prompt
    assert "Kalmio no valida seguridad ni entorno en vivo" in prompt
    assert "ese límite debe aparecer antes de StationList" in prompt


def test_conversation_agent_prompt_warns_after_tool_when_requested_services_are_unverified():
    prompt = conversation_agent_prompt(
        "Historial reciente:\nUsuario: Busca una parada con baños y cafetería\nMensaje actual del usuario: Estoy cerca de Almansa",
        tool_history=[
            {
                "call": {
                    "tool": "search_destination_chargers",
                    "args": {"location": {"label": "Almansa", "lat": 38.869, "lon": -1.0971}},
                },
                "result": {
                    "ok": True,
                    "tool": "search_destination_chargers",
                    "stops": [{"name": "Consum Almansa", "distanceKm": 0.49, "amenities": []}],
                },
            }
        ],
    )

    assert "Ya tienes resultados de search_destination_chargers" in prompt
    assert "No repitas la misma búsqueda" in prompt
    assert "Dato crítico de servicios" in prompt
    assert "no están verificados en esos resultados" in prompt


def test_conversation_agent_prompt_keeps_plan_b_on_previous_traced_alternatives():
    prompt = conversation_agent_prompt("El cargador al que iba está ocupado, dame un plan B")

    assert "no la repitas como plan B" in prompt
    assert "nombra la parada descartada" in prompt
    assert "no debe seguir siendo el plan principal" in prompt
    assert "Reutiliza exactamente alternativas previas de la herramienta" in prompt
    assert "no cambies métricas ni inventes coordenadas" in prompt
    assert "Si un dato como precio, dirección exacta o puestos de carga no estaba en la alternativa previa, omítelo" in prompt
    assert "usa su lat/lon exactos" in prompt
    assert "disponibilidad en vivo puede cambiar" in prompt


def test_conversation_agent_prompt_asks_structured_road_context_before_low_detour_search():
    prompt = conversation_agent_prompt("Estoy en carretera con 18%, no quiero desviarme mucho")

    assert "En carretera y poco desvío" in prompt
    assert "pide carretera, zona actual/coordenadas y destino" in prompt
    assert "no lo reduzcas a búsqueda urbana arbitraria" in prompt
    assert "usa AssistantMessage con una pregunta breve" in prompt
    assert "no muestres campos genéricos de ciudad" in prompt


def test_conversation_agent_prompt_guides_chargers_only_route_without_claiming_default_reserve():
    prompt = conversation_agent_prompt("Voy de Córdoba a Valencia con 58%. No quiero llegar justo")

    assert "planningLevel=chargers_only" in prompt
    assert "Usa RouteSummaryCard para distancia/duración de la herramienta" in prompt
    assert "no puedes validar batería de llegada ni reserva sin consumo/perfil" in prompt
    assert "El AssistantMessage inicial debe explicar antes de la card" in prompt
    assert "qué puedes decidir, qué no puedes validar y cuál es el siguiente paso" in prompt
    assert "muestra después la decisión principal pronto en móvil" in prompt
    assert "Patrón recomendado: AssistantMessage explicativo" in prompt
    assert "una card principal de contexto o recomendación" in prompt
    assert "ActionButtons para navegar/ver alternativas/refinar" in prompt
    assert "solo después StationList cuando esté justificada" in prompt
    assert "no digas que indicó 20%" in prompt
    assert "margen conservador por defecto" in prompt
    assert "No digas asegurar/garantizar margen en chargers_only" in prompt
    assert "ni 'te ayudará a recuperar margen'" in prompt
    assert "evita frases como '4 horas'" in prompt
    assert "arrivalBattery:null" in prompt
    assert "ese X% es batería de salida" in prompt
    assert "no escribas 'llegas con X%'" in prompt
    assert "Si el viaje es futuro" in prompt
    assert "antes de cualquier StationPreviewCard o StationList" in prompt
    assert "disponibilidad, acceso y tarifas pueden cambiar" in prompt


def test_conversation_agent_prompt_guides_controlled_detour_comfort_preference():
    prompt = conversation_agent_prompt("Prefiero desviarme 10 minutos si el sitio es más cómodo. Voy de Madrid a Valencia con 60%")

    assert "Preferencias de desvío controlado por comodidad" in prompt
    assert "menciona servicios indicados como comodidad potencial" in prompt
    assert "no digas 'buenos servicios'" in prompt
    assert "No introduzcas preferencias de pocas paradas" in prompt


def test_conversation_agent_prompt_guides_can_i_arrive_without_charging_question():
    prompt = conversation_agent_prompt("Voy de Sevilla a Granada, ¿me da para llegar sin cargar?")

    assert "debes llamar plan_route para mostrar distancia/duración de proveedor" in prompt
    assert "no respondas sí/no" in prompt
    assert "no afirmes que llega" in prompt
    assert "pide esos datos críticos" in prompt
    assert "no muestres StationPreviewCard/StationList como recomendación principal" in prompt
    assert "Sevilla a Granada, me da para llegar sin cargar?" in prompt


def test_conversation_agent_prompt_guides_few_stops_without_vehicle_profile():
    prompt = conversation_agent_prompt("Tengo que ir de Alicante a Bilbao y prefiero parar pocas veces")

    assert "8 h 37 min" in prompt
    assert "no como cientos de minutos" in prompt
    assert "prefiere parar pocas veces" in prompt
    assert "no puedes garantizar ni optimizar pocas paradas" in prompt
    assert "antes de las paradas" in prompt
    assert "punto de carga autorizado en el corredor" in prompt
    assert "Alicante a Bilbao, prefiero parar pocas veces" in prompt


def test_conversation_agent_prompt_guides_hard_arrival_reserve_without_vehicle_profile():
    prompt = conversation_agent_prompt("Voy de Zaragoza a Barcelona y quiero llegar con al menos 25%")

    assert "pasa X como reserve_min_percent" in prompt
    assert "ese X% no se puede validar en chargers_only" in prompt
    assert "antes de cualquier StationPreviewCard/StationList" in prompt
    assert "Zaragoza a Barcelona con 25%" in prompt


def test_conversation_agent_prompt_guides_granada_alhambra_weekend_destination_warning():
    prompt = conversation_agent_prompt("Voy el finde a Granada y duermo cerca de la Alhambra")

    assert "devuelve type=tool_call search_destination_chargers" in prompt
    assert "Granada como primera búsqueda aproximada" in prompt
    assert "Granada/Alhambra como aproximación" in prompt
    assert "si es finde" in prompt
    assert "disponibilidad, acceso y tarifas pueden cambiar" in prompt
    assert "no como ubicación exacta del alojamiento" in prompt
    assert "pide hotel/zona/direccion exacta" in prompt
    assert "AssistantMessage para explicar la ubicación usada" in prompt
    assert "no devuelvas solo un botón para buscar ni una respuesta final que diga 'buscaré'" in prompt
    assert "No respondas con 'buscaré', 'voy a buscar' o 'puedo buscar'" in prompt
    assert "no crees StationPreviewCard genéricos" in prompt


def test_conversation_agent_prompt_guides_round_trip_missing_origin_as_assistant_message():
    prompt = conversation_agent_prompt("Voy a Córdoba el viernes y vuelvo el domingo, dónde cargo?")

    assert "ida y vuelta" in prompt
    assert "no llames plan_route ni search_destination_chargers" in prompt
    assert "pregunta por el origen en un AssistantMessage" in prompt
    assert "origen/salida" in prompt
    assert "No uses la ciudad destino como origen" in prompt


def test_conversation_agent_prompt_guides_hotel_without_charger_primary_destination_stop():
    prompt = conversation_agent_prompt(
        "Voy a un hotel sin cargador, necesito cargar durante la estancia. En Valencia centro"
    )

    assert "hotel no tiene cargador" in prompt
    assert "StationPreviewCard" in prompt
    assert "StationList" in prompt
    assert "distancia, potencia, conectores y puestos de carga registrados" in prompt
    assert "no la presentes como disponibilidad en vivo ni como reserva" in prompt
    assert "Valencia centro" in prompt
    assert "parada primaria" in prompt


def test_tool_call_grounding_rejects_location_from_prompt_example():
    issues = tool_call_argument_grounding_issues(
        {
            "type": "tool_call",
            "tool": "search_destination_chargers",
            "args": {"location": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763}},
        },
        current_message="Voy a un hotel sin cargador, necesito cargar durante la estancia",
        history_blocks=[],
        tool_history=[],
    )

    assert issues
    assert "Valencia" in issues[0]
    assert "sin que aparezca" in issues[0]
    assert "no uses ejemplos del prompt como datos" in issues[0]


def test_tool_call_grounding_allows_location_from_followup_history():
    issues = tool_call_argument_grounding_issues(
        {
            "type": "tool_call",
            "tool": "search_destination_chargers",
            "args": {"location": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763}},
        },
        current_message="En Valencia centro",
        history_blocks=[
            {
                "id": "previous-user",
                "type": "UserMessage",
                "version": 1,
                "props": {"text": "Voy a un hotel sin cargador, necesito cargar durante la estancia"},
            }
        ],
        tool_history=[],
    )

    assert issues == []


def test_tool_call_grounding_rejects_generic_resolve_location_query():
    issues = tool_call_argument_grounding_issues(
        {
            "type": "tool_call",
            "tool": "resolve_location",
            "args": {"query": "ubicación actual"},
        },
        current_message="Necesito cargar ya, estoy al 12%",
        history_blocks=[],
        tool_history=[],
    )

    assert issues
    assert "resolve_location" in issues[0]
    assert "consulta genérica" in issues[0]


def test_tool_call_grounding_rejects_ungrounded_resolve_location_query():
    issues = tool_call_argument_grounding_issues(
        {
            "type": "tool_call",
            "tool": "resolve_location",
            "args": {"query": "Valencia"},
        },
        current_message="Necesito cargar durante una estancia",
        history_blocks=[],
        tool_history=[],
    )

    assert issues
    assert "Valencia" in issues[0]
    assert "sin que aparezca" in issues[0]


def test_tool_call_grounding_rejects_same_origin_destination_route():
    issues = tool_call_argument_grounding_issues(
        {
            "type": "tool_call",
            "tool": "plan_route",
            "args": {
                "origin": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                "destination": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
            },
        },
        current_message="Voy a Córdoba el viernes y vuelvo el domingo, dónde cargo?",
        history_blocks=[],
        tool_history=[],
    )

    assert issues
    assert "misma ubicación" in issues[0]
    assert "Falta el origen real" in issues[0]


def test_conversation_agent_prompt_guides_cheap_route_with_reserve_missing_context():
    prompt = conversation_agent_prompt("Quiero la ruta más barata, pero sin bajar del 20%")

    assert "Rutas baratas, reservas duras" in prompt
    assert "pregunta en el mismo turno por origen, destino, batería actual y modelo/consumo/autonomía" in prompt
    assert "No inventes tarifas, kWh, llegada ni comparativas de precio" in prompt
    assert "si no hay datos de tarifas de proveedor, dilo" in prompt


def test_conversation_agent_prompt_guides_price_preference_without_route_context():
    prompt = conversation_agent_prompt("Evita cargadores caros si hay alternativas razonables")

    assert "Preferencias de precio" in prompt
    assert "pide origen/destino o ubicación" in prompt
    assert "pricePerKwhEur/currency solo cuando venga de herramienta" in prompt
    assert "solo hay tarifas estimadas" in prompt


def test_conversation_agent_prompt_guides_large_hub_preference_without_location_context():
    prompt = conversation_agent_prompt("Prefiero hubs grandes aunque sean un poco más caros")

    assert "Preferencias de precio, hubs grandes o tamaño de parada" in prompt
    assert "no llames herramientas sin ruta/ubicación" in prompt
    assert "si la herramienta trae tarifas verificadas, compara tarifa/kWh" in prompt


def test_conversation_agent_prompt_guides_model_and_departure_battery_without_vehicle_profile():
    prompt = conversation_agent_prompt("Tengo un Tesla Model Y y salgo con 45%... Madrid a Valencia")

    assert "un modelo comercial como Tesla Model Y y una batería de salida no son un perfil autorizado" in prompt
    assert "usa vehicle:null u omite vehicle" in prompt
    assert "No rellenes campos desconocidos con null, ceros o defaults" in prompt
    assert "no calcular energía, autonomía ni llegada" in prompt


def test_conversation_agent_prompt_guides_charge_before_or_after_without_context():
    prompt = conversation_agent_prompt("¿Me conviene cargar antes de salir o al llegar?")

    assert "Cargar antes de salir vs al llegar" in prompt
    assert "Da una comparación conceptual breve" in prompt
    assert "cargar antes reduce riesgo" in prompt
    assert "cargar al llegar puede tener sentido" in prompt
    assert "pide origen, destino, batería actual y modelo/consumo/autonomía" in prompt


def test_a2ui_contract_rejects_cheap_route_reserve_without_vehicle_context():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Para calcular la ruta más barata necesito saber el origen y el destino.",
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[],
        message="Quiero la ruta más barata, pero sin bajar del 20%",
    )

    assert any("batería actual" in issue and "modelo/consumo/autonomía" in issue for issue in issues)


def test_a2ui_contract_allows_cheap_route_reserve_with_vehicle_context_request():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Para calcular una ruta barata sin bajar del 20%, necesito origen, destino, "
                        "batería actual y modelo, consumo o autonomía. Sin tarifas de proveedor no inventaré precios."
                    ),
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[],
        message="Quiero la ruta más barata, pero sin bajar del 20%",
    )

    assert issues == []


def test_a2ui_contract_rejects_price_preference_without_route_or_tariff_context():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Lo tendré en cuenta para las próximas búsquedas y rutas.",
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[],
        message="Evita cargadores caros si hay alternativas razonables",
    )

    assert any("ruta/ubicación" in issue and "tarifas" in issue for issue in issues)


def test_a2ui_contract_allows_price_preference_with_route_and_tariff_context_request():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Lo tendré como preferencia. Dime origen y destino o tu ubicación. "
                        "No inventaré tarifas o precios si el proveedor no los da."
                    ),
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[],
        message="Evita cargadores caros si hay alternativas razonables",
    )

    assert issues == []


def test_a2ui_contract_rejects_minimum_charge_without_vehicle_context():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Para cargar lo justo necesito saber tu origen y destino.",
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[],
        message="Quiero cargar lo justo para llegar, sin pagar de más",
    )

    assert any("batería actual" in issue and "modelo/consumo/autonomía" in issue for issue in issues)


def test_a2ui_contract_allows_minimum_charge_with_vehicle_context_request():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Para calcular cuánto cargar necesito origen, destino, batería actual y modelo, "
                        "consumo o autonomía. Sin eso no calcularé kWh ni coste."
                    ),
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[],
        message="Quiero cargar lo justo para llegar, sin pagar de más",
    )

    assert issues == []


def test_conversation_tool_rejects_placeholder_coordinates():
    with pytest.raises(ConversationToolError, match="placeholder 0,0"):
        parse_location_arg({"label": "", "lat": 0, "lon": 0})


def test_a2ui_contract_rejects_empty_stops_without_station_tool_result():
    blocks = validate_blocks(
        [
            {
                "id": "stations",
                "type": "StationList",
                "version": 1,
                "props": {"stations": []},
            }
        ]
    )

    issues = a2ui_contract_issues(blocks, tool_history=[], message="Voy una semana a Cádiz")

    assert any("StationList.stations está vacío" in issue for issue in issues)


def test_a2ui_contract_allows_empty_stops_after_station_tool_result():
    blocks = validate_blocks(
        [
            {
                "id": "stations",
                "type": "StationList",
                "version": 1,
                "props": {"stations": []},
            }
        ]
    )
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Cádiz", "lat": 36.5271, "lon": -6.2886}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Cádiz", "lat": 36.5271, "lon": -6.2886},
                "stops": [],
            },
        }
    ]

    issues = a2ui_contract_issues(blocks, tool_history=tool_history, message="Voy una semana a Cádiz")

    assert not any("StationList.stations está vacío" in issue for issue in issues)


def test_a2ui_contract_rejects_found_chargers_copy_without_station_tool_result():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "Te muestro cargadores disponibles en Cádiz para tu estancia."},
            }
        ]
    )

    issues = a2ui_contract_issues(blocks, tool_history=[], message="Voy una semana a Cádiz")

    assert any("sin resultado de herramienta trazable" in issue for issue in issues)


def test_a2ui_contract_accepts_chargers_only_route_blocks_with_structured_metadata():
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "origin": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                    "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                    "vehicle": None,
                    "preferences": {"reserve_min_percent": 20},
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "origin": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                "distanceKm": 520.3,
                "durationMin": 343,
                "energyKwh": None,
                "arrivalBattery": None,
                "recommendation": {
                    "name": "V-VALENCIA-022-2",
                    "stationName": "V-VALENCIA-022-2",
                    "powerKw": 22,
                    "distanceKm": 1.58,
                    "detourMin": 4,
                    "confidence": "media",
                    "availableEvses": 4,
                    "amenities": ["CAFE", "RESTAURANT"],
                    "scoreReasons": ["Servicios cercanos"],
                    "lat": 39.48123,
                    "lon": -0.389118,
                },
                "alternatives": [
                    {
                        "name": "V-VALENCIA-023",
                        "stationName": "V-VALENCIA-023",
                        "powerKw": 22,
                        "distanceKm": 2.9,
                        "detourMin": 7,
                        "confidence": "media",
                        "availableEvses": 4,
                        "amenities": ["CAFE"],
                        "scoreReasons": ["Servicios cercanos"],
                        "lat": 39.49549,
                        "lon": -0.401537,
                    }
                ],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "Sin consumo ni perfil del vehículo, no puedo validar batería de llegada ni reserva."},
            },
            {
                "id": "route",
                "type": "RouteSummaryCard",
                "version": 1,
                "props": {"distanceKm": 520.3, "durationMin": 343, "energyKwh": None, "arrivalBattery": None},
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "name": "V-VALENCIA-022-2",
                    "stationName": "V-VALENCIA-022-2",
                    "powerKw": 22,
                    "distanceKm": 1.58,
                    "detourMin": 4,
                    "confidence": "media",
                    "availableEvses": 4,
                    "amenities": ["CAFE", "RESTAURANT"],
                    "scoreReasons": ["Servicios cercanos"],
                    "lat": 39.48123,
                    "lon": -0.389118,
                },
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {
                    "stops": [
                        {
                            "name": "V-VALENCIA-023",
                            "stationName": "V-VALENCIA-023",
                            "powerKw": 22,
                            "distanceKm": 2.9,
                            "detourMin": 7,
                            "confidence": "media",
                            "availableEvses": 4,
                            "amenities": ["CAFE"],
                            "scoreReasons": ["Servicios cercanos"],
                            "lat": 39.49549,
                            "lon": -0.401537,
                        }
                    ]
                },
            },
            {
                "id": "margin",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Puedo buscar paradas con un margen conservador por defecto, pero no puedo asegurar que se cumpla sin datos del coche.",
                },
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Voy de Córdoba a Valencia con 58%. No quiero llegar justo",
    )

    assert issues == []


def test_a2ui_contract_rejects_chargers_only_warning_after_alternatives():
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                    "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                    "vehicle": None,
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "distanceKm": 356.7,
                "durationMin": 240,
                "energyKwh": None,
                "arrivalBattery": None,
                "recommendation": {"name": "Moya Hub Honrubia", "powerKw": 240, "distanceKm": 1.23},
                "alternatives": [{"name": "Aparcamiento CTM", "powerKw": 400, "distanceKm": 4.77}],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "route",
                "type": "RouteSummaryCard",
                "version": 1,
                "props": {"distanceKm": 356.7, "durationMin": 240, "energyKwh": None, "arrivalBattery": None},
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Moya Hub Honrubia", "powerKw": 240, "distanceKm": 1.23},
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "Aparcamiento CTM", "powerKw": 400, "distanceKm": 4.77}]},
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "level": "medio",
                    "text": "Sin consumo ni perfil del vehículo, no puedo validar batería de llegada ni reserva.",
                },
            },
        ]
    )

    issues = a2ui_contract_issues(blocks, tool_history, message="Voy de Madrid a Valencia")

    assert any("AssistantMessage inicial debe explicar antes de StationList" in issue for issue in issues)


def test_a2ui_contract_rejects_available_evses_as_connector_count_copy():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                "stops": [
                    {"name": "BALLENOIL-ES336090-COLON", "availableEvses": 2, "powerKw": 150, "distanceKm": 0.3},
                    {"name": "Hotel Córdoba Center", "availableEvses": 3, "powerKw": 22, "distanceKm": 0.59},
                ],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "En Córdoba he encontrado puntos de carga con al menos 2 conectores; ninguno tiene un solo conector."
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "BALLENOIL-ES336090-COLON", "availableEvses": 2, "powerKw": 150, "distanceKm": 0.3},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Evita cargadores con un solo conector. Estoy en Córdoba...",
    )

    assert any("availableEvses como conteo de conectores" in issue for issue in issues)


def test_a2ui_contract_rejects_single_evse_primary_when_user_avoids_single_connector():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                "stops": [
                    {"name": "Single EVSE", "availableEvses": 1, "powerKw": 150, "distanceKm": 0.2},
                    {"name": "Multi EVSE", "availableEvses": 3, "powerKw": 50, "distanceKm": 0.5},
                ],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "Uso puestos de carga registrados para evitar puntos de carga de un solo puesto."},
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Single EVSE", "availableEvses": 1, "powerKw": 150, "distanceKm": 0.2},
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "Multi EVSE", "availableEvses": 3, "powerKw": 50, "distanceKm": 0.5}]},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Evita cargadores con un solo conector. Estoy en Córdoba...",
    )

    assert any("parada primaria tiene solo 1 puesto" in issue for issue in issues)


def test_a2ui_contract_allows_available_evses_copy_for_single_connector_preference():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                "stops": [
                    {"name": "BALLENOIL-ES336090-COLON", "availableEvses": 2, "powerKw": 150, "distanceKm": 0.3},
                    {"name": "Hotel Córdoba Center", "availableEvses": 3, "powerKw": 22, "distanceKm": 0.59},
                ],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Priorizo puntos con mas de 1 puesto registrado; no afirmo ocupacion ni conectores libres en vivo."
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "BALLENOIL-ES336090-COLON", "availableEvses": 2, "powerKw": 150, "distanceKm": 0.3},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Evita cargadores con un solo conector. Estoy en Córdoba...",
    )

    assert issues == []


def test_a2ui_contract_allows_traced_station_price_and_cost_comparison():
    tool_history = [
        {
            "call": {"tool": "search_destination_chargers", "args": {"location": {"label": "Almansa"}}},
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "stops": [
                    {"name": "Almansa HPC", "pricePerKwhEur": 0.49, "currency": "EUR", "priceIsEstimated": False},
                    {"name": "Almansa AC", "pricePerKwhEur": 0.59, "currency": "EUR", "priceIsEstimated": False},
                ],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "station",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Almansa HPC", "pricePerKwhEur": 0.49, "currency": "EUR", "priceIsEstimated": False},
            },
            {
                "id": "cost",
                "type": "CostComparisonCard",
                "version": 1,
                "props": {
                    "best": "Almansa HPC",
                    "pricePerKwhEur": 0.49,
                    "comparedWith": "Almansa AC",
                    "comparedWithPricePerKwhEur": 0.59,
                    "savingPerKwhEur": 0.10,
                    "currency": "EUR",
                    "priceIsEstimated": False,
                },
            },
        ]
    )

    issues = a2ui_contract_issues(blocks, tool_history)

    assert issues == []


def test_a2ui_contract_rejects_estimated_or_mismatched_prices():
    tool_history = [
        {
            "call": {"tool": "search_destination_chargers", "args": {"location": {"label": "Almansa"}}},
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "stops": [
                    {"name": "Almansa HPC", "pricePerKwhEur": 0.49, "currency": "EUR", "priceIsEstimated": True},
                    {"name": "Almansa AC", "pricePerKwhEur": 0.59, "currency": "EUR", "priceIsEstimated": False},
                ],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "station",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Almansa HPC", "pricePerKwhEur": 0.49, "currency": "EUR", "priceIsEstimated": True},
            },
            {
                "id": "cost",
                "type": "CostComparisonCard",
                "version": 1,
                "props": {
                    "best": "Almansa AC",
                    "pricePerKwhEur": 0.42,
                    "currency": "EUR",
                    "priceIsEstimated": False,
                },
            },
        ]
    )

    issues = a2ui_contract_issues(blocks, tool_history)

    assert any("tarifa para Almansa HPC está marcada como estimada" in issue for issue in issues)
    assert any("pricePerKwhEur no coincide" in issue for issue in issues)


def test_a2ui_contract_rejects_untraced_default_reserve_attribution():
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "origin": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                    "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                    "preferences": {"reserve_min_percent": 20},
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "distanceKm": 520.3,
                "durationMin": 343,
                "energyKwh": None,
                "arrivalBattery": None,
                "recommendation": {"name": "V-VALENCIA-022-2"},
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "level": "medio",
                    "text": "No puedo asegurar que llegues con el 20% de reserva que pides sin datos del coche.",
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Voy de Córdoba a Valencia con 58%. No quiero llegar justo",
    )

    assert any("reserva porcentual que no dijo" in issue for issue in issues)


def test_a2ui_contract_rejects_unvalidated_margin_guarantee_in_chargers_only_route():
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "origin": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                    "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                    "preferences": {"reserve_min_percent": 20},
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "distanceKm": 520.3,
                "durationMin": 343,
                "energyKwh": None,
                "arrivalBattery": None,
                "recommendation": {"name": "V-VALENCIA-022-2"},
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "level": "medio",
                    "text": "Te recomiendo cargar en esta parada antes de entrar a Valencia para asegurar margen.",
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Voy de Córdoba a Valencia con 58%. No quiero llegar justo",
    )

    assert any("da certeza sobre recuperar margen" in issue for issue in issues)


def test_a2ui_contract_rejects_certain_margin_recovery_in_chargers_only():
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                    "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "distanceKm": 356.7,
                "durationMin": 240,
                "energyKwh": None,
                "arrivalBattery": None,
                "recommendation": {"name": "Moya Hub Honrubia"},
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "level": "medio",
                    "text": "Cargar en esta parada te ayudará a recuperar margen operativo, pero no está garantizado.",
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Prefiero desviarme 10 minutos si el sitio es más cómodo. Voy de Madrid a Valencia con 60%",
    )

    assert any("da certeza sobre recuperar margen" in issue for issue in issues)


def test_a2ui_contract_rejects_unasked_few_stops_copy():
    blocks = validate_blocks(
        [
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Sin datos de autonomía ni consumo, no puedo validar la batería de llegada. "
                        "Si prefieres parar pocas veces, necesito el modelo o consumo."
                    )
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        [],
        message="Prefiero desviarme 10 minutos si el sitio es más cómodo. Voy de Madrid a Valencia con 60%",
    )

    assert any("preferencia de pocas paradas" in issue for issue in issues)


def test_a2ui_contract_rejects_future_route_without_volatility_warning():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Te muestro paradas de carga en el corredor. No puedo validar la batería de llegada.",
                },
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "level": "medio",
                    "text": "Sin consumo ni batería usable, el margen no está validado.",
                },
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[],
        message="Voy de Madrid a Málaga mañana y salgo con 80%",
    )

    assert any("disponibilidad, acceso y tarifas pueden cambiar" in issue for issue in issues)


def test_a2ui_contract_rejects_departure_battery_as_arrival_battery():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "No puedo validar si llegas con el 80% sin datos de consumo.",
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[],
        message="Voy de Madrid a Málaga mañana y salgo con 80%",
    )

    assert any("80% de salida" in issue for issue in issues)


def test_a2ui_contract_rejects_future_warning_after_alternatives():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "He preparado la ruta con paradas de carga recomendadas."},
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "Manzanares - El Cruce", "powerKw": 180, "distanceKm": 2.23}]},
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "level": "medio",
                    "text": (
                        "Al ser un viaje futuro, la disponibilidad, acceso y tarifas pueden cambiar antes del viaje."
                    ),
                },
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[
            {
                "call": {"tool": "plan_route", "args": {}},
                "result": {
                    "ok": True,
                    "tool": "plan_route",
                    "recommendation": {"name": "Manzanares - El Cruce"},
                },
            }
        ],
        message="Voy de Madrid a Málaga mañana y salgo con 80%",
    )

    assert any("antes de StationPreviewCard/StationList" in issue for issue in issues)


def test_a2ui_contract_rejects_future_warning_after_recommended_stop():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "Te muestro paradas de carga en el corredor."},
            },
            {
                "id": "stop",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Aparcamiento CTM", "powerKw": 400, "distanceKm": 2.29},
            },
            {
                "id": "warning",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Mañana la disponibilidad, acceso y tarifas pueden cambiar antes del viaje.",
                },
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=[
            {
                "call": {"tool": "plan_route", "args": {}},
                "result": {
                    "ok": True,
                    "tool": "plan_route",
                    "recommendation": {"name": "Aparcamiento CTM"},
                },
            }
        ],
        message="Voy de Madrid a Málaga mañana y salgo con 80%",
    )

    assert any("antes de StationPreviewCard/StationList" in issue for issue in issues)


def test_a2ui_contract_allows_future_route_with_volatility_warning():
    tool_history = [
        {
            "call": {
                "tool": "plan_route",
                "args": {
                    "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                    "destination": {"label": "Málaga", "lat": 36.7213, "lon": -4.4214},
                },
            },
            "result": {
                "ok": True,
                "tool": "plan_route",
                "planningLevel": "chargers_only",
                "recommendation": {"name": "Aparcamiento CTM"},
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Te muestro paradas autorizadas en el corredor. Para mañana, confirma disponibilidad, "
                        "acceso y tarifas porque pueden cambiar antes del viaje."
                    ),
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history=tool_history,
        message="Voy de Madrid a Málaga mañana y salgo con 80%",
    )

    assert issues == []


def test_a2ui_contract_rejects_visible_amenity_proximity_copy():
    blocks = validate_blocks(
        [
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "level": "medio",
                    "text": "La parada tiene cafetería cerca para esperar con comodidad.",
                },
            }
        ]
    )

    issues = a2ui_contract_issues(blocks, tool_history=[], message="Voy con niños")

    assert any("servicio está cerca" in issue for issue in issues)


def test_decode_agent_json_accepts_stdout_when_output_file_is_empty():
    payload = decode_agent_json("", '{"type":"tool_call","tool":"resolve_location","args":{"query":"Córdoba"}}')

    assert payload["type"] == "tool_call"
    assert payload["args"]["query"] == "Córdoba"


def test_decode_agent_json_extracts_fenced_or_wrapped_json():
    fenced = '```json\n{"type":"final","blocks":[]}\n```'
    wrapped = 'Respuesta:\n{"type":"final","blocks":[]}\nFin.'

    assert decode_agent_json(fenced)["type"] == "final"
    assert decode_agent_json(wrapped)["blocks"] == []


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


def test_deepseek_decision_parser_normalizes_misplaced_tool_call_block():
    decision = parse_openai_compatible_decision(
        {
            "content": json.dumps(
                {
                    "type": "final",
                    "blocks": [
                        {
                            "id": "intro",
                            "type": "AssistantMessage",
                            "version": 1,
                            "props": {"text": "Voy a buscar puntos de carga cerca de Córdoba."},
                        },
                        {
                            "id": "search",
                            "type": "tool_call",
                            "tool": "search_destination_chargers",
                            "args": {
                                "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                                "connector": None,
                                "radius_km": 80,
                                "limit": 3,
                            },
                        },
                    ],
                },
                ensure_ascii=False,
            )
        }
    )

    assert decision == {
        "type": "tool_call",
        "tool": "search_destination_chargers",
        "args": {
            "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
            "connector": None,
            "radius_km": 80,
            "limit": 3,
        },
    }


def test_deepseek_repair_decision_disables_native_tools(monkeypatch):
    calls = []

    def fake_deepseek_decision(prompt, allow_tools=True):
        calls.append((prompt, allow_tools))
        return {"type": "final", "blocks": []}

    monkeypatch.setattr("routing.agent.call_deepseek_decision", fake_deepseek_decision)

    decision = run_deepseek_decision(
        "Busca cargadores cerca de Valencia",
        repair_issues=["StationList necesita datos trazables."],
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


def test_contextualized_prompt_summarizes_explicit_vehicle_facts_for_agent():
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
                "id": "assistant-hotel",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "¿Qué hotel o zona exacta?"},
            }
        ],
    )

    assert "Pista de ubicación conocida detectada en el mensaje actual" in prompt
    assert "Córdoba (37.8882, -4.7794)" in prompt
    assert "no una decisión de intención" in prompt


def test_contextualized_prompt_includes_previous_alternative_stop_details_for_plan_b():
    prompt = contextualized_prompt(
        "El cargador al que iba está ocupado, dame un plan B",
        [
            {
                "id": "user-1",
                "type": "UserMessage",
                "version": 1,
                "props": {"text": "Estoy al 8% y no conozco la zona"},
            },
            {
                "id": "urgent-1",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "name": "BALLENOIL-ES336090-COLON",
                    "stationName": "BALLENOIL-ES336090-COLON",
                    "distanceKm": 0.3,
                },
            },
            {
                "id": "alternatives-1",
                "type": "StationList",
                "version": 1,
                "props": {
                    "stations": [
                        {
                            "name": "Parking Calle Sevilla Nº5 - Córdoba",
                            "distanceKm": 0.5,
                            "powerKw": 22,
                            "connectorTypes": ["TYPE2"],
                            "lat": 37.883857,
                            "lon": -4.780831,
                        },
                        {
                            "name": "Hotel Córdoba Center",
                            "distanceKm": 0.59,
                            "powerKw": 22,
                            "connectorTypes": ["TYPE2"],
                            "lat": 37.892339,
                            "lon": -4.783527,
                        },
                    ]
                },
            },
        ],
    )

    assert "batería 8%" in prompt
    assert "Estación mostrada previamente: BALLENOIL-ES336090-COLON" in prompt
    assert "Estaciones mostradas con datos trazables:" in prompt
    assert "Parking Calle Sevilla Nº5 - Córdoba (distancia 0.5 km, potencia 22 kW" in prompt
    assert "coordenadas 37.883857,-4.780831" in prompt
    assert "Hotel Córdoba Center (distancia 0.59 km, potencia 22 kW" in prompt
    assert "Mensaje actual del usuario: El cargador al que iba está ocupado, dame un plan B" in prompt


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
    assert blocks_from_a2ui_response(first_response)[-1]["type"] == "PositionRequestCard"

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
    assert "StationPreviewCard" in new_block_types
    assert "PositionRequestCard" not in new_block_types
    urgent_block = next(block for block in new_blocks if block["type"] == "StationPreviewCard")
    assert urgent_block["props"]["name"] == station.name
    assert urgent_block["props"]["stationName"] == station.name


@pytest.mark.django_db
def test_deepseek_hotel_followup_with_known_city_can_search_from_location_hint(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
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

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        messages_seen.append(message)
        if "Hotel Meliá cordoba" not in message:
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "assistant-hotel",
                        "type": "AssistantMessage",
                        "version": 1,
                        "props": {
                            "text": "¿Qué hotel o qué ciudad/zona quieres usar?",
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
                    "id": "assistant-cordoba",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {
                        "text": (
                            "No tengo la ubicación exacta del hotel Meliá; uso Córdoba como aproximación. "
                            "Si me das la dirección o zona exacta puedo refinar la búsqueda."
                        )
                    },
                },
                {
                    "id": "stops-cordoba",
                    "type": "StationList",
                    "version": 1,
                    "props": {"stations": tool_result["stops"]},
                },
                {
                    "id": "risk-cordoba",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {
                        "level": "medio",
                        "text": "Confirma acceso final, tarifa y disponibilidad antes de depender de estos cargadores.",
                    },
                },
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

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
    assert any(block["type"] == "StationPreviewCard" for block in blocks_from_a2ui_response(location_response))

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
    assert "StationPreviewCard" in new_block_types

    urgent_block = next(block for block in new_blocks if block["type"] == "StationPreviewCard")
    assert urgent_block["props"]["name"] == station.name
    assert urgent_block["props"]["stationName"] == station.name


@pytest.mark.django_db
def test_deepseek_conversation_agent_interprets_vehicle_followup_from_available_transcript(
    client, settings, monkeypatch
):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    captured_messages = []
    session = client.session
    session[ACTIVE_CONVERSATION_BLOCKS_KEY] = [
        {"id": "user-urgent", "type": "UserMessage", "version": 1, "props": {"text": "Necesito cargar ya"}},
        {
            "id": "location-request",
            "type": "PositionRequestCard",
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
            "type": "StationDetailCard",
            "version": 1,
            "props": {
                "name": "Eurostars Maimonides - 135",
                "stationName": "Eurostars Maimonides - 135",
                "distanceKm": 0.16,
            },
        },
    ]
    session.save()

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        captured_messages.append(message)
        blocks = [
            {
                    "id": "urgent-with-battery",
                    "type": "StationDetailCard",
                    "version": 1,
                    "props": {
                        "name": "Eurostars Maimonides - 135",
                        "stationName": "Eurostars Maimonides - 135",
                        "distanceKm": 0.16,
                    },
                }
        ]
        if repair_issues:
            blocks.append(
                {
                    "id": "urgent-risk",
                    "type": "AssistantMessage",
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

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Tengo un 20%"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert captured_messages
    assert "Usuario: Necesito cargar ya" in captured_messages[0]
    assert "Usuario: Estoy en 37.880729, -4.782446" in captured_messages[0]
    assert "Estación mostrada previamente: Eurostars Maimonides - 135" in captured_messages[0]
    assert "Mensaje actual del usuario: Tengo un 20%" in captured_messages[0]
    latest_urgent_block = next(
        block for block in reversed(blocks_from_a2ui_response(response)) if block["type"] == "StationDetailCard"
    )
    assert latest_urgent_block["props"]["name"] == "Eurostars Maimonides - 135"
    assert "battery" not in latest_urgent_block["props"]


@pytest.mark.django_db
def test_deepseek_conversation_agent_does_not_repair_component_choice_from_urgent_history(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    repair_requests = []
    session = client.session
    session[ACTIVE_CONVERSATION_BLOCKS_KEY] = [
        {"id": "user-urgent", "type": "UserMessage", "version": 1, "props": {"text": "Necesito cargar ya"}},
        {
            "id": "location-request",
            "type": "PositionRequestCard",
            "version": 1,
            "props": {
                "reason": "urgent_charge",
                "title": "Necesito tu ubicación",
                "body": "Comparte ubicación para buscar cargadores.",
            },
        },
    ]
    session.save()

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        if repair_issues:
            repair_requests.append(repair_issues)
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "wrong-destination",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {"text": "Uso Córdoba como ubicación aproximada para esta búsqueda."},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Estoy en Córdoba con un 18%"},
        content_type="application/json",
    )

    assert response.status_code == 200
    new_blocks = blocks_from_a2ui_response(response)[len(session[ACTIVE_CONVERSATION_BLOCKS_KEY]) :]
    block_types = [block["type"] for block in new_blocks]
    assert repair_requests == []
    assert "AssistantMessage" in block_types
    assert "StationDetailCard" not in block_types


@pytest.mark.django_db
def test_deepseek_conversation_agent_executes_allowlisted_tool(client, settings, monkeypatch, real_station):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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
                    "id": "assistant-from-tool",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {
                        "text": (
                            "Uso Almansa como aproximación porque no tengo la dirección exacta del hotel. "
                            "Dime dirección o zona exacta para refinar la búsqueda."
                        )
                    },
                },
                {
                    "id": "stops-from-tool",
                    "type": "StationList",
                    "version": 1,
                    "props": {"stations": tool_result["stops"]},
                },
                {
                    "id": "risk-from-tool",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {
                        "level": "medio",
                        "text": (
                            "Confirma disponibilidad antes de depender de estos cargadores. "
                            "Si me das la dirección exacta del hotel, puedo afinar."
                        ),
                    },
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
    blocks = blocks_from_a2ui_response(response)
    block_types = [block["type"] for block in blocks]
    assert "UserMessage" in block_types
    assert "StationList" in block_types
    stops_block = next(block for block in blocks if block["type"] == "StationList")
    assert stops_block["props"]["stations"][0]["name"] == real_station.name


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
                    "id": "assistant-deepseek",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {
                        "text": (
                            "Uso Almansa como aproximación porque no tengo la dirección exacta del hotel. "
                            "Dime dirección o zona exacta para refinar la búsqueda."
                        )
                    },
                },
                {
                    "id": "stops-deepseek",
                    "type": "StationList",
                    "version": 1,
                    "props": {"stations": tool_result["stops"]},
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
    stops_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "StationList")
    assert stops_block["props"]["stations"][0]["name"] == real_station.name
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
def test_deepseek_conversation_agent_rejects_unknown_tool_with_assistant_message(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"

    def fake_deepseek_decision(message, tool_history=None):
        return {"type": "tool_call", "tool": "delete_everything", "args": {}}

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Haz algo no permitido"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert any(
        "No puedo hacer esa acción desde el chat" in block["props"]["text"]
        for block in blocks_from_a2ui_response(response)
        if block["type"] == "AssistantMessage"
    )


@pytest.mark.django_db
def test_deepseek_allowed_tool_failure_returns_to_agent_for_contextual_final(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    calls = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

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
def test_deepseek_station_list_requires_traced_station_data(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    repair_requests = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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
                    "id": "place-from-agent",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {"text": "Uso Valencia como ubicación aproximada para la búsqueda."},
                },
                {
                    "id": "stops-from-agent",
                    "type": "StationList",
                    "version": 1,
                    "props": {"stations": [{"name": "Cargador real", "powerKw": 50, "distanceKm": 1.2}]},
                },
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

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
def test_deepseek_conversation_agent_allows_bounded_tool_chain(client, settings, monkeypatch, real_station):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
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

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {"text": "Uso Valencia como ubicación aproximada para la búsqueda."},
                },
                {
                    "id": "stops-from-chain",
                    "type": "StationList",
                    "version": 1,
                    "props": {"stations": tool_history[-1]["result"]["stops"]},
                },
                {
                    "id": "risk-from-chain",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {"level": "medio", "text": "Confirma disponibilidad antes de depender de estos cargadores."},
                },
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert calls == [0, 1, 2]
    blocks = blocks_from_a2ui_response(response)
    assert any(
        block["type"] == "AssistantMessage" and "Valencia" in block["props"].get("text", "")
        for block in blocks
    )
    stops_block = next(block for block in blocks if block["type"] == "StationList")
    assert stops_block["props"]["stations"][0]["name"] == valencia_station.name


@pytest.mark.django_db
def test_deepseek_conversation_agent_allows_agent_chosen_text_final_after_tool(client, settings, monkeypatch, real_station):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    repair_requests = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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
                        "props": {
                            "text": (
                                f"He encontrado {real_station.name} usando Almansa como aproximación, "
                                "porque no tengo la dirección exacta del hotel. Dime dirección o zona exacta para refinar."
                            )
                        },
                    }
                ],
            }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

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
def test_deepseek_conversation_agent_repairs_untraced_structured_station_data(client, settings, monkeypatch, real_station):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    repair_requests = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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
                        "id": "assistant-repaired",
                        "type": "AssistantMessage",
                        "version": 1,
                        "props": {
                            "text": (
                                "Uso Almansa como aproximación porque no tengo la dirección exacta del hotel. "
                                "Dime dirección o zona exacta para refinar la búsqueda."
                            )
                        },
                    },
                    {
                        "id": "stops-repaired",
                        "type": "StationList",
                        "version": 1,
                        "props": {"stations": tool_result["stops"]},
                    }
                ],
            }
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "invented-stop",
                    "type": "StationList",
                    "version": 1,
                    "props": {"stations": [{"name": "Fake HPC", "powerKw": 350, "distanceKm": 0.1}]},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

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
def test_deepseek_conversation_agent_repairs_generic_station_name_when_tool_has_station(
    client, settings, monkeypatch, real_station
):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    repair_requests = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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
                        "type": "StationDetailCard",
                        "version": 1,
                        "props": {
                            "name": tool_result["stops"][0]["name"],
                            "stationName": tool_result["stops"][0]["name"],
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
                    "type": "StationDetailCard",
                    "version": 1,
                    "props": {"name": "Cargador cercano por confirmar", "distanceKm": 0.1},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya cerca de Almansa"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert repair_requests
    assert "debe usar una estación trazable" in repair_requests[0][0]
    urgent_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "StationDetailCard")
    assert urgent_block["props"]["name"] == real_station.name
    assert urgent_block["props"]["stationName"] == real_station.name


@pytest.mark.django_db
def test_deepseek_conversation_agent_does_not_force_user_battery_into_station_detail(
    client, settings, monkeypatch, real_station
):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    repair_requests = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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
                        "type": "StationDetailCard",
                        "version": 1,
                        "props": {
                            "name": tool_result["stops"][0]["name"],
                            "stationName": tool_result["stops"][0]["name"],
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
                    "type": "StationDetailCard",
                    "version": 1,
                    "props": {
                        "name": tool_result["stops"][0]["name"],
                        "stationName": tool_result["stops"][0]["name"],
                        "distanceKm": tool_result["stops"][0]["distanceKm"],
                    },
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya, estoy al 12% en Almansa"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert repair_requests == []
    urgent_block = next(block for block in blocks_from_a2ui_response(response) if block["type"] == "StationDetailCard")
    assert urgent_block["props"]["name"] == real_station.name
    assert "battery" not in urgent_block["props"]


@pytest.mark.django_db
def test_deepseek_conversation_agent_allows_risk_copy_in_assistant_message(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "risk-copy",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {"text": "Confirma acceso final, tarifa y disponibilidad porque los datos pueden cambiar."},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Tengo poca batería y voy con niños"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert any(
        "Confirma acceso final" in block["props"]["text"]
        for block in blocks_from_a2ui_response(response)
        if block["type"] == "AssistantMessage"
    )


@pytest.mark.django_db
def test_deepseek_conversation_agent_repairs_unsupported_action_buttons(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    repair_requests = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

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
                                "args": {"url": "https://www.google.com/maps/search/?api=1&query=Kalmio"},
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


def test_action_buttons_reject_station_navigation_with_wrong_coordinates_from_city_location():
    station = {
        "name": "E-V-Valencia-076",
        "distance_km": 0.3,
        "connectors": [{"type": "CCS2", "count": 2, "power_kw": 100, "available": True}],
        "location": {"lat": 39.472345, "lon": -0.381234},
    }
    issues = a2ui_contract_issues(
        [
            {
                "id": "actions",
                "type": "ActionButtons",
                "version": 1,
                "props": {
                    "actions": [
                        {
                            "label": "Navegar a E-V-Valencia-076",
                            "functionCall": {
                                "call": "openUrl",
                                "args": {"url": "https://maps.google.com/?daddr=39.4699,-0.3763"},
                            },
                        }
                    ]
                },
            }
        ],
        [],
        history_blocks=[
            {
                "id": "previous-stops",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [station]},
            }
        ],
    )

    assert any("no coinciden con la estación trazable 'E-V-Valencia-076'" in issue for issue in issues)


def test_action_buttons_accept_station_navigation_with_variant_station_coordinates():
    station = {
        "name": "E-V-Valencia-076",
        "distance_km": 0.3,
        "connectors": [{"type": "CCS2", "count": 2, "power_kw": 100, "available": True}],
        "location": {"lat": 39.472345, "lon": -0.381234},
    }
    issues = a2ui_contract_issues(
        [
            {
                "id": "actions",
                "type": "ActionButtons",
                "version": 1,
                "props": {
                    "actions": [
                        {
                            "label": "Navegar a E-V-Valencia-076",
                            "functionCall": {
                                "call": "openUrl",
                                "args": {"url": "https://maps.google.com/?daddr=39.472345,-0.381234"},
                            },
                        }
                    ]
                },
            }
        ],
        [],
        history_blocks=[
            {
                "id": "previous-stops",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [station]},
            }
        ],
    )

    assert issues == []


def test_variant_station_coordinates_are_validated_against_traced_history():
    traced_station = {
        "name": "E-V-Valencia-076",
        "powerKw": 100,
        "distanceKm": 0.3,
        "lat": 39.472345,
        "lon": -0.381234,
    }
    issues = a2ui_contract_issues(
        [
            {
                "id": "stops",
                "type": "StationList",
                "version": 1,
                "props": {
                    "stations": [
                        {
                            "name": "E-V-Valencia-076",
                            "distance_km": 0.3,
                            "connectors": [{"type": "CCS2", "count": 2, "power_kw": 100, "available": True}],
                            "location": {"lat": 39.4699, "lon": -0.3763},
                        }
                    ]
                },
            }
        ],
        [],
        history_blocks=[
            {
                "id": "previous-stops",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [traced_station]},
            }
        ],
    )

    assert any("StationList.stations[0].lat no coincide" in issue for issue in issues)
    assert any("StationList.stations[0].lon no coincide" in issue for issue in issues)


def test_resolve_location_marks_poi_query_as_city_approximation():
    result = resolve_location_tool({"query": "Atocha, Madrid"})

    assert result["ok"] is True
    assert result["location"]["label"] == "Madrid"
    assert result["location"]["precision"] == "city_approximation"
    assert result["location"]["query"] == "Atocha, Madrid"


def test_structured_blocks_require_visible_copy_when_location_is_approximate():
    tool_history = [
        {
            "call": {"tool": "resolve_location", "args": {"query": "Atocha, Madrid"}},
            "result": {
                "ok": True,
                "location": {
                    "label": "Madrid",
                    "lat": 40.4168,
                    "lon": -3.7038,
                    "precision": "city_approximation",
                    "query": "Atocha, Madrid",
                },
            },
        },
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                "stops": [
                    {
                        "name": "Telpark - Plaza del Carmen",
                        "powerKw": 360,
                        "distanceKm": 0.23,
                        "availableEvses": 23,
                        "lat": 40.418803,
                        "lon": -3.703231,
                    }
                ],
            },
        },
    ]
    issues = a2ui_contract_issues(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "name": "Telpark - Plaza del Carmen",
                    "stationName": "Telpark - Plaza del Carmen",
                    "distanceKm": 0.23,
                    "risk": "Batería crítica. Ve al cargador cercano.",
                },
            }
        ],
        tool_history,
        "Estoy cerca de Atocha, Madrid",
    )

    assert any("'Atocha, Madrid' -> 'Madrid'" in issue for issue in issues)


def test_structured_blocks_allow_visible_copy_when_location_is_approximate():
    tool_history = [
        {
            "call": {"tool": "resolve_location", "args": {"query": "Atocha, Madrid"}},
            "result": {
                "ok": True,
                "location": {
                    "label": "Madrid",
                    "lat": 40.4168,
                    "lon": -3.7038,
                    "precision": "city_approximation",
                    "query": "Atocha, Madrid",
                },
            },
        },
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                "stops": [
                    {
                        "name": "Telpark - Plaza del Carmen",
                        "powerKw": 360,
                        "distanceKm": 0.23,
                        "availableEvses": 23,
                        "lat": 40.418803,
                        "lon": -3.703231,
                    }
                ],
            },
        },
    ]
    issues = a2ui_contract_issues(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "No tengo la ubicación exacta de Atocha; uso Madrid como aproximación."},
            },
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "name": "Telpark - Plaza del Carmen",
                    "stationName": "Telpark - Plaza del Carmen",
                    "distanceKm": 0.23,
                    "risk": "Batería crítica. Ve al cargador cercano.",
                },
            },
        ],
        tool_history,
        "Estoy cerca de Atocha, Madrid",
    )

    assert issues == []


def test_comfort_copy_rejects_untraced_children_claims():
    issues = a2ui_contract_issues(
        [
            {
                "id": "urgent",
                "type": "StationDetailCard",
                "version": 1,
                "props": {
                    "name": "BALLENOIL-ES336090-COLON",
                    "stationName": "BALLENOIL-ES336090-COLON",
                    "distanceKm": 0.3,
                    "risk": "Dispone de cafetería y supermercado cerca, útil para entretener a los niños.",
                },
            }
        ],
        [
            {
                "call": {"tool": "search_destination_chargers", "args": {"location": {"label": "Córdoba"}}},
                "result": {
                    "ok": True,
                    "tool": "search_destination_chargers",
                    "stops": [
                        {
                            "name": "BALLENOIL-ES336090-COLON",
                            "distanceKm": 0.3,
                            "amenities": ["CAFE", "SUPERMARKET"],
                        }
                    ],
                },
            }
        ],
    )

    assert any("claim de seguridad/comodidad para niños no respaldado por datos" in issue for issue in issues)


def test_comfort_copy_allows_service_location_clarifying_question():
    issues = a2ui_contract_issues(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Para buscar una parada con baños y cafetería, necesito saber la ubicación "
                        "(ciudad, zona o coordenadas) donde quieres cargar. ¿Dónde estás o cerca de qué lugar buscas?"
                    )
                },
            }
        ],
        [],
        message="Busca una parada con baños y cafetería",
    )

    assert issues == []


def test_comfort_copy_allows_traced_amenities_as_potential_convenience():
    issues = a2ui_contract_issues(
        [
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Servicios indicados en el punto: CAFE y SUPERMARKET. Pueden ayudar como comodidad potencial; confirma antes de depender de ellos."
                },
            }
        ],
        [],
    )

    assert issues == []


def test_comfort_copy_allows_nearby_station_with_separate_traced_amenities():
    issues = a2ui_contract_issues(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "La estación recomendada está cerca de Córdoba. "
                        "Servicios indicados en el punto: CAFE y SUPERMARKET; confirma antes de depender de ellos."
                    )
                },
            }
        ],
        [],
    )

    assert issues == []


def test_comfort_copy_allows_perfecto_as_conversational_acknowledgement():
    issues = a2ui_contract_issues(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Perfecto, tienes ruta de Madrid a Valencia con 60% de batería. "
                        "Prefieres desviarte hasta 10 minutos por más comodidad."
                    )
                },
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "La parada tiene servicios indicados; confirma disponibilidad y acceso antes de depender de ellos."
                },
            },
        ],
        [],
    )

    assert issues == []


def test_comfort_copy_rejects_subjective_good_services_claim():
    issues = a2ui_contract_issues(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "Te muestro una parada de carga en el corredor con buenos servicios."},
            }
        ],
        [],
    )

    assert any("claim de seguridad/comodidad" in issue for issue in issues)


def test_requested_service_contract_rejects_missing_unverified_copy_when_tool_has_no_amenities():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Almansa", "lat": 38.869, "lon": -1.0971}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Almansa", "lat": 38.869, "lon": -1.0971},
                "stops": [
                    {"name": "Consum Almansa", "powerKw": 100, "distanceKm": 0.49, "amenities": []},
                    {"name": "Repsol ES, CRED Almansa", "powerKw": 50, "distanceKm": 0.68, "amenities": []},
                ],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "He encontrado cargadores en Almansa."},
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Consum Almansa", "powerKw": 100, "distanceKm": 0.49},
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "Repsol ES, CRED Almansa", "powerKw": 50, "distanceKm": 0.68}]},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Busca una parada con baños y cafetería Estoy cerca de Almansa",
    )

    assert any("no los trazó" in issue for issue in issues)


def test_requested_service_contract_allows_unverified_copy_when_tool_has_no_amenities():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Almansa", "lat": 38.869, "lon": -1.0971}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Almansa", "lat": 38.869, "lon": -1.0971},
                "stops": [{"name": "Consum Almansa", "powerKw": 100, "distanceKm": 0.49, "amenities": []}],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "He encontrado cargadores autorizados en Almansa, pero baños y cafetería "
                        "no están verificados en estos resultados."
                    )
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Consum Almansa", "powerKw": 100, "distanceKm": 0.49},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Busca una parada con baños y cafetería Estoy cerca de Almansa",
    )

    assert issues == []


def test_comfort_copy_allows_charger_proximity_with_unverified_service_disclaimer():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Almansa", "lat": 38.869, "lon": -1.0971}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Almansa", "lat": 38.869, "lon": -1.0971},
                "stops": [{"name": "Consum Almansa", "powerKw": 100, "distanceKm": 0.49, "amenities": []}],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Estos son puntos de carga encontrados cerca de Almansa. "
                        "Los servicios como baños o cafetería no están verificados en estos resultados."
                    )
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "Consum Almansa", "powerKw": 100, "distanceKm": 0.49},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Busca una parada con baños y cafetería Estoy cerca de Almansa",
    )

    assert issues == []


def test_night_safety_contract_rejects_untraced_affluence_claims():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "He priorizado opciones céntricas con más afluencia."},
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "Al estar en zona céntrica, es menos probable que sean solitarios; verifica el entorno."
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "E-V-Valencia-091", "powerKw": 100, "distanceKm": 0.17},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        [
            {
                "call": {"tool": "search_destination_chargers", "args": {"location": {"label": "Valencia centro"}}},
                "result": {
                    "ok": True,
                    "tool": "search_destination_chargers",
                    "stops": [{"name": "E-V-Valencia-091", "powerKw": 100, "distanceKm": 0.17}],
                },
            }
        ],
        message="No quiero cargar en sitios solitarios de noche Estoy en Valencia centro",
    )

    assert any("inferencia de seguridad nocturna no respaldada por datos" in issue for issue in issues)


def test_night_safety_contract_rejects_warning_after_alternatives():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "He priorizado puntos autorizados cerca de Valencia centro usando datos disponibles."
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "E-V-Valencia-091", "powerKw": 100, "distanceKm": 0.17},
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "E-V-Valencia-076", "powerKw": 22, "distanceKm": 0.18}]},
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "No puedo validar seguridad, iluminación ni afluencia en vivo. "
                        "Verifica el entorno si llegas de noche."
                    )
                },
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        [
            {
                "call": {"tool": "search_destination_chargers", "args": {"location": {"label": "Valencia centro"}}},
                "result": {
                    "ok": True,
                    "tool": "search_destination_chargers",
                    "stops": [
                        {"name": "E-V-Valencia-091", "powerKw": 100, "distanceKm": 0.17},
                        {"name": "E-V-Valencia-076", "powerKw": 22, "distanceKm": 0.18},
                    ],
                },
            }
        ],
        message="No quiero cargar en sitios solitarios de noche Estoy en Valencia centro",
    )

    assert any("AssistantMessage inicial debe explicar" in issue for issue in issues)


def test_night_safety_contract_allows_traced_central_copy_with_early_risk():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "He priorizado puntos autorizados cerca de Valencia centro usando dirección, potencia y puestos de carga registrados. "
                        "No puedo validar seguridad, iluminación, afluencia ni vigilancia en vivo. "
                        "Confirma acceso, disponibilidad y verifica el entorno si llegas de noche."
                    )
                },
            },
            {
                "id": "recommended",
                "type": "StationDetailCard",
                "version": 1,
                "props": {"name": "E-V-Valencia-091", "powerKw": 100, "distanceKm": 0.17},
            },
            {
                "id": "alternatives",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "E-V-Valencia-076", "powerKw": 22, "distanceKm": 0.18}]},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        [
            {
                "call": {"tool": "search_destination_chargers", "args": {"location": {"label": "Valencia centro"}}},
                "result": {
                    "ok": True,
                    "tool": "search_destination_chargers",
                    "stops": [
                        {"name": "E-V-Valencia-091", "powerKw": 100, "distanceKm": 0.17},
                        {"name": "E-V-Valencia-076", "powerKw": 22, "distanceKm": 0.18},
                    ],
                },
            }
        ],
        message="No quiero cargar en sitios solitarios de noche Estoy en Valencia centro",
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


def test_a2ui_contract_rejects_hotel_exact_destination_from_city_search():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                "stops": [{"name": "BALLENOIL-ES336090-COLON", "distanceKm": 0.3, "powerKw": 150}],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": "He buscado puntos de carga cerca de Córdoba para tu estancia en el hotel Meliá."
                },
            },
            {
                "id": "stops",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "BALLENOIL-ES336090-COLON", "distanceKm": 0.3, "powerKw": 150}]},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Me voy 3 días a Córdoba y me quedo en el hotel Meliá",
    )

    assert any("debe decir visiblemente que es una aproximación" in issue for issue in issues)
    assert any("para refinar la búsqueda" in issue for issue in issues)


def test_a2ui_contract_allows_hotel_city_approximation_with_refinement_request():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Córdoba", "lat": 37.8882, "lon": -4.7794},
                "stops": [{"name": "BALLENOIL-ES336090-COLON", "distanceKm": 0.3, "powerKw": 150}],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "No tengo la ubicación exacta del hotel Meliá; uso Córdoba como aproximación. "
                        "Si me das la dirección o zona exacta puedo refinar la búsqueda."
                    )
                },
            },
            {
                "id": "stops",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "BALLENOIL-ES336090-COLON", "distanceKm": 0.3, "powerKw": 150}]},
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "Confirma acceso final, tarifa y disponibilidad antes de depender de estos puntos."},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message="Me voy 3 días a Córdoba y me quedo en el hotel Meliá",
    )

    assert issues == []


def test_a2ui_contract_allows_weekend_alhambra_destination_with_early_warning():
    tool_history = [
        {
            "call": {
                "tool": "search_destination_chargers",
                "args": {"location": {"label": "Alhambra, Granada", "lat": 37.1761, "lon": -3.5881}},
            },
            "result": {
                "ok": True,
                "tool": "search_destination_chargers",
                "location": {"label": "Alhambra, Granada", "lat": 37.1761, "lon": -3.5881},
                "stops": [{"name": "Parking Ave María Vistillas", "distanceKm": 0.51, "powerKw": 22}],
            },
        }
    ]
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Uso Alhambra, Granada como aproximación para tu alojamiento. Para el finde, "
                        "disponibilidad, acceso y tarifas pueden cambiar antes del viaje. Si me das "
                        "hotel exacto, dirección o zona exacta puedo refinar la búsqueda."
                    )
                },
            },
            {
                "id": "stops",
                "type": "StationList",
                "version": 1,
                "props": {"stations": [{"name": "Parking Ave María Vistillas", "distanceKm": 0.51, "powerKw": 22}]},
            },
            {
                "id": "risk",
                "type": "AssistantMessage",
                "version": 1,
                "props": {"text": "Datos procedentes solo de puntos de carga autorizados importados."},
            },
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        tool_history,
        message=(
            "Pista de ubicación conocida detectada en el mensaje actual: Alhambra, Granada (37.1761,-3.5881).\n"
            "Mensaje actual del usuario: Voy el finde a Granada y duermo cerca de la Alhambra"
        ),
    )

    assert issues == []


def test_a2ui_contract_allows_future_round_trip_clarifying_origin_without_volatility_warning():
    blocks = validate_blocks(
        [
            {
                "id": "assistant",
                "type": "AssistantMessage",
                "version": 1,
                "props": {
                    "text": (
                        "Veo que es un viaje de ida y vuelta a Córdoba. "
                        "¿Desde qué ciudad sales el viernes?"
                    )
                },
            }
        ]
    )

    issues = a2ui_contract_issues(
        blocks,
        [],
        message="Voy a Córdoba el viernes y vuelvo el domingo, dónde cargo?",
    )

    assert issues == []

@pytest.mark.django_db
def test_deepseek_conversation_agent_stops_repeated_tool_call(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Valencia"}}

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert any(
        "No he podido completar esta respuesta con fiabilidad" in block["props"]["text"]
        for block in blocks_from_a2ui_response(response)
        if block["type"] == "AssistantMessage"
    )


@pytest.mark.django_db
def test_deepseek_conversation_agent_recovers_repeated_tool_call_with_final_retry(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
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

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
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
                        "type": "StationList",
                        "version": 1,
                        "props": {"stations": tool_history[-1]["result"]["stops"]},
                    },
                ],
            }
        return {"type": "tool_call", "tool": "search_destination_chargers", "args": repeated_args}

    def fake_record_trace_event(**kwargs):
        trace_events.append(kwargs)

    monkeypatch.setattr("routing.agent.execute_conversation_tool", fake_execute_conversation_tool)
    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)
    monkeypatch.setattr("routing.agent.record_trace_event", fake_record_trace_event)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Córdoba cerca de la Mezquita: algo que tenga más potencia?"},
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
def test_deepseek_conversation_agent_stops_at_tool_budget(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    settings.KALMIO_DEEPSEEK_MAX_TOOL_CALLS = 1

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        tool_history = tool_history or []
        if not tool_history:
            return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Valencia"}}
        return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Madrid"}}

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert any(
        "No he podido completar esta respuesta con fiabilidad" in block["props"]["text"]
        for block in blocks_from_a2ui_response(response)
        if block["type"] == "AssistantMessage"
    )


@pytest.mark.django_db
def test_local_conversation_agent_failure_uses_dev_fallback_without_technical_detail(client, monkeypatch):
    def failing_agent(message, history_blocks=None):
        raise AgentResponseError("El agente no devolvió JSON válido.")

    monkeypatch.setattr("routing.api.run_conversation_agent", failing_agent)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya"},
        content_type="application/json",
    )

    assert response.status_code == 200
    blocks = blocks_from_a2ui_response(response)
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks)
    assert "DeepSeek" not in rendered_text
    assert "JSON" not in rendered_text
    block_types = [block["type"] for block in blocks]
    assert "UserMessage" in block_types
    assert "PositionRequestCard" in block_types
    assert "RiskExplanationCard" not in block_types


@pytest.mark.django_db
def test_deepseek_conversation_agent_failure_uses_minimal_safe_fallback(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"

    def failing_agent(message, history_blocks=None):
        raise AgentResponseError("El agente no devolvió JSON válido.")

    monkeypatch.setattr("routing.api.run_conversation_agent", failing_agent)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya"},
        content_type="application/json",
    )

    assert response.status_code == 200
    blocks = blocks_from_a2ui_response(response)
    rendered_text = " ".join(str(block.get("props", {})) for block in blocks)
    assert "DeepSeek" not in rendered_text
    assert "JSON" not in rendered_text
    block_types = [block["type"] for block in blocks]
    assert "UserMessage" in block_types
    assert "AssistantMessage" in block_types
    assert "PositionRequestCard" not in block_types
    assert "StationDetailCard" not in block_types


@pytest.mark.django_db
def test_deepseek_urgent_response_does_not_repair_component_choice_by_intent(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "deepseek"
    repair_requests = []

    def fake_deepseek_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        if repair_issues:
            repair_requests.append(repair_issues)
            return {"type": "final", "blocks": []}
        return {
            "type": "final",
            "blocks": [
                {
                    "id": "wrong-destination",
                    "type": "AssistantMessage",
                    "version": 1,
                    "props": {"text": "Uso Córdoba como ubicación aproximada para esta búsqueda."},
                }
            ],
        }

    monkeypatch.setattr("routing.agent.run_deepseek_decision", fake_deepseek_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya en Córdoba con 18%"},
        content_type="application/json",
    )

    assert response.status_code == 200
    block_types = [block["type"] for block in blocks_from_a2ui_response(response)]
    assert repair_requests == []
    assert "AssistantMessage" in block_types
    assert "StationDetailCard" not in block_types


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
def test_plan_route_tool_treats_partial_vehicle_profile_as_chargers_only(monkeypatch, real_station):
    monkeypatch.setattr("routing.tools.get_route_provider", lambda: StaticRouteProvider())
    partial_vehicle = {
        "model": "Tesla Model Y",
        "battery": 45,
        "usable_battery_kwh": None,
        "consumption_kwh_per_100km": None,
        "connector": None,
        "max_charge_kw": None,
    }

    assert parse_vehicle_arg(partial_vehicle) is None

    result = plan_route_tool(
        {
            "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
            "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
            "vehicle": partial_vehicle,
            "preferences": {"reserve_min_percent": 20},
            "corridor_radius_km": 25,
        }
    )

    assert result["ok"] is True
    assert result["planningLevel"] == "chargers_only"
    assert result["energyKwh"] is None
    assert result["arrivalBattery"] is None
    assert result["recommendation"]["stationName"] == real_station.name
    assert result["routeGeometry"] == {
        "type": "LineString",
        "coordinates": [
            [-3.7038, 40.4168],
            [-2.4, 38.35],
            [-1.1, 38.85],
            [-0.3763, 39.4699],
        ],
    }
    assert result["corridorRadiusKm"] == 25


def test_a2ui_contract_rejects_map_preview_with_untraced_route_geometry():
    tool_history = [
        {
            "call": {"tool": "plan_route", "args": {}},
            "result": {
                "ok": True,
                "tool": "plan_route",
                "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                "distanceKm": 520,
                "durationMin": 355,
                "energyKwh": None,
                "arrivalBattery": None,
                "routeGeometry": {
                    "type": "LineString",
                    "coordinates": [[-3.7038, 40.4168], [-0.3763, 39.4699]],
                },
                "recommendation": {
                    "name": "Almansa HPC",
                    "stationName": "Almansa HPC",
                    "powerKw": 180,
                    "distanceKm": 1.2,
                    "detourMin": 8,
                    "lat": 38.869,
                    "lon": -1.0971,
                },
                "alternatives": [],
            },
        }
    ]
    blocks = [
        {
            "id": "map",
            "type": "MapPreviewCard",
            "version": 1,
            "props": {
                "origin": {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
                "destination": {"label": "Valencia", "lat": 39.4699, "lon": -0.3763},
                "primaryStation": {
                    "name": "Almansa HPC",
                    "stationName": "Almansa HPC",
                    "powerKw": 180,
                    "distanceKm": 1.2,
                    "detourMin": 8,
                    "lat": 38.869,
                    "lon": -1.0971,
                },
                "routeGeometry": {
                    "type": "LineString",
                    "coordinates": [[-3.7038, 40.4168], [-2.2, 41.1], [-0.3763, 39.4699]],
                },
                "geometryPrecision": "provider",
            },
        }
    ]

    issues = a2ui_contract_issues(blocks, tool_history)

    assert any("MapPreviewCard.routeGeometry no coincide con plan_route" in issue for issue in issues)


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
