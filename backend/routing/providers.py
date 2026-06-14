from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lon: float


@dataclass(frozen=True)
class ProviderRoute:
    distance_km: float
    duration_min: int
    geometry: list[Coordinate]


class RoutingProviderError(RuntimeError):
    pass


class OsrmRouteProvider:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        request_retries: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.KALMIO_OSRM_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.KALMIO_OSRM_TIMEOUT_SECONDS
        self.request_retries = request_retries if request_retries is not None else settings.KALMIO_ROUTING_REQUEST_RETRIES
        if self.request_retries < 0:
            self.request_retries = 0

    def route(self, origin: Coordinate, destination: Coordinate) -> ProviderRoute:
        validate_coordinate(origin, "origin")
        validate_coordinate(destination, "destination")

        coords = f"{origin.lon},{origin.lat};{destination.lon},{destination.lat}"
        query = urllib.parse.urlencode(
            {
                "overview": "full",
                "geometries": "geojson",
                "alternatives": "false",
                "steps": "false",
            }
        )
        url = f"{self.base_url}/route/v1/driving/{coords}?{query}"
        attempts = self.request_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.URLError as exc:
                if attempt >= attempts:
                    raise RoutingProviderError(f"No se pudo consultar el proveedor de rutas: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise RoutingProviderError("El proveedor de rutas devolvió una respuesta inválida.") from exc

            time.sleep(0.1 * attempt)
        else:
            raise RoutingProviderError("No se pudo consultar el proveedor de rutas.")

        if not isinstance(payload, dict):
            raise RoutingProviderError("El proveedor de rutas devolvió una respuesta inválida.")

        routes = payload.get("routes") or []
        if not routes:
            message = payload.get("message") or "sin rutas disponibles"
            raise RoutingProviderError(f"El proveedor de rutas no encontró una ruta: {message}")

        route = routes[0]
        if not isinstance(route, dict):
            raise RoutingProviderError("El proveedor de rutas devolvió una ruta inválida.")
        try:
            distance_km = round(float(route["distance"]) / 1000, 1)
            duration_min = round(float(route["duration"]) / 60)
            geometry = route["geometry"]["coordinates"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RoutingProviderError("El proveedor de rutas devolvió una ruta incompleta.") from exc

        try:
            points = [Coordinate(lat=float(lat), lon=float(lon)) for lon, lat in geometry]
        except (TypeError, ValueError) as exc:
            raise RoutingProviderError("El proveedor de rutas devolvió una geometría inválida.") from exc
        if len(points) < 2:
            raise RoutingProviderError("El proveedor de rutas devolvió una geometría insuficiente.")

        return ProviderRoute(
            distance_km=distance_km,
            duration_min=duration_min,
            geometry=points,
        )


def get_route_provider() -> OsrmRouteProvider:
    provider_name = settings.KALMIO_ROUTING_PROVIDER.lower()
    if provider_name != "osrm":
        raise RoutingProviderError(f"Proveedor de rutas no soportado: {provider_name}")
    return OsrmRouteProvider()


def validate_coordinate(coordinate: Coordinate, field_name: str) -> None:
    if not -90 <= coordinate.lat <= 90:
        raise RoutingProviderError(f"{field_name}.lat está fuera de rango.")
    if not -180 <= coordinate.lon <= 180:
        raise RoutingProviderError(f"{field_name}.lon está fuera de rango.")
