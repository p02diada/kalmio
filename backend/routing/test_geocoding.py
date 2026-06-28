import json

import pytest
from django.test import override_settings

from routing.geocoding import MapboxLocationResolver
from routing.tools import resolve_location_tool


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def mapbox_payload():
    return {
        "features": [
            {
                "id": "dXJuOm1ieHBvaTox",
                "properties": {
                    "mapbox_id": "dXJuOm1ieHBvaTox",
                    "feature_type": "poi",
                    "name": "Hotel Meliá Córdoba",
                    "full_address": "Hotel Meliá Córdoba, Córdoba, España",
                    "coordinates": {"longitude": -4.7852, "latitude": 37.8901},
                    "match_code": {"confidence": "high"},
                },
                "geometry": {"type": "Point", "coordinates": [-4.7852, 37.8901]},
            }
        ]
    }


def test_mapbox_resolver_normalizes_poi_candidate(monkeypatch):
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        assert timeout == 4
        return FakeResponse(mapbox_payload())

    monkeypatch.setattr("routing.geocoding.urllib.request.urlopen", fake_urlopen)

    resolver = MapboxLocationResolver(
        access_token="test-token",
        country="ES",
        language="es",
        request_retries=0,
        timeout_seconds=4,
    )
    candidates = resolver.resolve("Hotel Meliá Córdoba")

    assert len(candidates) == 1
    assert candidates[0].label == "Hotel Meliá Córdoba, Córdoba, España"
    assert candidates[0].lat == 37.8901
    assert candidates[0].lon == -4.7852
    assert candidates[0].precision == "poi"
    assert candidates[0].source == "mapbox"
    assert candidates[0].is_approximate is False
    assert "/search/searchbox/v1/forward" in requested_urls[0]
    assert "country=ES" in requested_urls[0]
    assert "language=es" in requested_urls[0]


@override_settings(KALMIO_GEOCODING_PROVIDER="mapbox", KALMIO_MAPBOX_ACCESS_TOKEN="test-token")
def test_resolve_location_tool_returns_mapbox_candidates(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(mapbox_payload())

    monkeypatch.setattr("routing.geocoding.urllib.request.urlopen", fake_urlopen)

    result = resolve_location_tool({"query": "Hotel Meliá Córdoba", "searchMode": "poi"})

    assert result["ok"] is True
    assert result["tool"] == "resolve_location"
    assert result["searchMode"] == "poi"
    assert result["source"] == "mapbox"
    assert result["precision"] == "poi"
    assert result["isApproximate"] is False
    assert result["location"]["label"] == "Hotel Meliá Córdoba, Córdoba, España"
    assert result["location"] == result["candidates"][0]


@override_settings(KALMIO_GEOCODING_PROVIDER="mapbox", KALMIO_MAPBOX_ACCESS_TOKEN="test-token")
def test_resolve_location_tool_discards_unrelated_mapbox_poi(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "features": [
                    {
                        "properties": {
                            "mapbox_id": "wrong-poi",
                            "feature_type": "poi",
                            "name": "Área de Servicio Arroyo de la Miel",
                            "full_address": "29620 Torremolinos, España",
                            "coordinates": {"longitude": -4.5283, "latitude": 36.6131},
                        },
                        "geometry": {"type": "Point", "coordinates": [-4.5283, 36.6131]},
                    }
                ]
            }
        )

    monkeypatch.setattr("routing.geocoding.urllib.request.urlopen", fake_urlopen)

    result = resolve_location_tool({"query": "Área de servicio La Pausa AP-7"})

    assert result["ok"] is False
    assert result["candidates"] == []


@pytest.mark.parametrize("query,label", [("Málaga", "Málaga"), ("cerca de la Alhambra", "Alhambra, Granada")])
@override_settings(KALMIO_GEOCODING_PROVIDER="mapbox", KALMIO_MAPBOX_ACCESS_TOKEN="")
def test_resolve_location_tool_uses_local_fallback_without_mapbox_token_in_development(query, label):
    result = resolve_location_tool({"query": query})

    assert result["ok"] is True
    assert result["location"]["label"] == label
    assert result["location"]["source"] == "local_known_locations"
