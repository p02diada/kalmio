from datetime import timedelta
from decimal import Decimal

import pytest
from accounts.models import AuthThrottle
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from charging.models import AvailabilitySnapshot, Connector, DataSource, EVSE, Operator, ReliabilityScore, Station, Tariff
from routing.api import ACTIVE_CONVERSATION_BLOCKS_KEY
from routing.agent import AgentResponseError
from routing.models import RoutePlan
from routing.production_planner import station_to_score_payload
from routing.providers import Coordinate, ProviderRoute, RoutingProviderError


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
    assert body["blocks"][0]["type"] == "AssistantMessage"
    assert body["blocks"][1]["type"] == "PreferenceChips"


@pytest.mark.django_db
def test_conversation_message_handles_destination_charging_without_route_planner(client, real_station):
    response = client.post(
        "/api/conversation/message",
        data={"text": "Quiero cargadores cerca de un hotel en Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    block_types = [block["type"] for block in body["blocks"]]
    assert "UserMessage" in block_types
    assert "DestinationChargingCard" in block_types
    assert "RouteSummaryCard" not in block_types
    assert RoutePlan.objects.count() == 0


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
    assert first_response.json()["blocks"][-1]["type"] == "LocationRequestCard"

    second_response = client.post(
        "/api/conversation/message",
        data={"text": "En cordoba"},
        content_type="application/json",
    )

    assert second_response.status_code == 200
    blocks = second_response.json()["blocks"]
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
    assert any(block["type"] == "UrgentChargeCard" for block in location_response.json()["blocks"])

    battery_response = client.post(
        "/api/conversation/message",
        data={"text": "Tengo un 20%"},
        content_type="application/json",
    )

    assert battery_response.status_code == 200
    blocks = battery_response.json()["blocks"]
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
    body = response.json()
    latest_urgent_block = next(block for block in reversed(body["blocks"]) if block["type"] == "UrgentChargeCard")
    assert latest_urgent_block["props"]["battery"] == 20


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
    body = response.json()
    block_types = [block["type"] for block in body["blocks"]]
    assert "UserMessage" in block_types
    assert "AlternativeStopsList" in block_types
    stops_block = next(block for block in body["blocks"] if block["type"] == "AlternativeStopsList")
    assert stops_block["props"]["stops"][0]["name"] == real_station.name


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
    body = response.json()
    risk_block = next(block for block in body["blocks"] if block["type"] == "RiskExplanationCard")
    assert "No puedo hacer esa acción desde el chat" in risk_block["props"]["text"]


@pytest.mark.django_db
def test_codex_destination_card_with_embedded_stops_is_normalized(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"

    def fake_codex_decision(message, tool_history=None):
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
    body = response.json()
    destination_block = next(block for block in body["blocks"] if block["type"] == "DestinationChargingCard")
    stops_block = next(block for block in body["blocks"] if block["type"] == "AlternativeStopsList")
    assert destination_block["props"] == {"destination": "Valencia", "needsConfirmation": True}
    assert stops_block["props"]["stops"][0]["name"] == "Cargador real"


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
    body = response.json()
    assert any(block["type"] == "DestinationChargingCard" for block in body["blocks"])
    stops_block = next(block for block in body["blocks"] if block["type"] == "AlternativeStopsList")
    assert stops_block["props"]["stops"][0]["name"] == valencia_station.name


@pytest.mark.django_db
def test_codex_conversation_agent_repairs_semantic_a2ui_contract(client, settings, monkeypatch, real_station):
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
            tool_result = tool_history[-1]["result"]
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "destination-repaired",
                        "type": "DestinationChargingCard",
                        "version": 1,
                        "props": {"destination": "Almansa", "needsConfirmation": True},
                    },
                    {
                        "id": "stops-repaired",
                        "type": "AlternativeStopsList",
                        "version": 1,
                        "props": {"stops": tool_result["stops"]},
                    },
                    {
                        "id": "risk-repaired",
                        "type": "RiskExplanationCard",
                        "version": 1,
                        "props": {
                            "title": "Aviso importante",
                            "items": [
                                "Confirma disponibilidad antes de depender de estos cargadores.",
                                "Confirma acceso y tarifa antes de depender de estos cargadores.",
                            ],
                        },
                    },
                ],
            }
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
    body = response.json()
    block_types = [block["type"] for block in body["blocks"]]
    assert repair_requests
    assert "DestinationChargingCard" in block_types
    assert "AlternativeStopsList" in block_types
    assert "RiskExplanationCard" in block_types
    risk_block = next(block for block in body["blocks"] if block["type"] == "RiskExplanationCard")
    assert risk_block["props"]["level"] == "medio"
    assert "Confirma disponibilidad" in risk_block["props"]["text"]


@pytest.mark.django_db
def test_codex_conversation_agent_stops_repeated_tool_call(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"

    def fake_codex_decision(message, tool_history=None):
        return {"type": "tool_call", "tool": "resolve_location", "args": {"query": "Valencia"}}

    monkeypatch.setattr("routing.agent.run_codex_decision", fake_codex_decision)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Busca cargadores cerca de Valencia"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    risk_block = next(block for block in body["blocks"] if block["type"] == "RiskExplanationCard")
    assert "No he podido completar esta respuesta con fiabilidad" in risk_block["props"]["text"]


@pytest.mark.django_db
def test_codex_conversation_agent_stops_at_tool_budget(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    settings.KALMIO_CODEX_MAX_TOOL_CALLS = 1

    def fake_codex_decision(message, tool_history=None):
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
    body = response.json()
    risk_block = next(block for block in body["blocks"] if block["type"] == "RiskExplanationCard")
    assert "No he podido completar esta respuesta con fiabilidad" in risk_block["props"]["text"]


@pytest.mark.django_db
def test_conversation_agent_failure_uses_local_semantic_fallback_without_technical_detail(client, monkeypatch):
    def failing_agent(message, history_blocks=None):
        raise AgentResponseError("Codex local no devolvió JSON válido.")

    monkeypatch.setattr("routing.api.run_conversation_agent", failing_agent)

    response = client.post(
        "/api/conversation/message",
        data={"text": "Necesito cargar ya"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    rendered_text = " ".join(str(block.get("props", {})) for block in body["blocks"])
    assert "Codex" not in rendered_text
    assert "JSON" not in rendered_text
    block_types = [block["type"] for block in body["blocks"]]
    assert "UserMessage" in block_types
    assert "LocationRequestCard" in block_types
    assert "RiskExplanationCard" not in block_types


@pytest.mark.django_db
def test_codex_urgent_response_repairs_destination_card_to_urgent_card(client, settings, monkeypatch):
    settings.KALMIO_CONVERSATION_AGENT_MODE = "codex"
    repair_requests = []

    def fake_codex_decision(message, tool_history=None, repair_issues=None, candidate_blocks=None):
        if repair_issues:
            repair_requests.append(repair_issues)
            return {
                "type": "final",
                "blocks": [
                    {
                        "id": "urgent-repaired",
                        "type": "UrgentChargeCard",
                        "version": 1,
                        "props": {"battery": 18, "nearest": "Córdoba Centro HPC", "distanceKm": 1.4},
                    },
                    {
                        "id": "risk-repaired",
                        "type": "RiskExplanationCard",
                        "version": 1,
                        "props": {
                            "level": "medio",
                            "text": "Confirma acceso final, tarifa y disponibilidad antes de depender del cargador.",
                        },
                    },
                ],
            }
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
    body = response.json()
    block_types = [block["type"] for block in body["blocks"]]
    assert repair_requests
    assert "UrgentChargeCard" in block_types
    assert "DestinationChargingCard" not in block_types


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
