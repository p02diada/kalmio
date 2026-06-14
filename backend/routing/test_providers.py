import json
import urllib.error

import pytest

from routing.providers import Coordinate, OsrmRouteProvider, RoutingProviderError


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def patch_urlopen(monkeypatch, payload):
    def urlopen(url, timeout):
        return StubResponse(payload)

    monkeypatch.setattr("routing.providers.urllib.request.urlopen", urlopen)


def test_osrm_provider_retries_transient_failures(monkeypatch):
    attempts = {"count": 0}
    success_payload = {
        "routes": [
            {
                "distance": 1500,
                "duration": 180,
                "geometry": {"coordinates": [[-4.7794, 37.8882], [-2.4, 38.35], [-0.3763, 39.4699]]},
            }
        ]
    }

    def urlopen(url, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.URLError("temporary failure")
        return StubResponse(success_payload)

    monkeypatch.setattr("routing.providers.urllib.request.urlopen", urlopen)
    provider = OsrmRouteProvider(base_url="https://routing.example", timeout_seconds=1, request_retries=1)

    route = provider.route(Coordinate(lat=37.8882, lon=-4.7794), Coordinate(lat=39.4699, lon=-0.3763))

    assert route.distance_km == 1.5
    assert attempts["count"] == 2


def test_osrm_provider_requires_route_geometry(monkeypatch):
    patch_urlopen(
        monkeypatch,
        {
            "routes": [
                {
                    "distance": 1000,
                    "duration": 120,
                    "geometry": {"coordinates": [[-4.7794, 37.8882]]},
                }
            ]
        },
    )
    provider = OsrmRouteProvider(base_url="https://routing.example", timeout_seconds=1)

    with pytest.raises(RoutingProviderError, match="geometría insuficiente"):
        provider.route(Coordinate(lat=37.8882, lon=-4.7794), Coordinate(lat=39.4699, lon=-0.3763))


def test_osrm_provider_rejects_incomplete_route(monkeypatch):
    patch_urlopen(monkeypatch, {"routes": [{"distance": 1000, "geometry": {"coordinates": [[-4.7794, 37.8882], [-0.3763, 39.4699]]}}]})
    provider = OsrmRouteProvider(base_url="https://routing.example", timeout_seconds=1)

    with pytest.raises(RoutingProviderError, match="ruta incompleta"):
        provider.route(Coordinate(lat=37.8882, lon=-4.7794), Coordinate(lat=39.4699, lon=-0.3763))


def test_osrm_provider_uses_provider_geometry(monkeypatch):
    patch_urlopen(
        monkeypatch,
        {
            "routes": [
                {
                    "distance": 1500,
                    "duration": 180,
                    "geometry": {"coordinates": [[-4.7794, 37.8882], [-2.4, 38.35], [-0.3763, 39.4699]]},
                }
            ]
        },
    )
    provider = OsrmRouteProvider(base_url="https://routing.example", timeout_seconds=1)

    route = provider.route(Coordinate(lat=37.8882, lon=-4.7794), Coordinate(lat=39.4699, lon=-0.3763))

    assert route.distance_km == 1.5
    assert route.duration_min == 3
    assert route.geometry == [
        Coordinate(lat=37.8882, lon=-4.7794),
        Coordinate(lat=38.35, lon=-2.4),
        Coordinate(lat=39.4699, lon=-0.3763),
    ]
