from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from django.conf import settings


KNOWN_LOCATIONS = {
    "madrid": ("Madrid", 40.4168, -3.7038),
    "valencia": ("Valencia", 39.4699, -0.3763),
    "cordoba": ("Córdoba", 37.8882, -4.7794),
    "sevilla": ("Sevilla", 37.3891, -5.9845),
    "barcelona": ("Barcelona", 41.3874, 2.1686),
    "malaga": ("Málaga", 36.7213, -4.4214),
    "granada": ("Granada", 37.1773, -3.5986),
    "alicante": ("Alicante", 38.3452, -0.4810),
    "bilbao": ("Bilbao", 43.2630, -2.9350),
    "zaragoza": ("Zaragoza", 41.6488, -0.8891),
    "cadiz": ("Cádiz", 36.5271, -6.2886),
    "alhambra": ("Alhambra, Granada", 37.1761, -3.5881),
    "almansa": ("Almansa", 38.8690, -1.0971),
    "alcobendas": ("Alcobendas", 40.5317, -3.6419),
    "alcora": ("Alcora", 39.1230, -0.5025),
}


class GeocodingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocationCandidate:
    label: str
    lat: float
    lon: float
    precision: str
    source: str
    is_approximate: bool
    confidence: float | None = None
    query: str = ""
    source_id: str = ""

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": self.label,
            "lat": self.lat,
            "lon": self.lon,
            "precision": self.precision,
            "source": self.source,
            "isApproximate": self.is_approximate,
            "query": self.query,
        }
        if self.confidence is not None:
            payload["confidence"] = round(self.confidence, 3)
        if self.source_id:
            payload["sourceId"] = self.source_id
        return payload


class LocalLocationResolver:
    source = "local_known_locations"

    def resolve(self, raw_query: str, search_mode: str = "auto") -> list[LocationCandidate]:
        query = normalize_location_query(raw_query)
        candidates: list[LocationCandidate] = []
        for key, (label, lat, lon) in KNOWN_LOCATIONS.items():
            if key in query:
                precision = local_location_resolution_precision(query, key)
                candidates.append(
                    LocationCandidate(
                        label=label,
                        lat=lat,
                        lon=lon,
                        precision=precision,
                        source=self.source,
                        is_approximate=precision != "known_location",
                        confidence=1.0 if precision == "known_location" else 0.62,
                        query=raw_query,
                        source_id=key,
                    )
                )
        return candidates[:5]


class MapboxLocationResolver:
    source = "mapbox"

    def __init__(
        self,
        access_token: str | None = None,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        request_retries: int | None = None,
        country: str | None = None,
        language: str | None = None,
        limit: int | None = None,
    ) -> None:
        self.access_token = (access_token or settings.KALMIO_MAPBOX_ACCESS_TOKEN).strip()
        self.base_url = (base_url or settings.KALMIO_MAPBOX_GEOCODING_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.KALMIO_GEOCODING_TIMEOUT_SECONDS
        self.request_retries = (
            request_retries if request_retries is not None else settings.KALMIO_GEOCODING_REQUEST_RETRIES
        )
        self.country = (country if country is not None else settings.KALMIO_GEOCODING_COUNTRY).strip()
        self.language = (language if language is not None else settings.KALMIO_GEOCODING_LANGUAGE).strip()
        self.limit = limit if limit is not None else settings.KALMIO_GEOCODING_LIMIT
        self.search_api = settings.KALMIO_MAPBOX_SEARCH_API

    def resolve(self, raw_query: str, search_mode: str = "auto") -> list[LocationCandidate]:
        if not self.access_token:
            raise GeocodingProviderError("Mapbox no está configurado: falta KALMIO_MAPBOX_ACCESS_TOKEN.")
        query = raw_query.strip()
        if not query:
            return []

        params: dict[str, Any] = {
            "q": query,
            "access_token": self.access_token,
            "limit": self.limit,
        }
        if self.country:
            params["country"] = self.country
        if self.language:
            params["language"] = self.language
        search_api = mapbox_search_api_for_query(query, self.search_api, search_mode)
        if search_api == "searchbox":
            path = "/search/searchbox/v1/forward"
        else:
            path = "/search/geocode/v6/forward"
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"

        payload = self._get_json(url)
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise GeocodingProviderError("Mapbox devolvió una respuesta de geocoding inválida.")

        candidates = [
            candidate
            for feature in features
            if (candidate := mapbox_feature_candidate(feature, query))
            and candidate_matches_query(candidate.label, query, candidate.precision)
        ]
        candidates.sort(key=lambda candidate: candidate_rank(candidate, query))
        return candidates[: self.limit]

    def _get_json(self, url: str) -> dict[str, Any]:
        attempts = max(self.request_retries, 0) + 1
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "kalmio/resolve-location"})
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                raise GeocodingProviderError(f"Mapbox rechazó la consulta de ubicación: HTTP {exc.code}.") from exc
            except urllib.error.URLError as exc:
                if attempt >= attempts:
                    raise GeocodingProviderError(f"No se pudo consultar Mapbox geocoding: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise GeocodingProviderError("Mapbox devolvió una respuesta de geocoding inválida.") from exc
            time.sleep(0.1 * attempt)
        raise GeocodingProviderError("No se pudo consultar Mapbox geocoding.")


def get_location_resolver():
    provider = settings.KALMIO_GEOCODING_PROVIDER
    if provider == "local":
        return LocalLocationResolver()
    if provider == "mapbox":
        if settings.KALMIO_MAPBOX_ACCESS_TOKEN:
            return MapboxLocationResolver()
        if getattr(settings, "IS_PRODUCTION", False):
            raise GeocodingProviderError("Mapbox no está configurado: falta KALMIO_MAPBOX_ACCESS_TOKEN.")
        return LocalLocationResolver()
    raise GeocodingProviderError(f"Proveedor de geocoding no soportado: {provider}")


def normalize_location_query(value: str) -> str:
    substitutions = str.maketrans("áéíóúüñ", "aeiouun")
    return value.lower().translate(substitutions)


def local_location_resolution_precision(query: str, matched_key: str) -> str:
    if query.strip(" .,") == matched_key:
        return "known_location"
    if any(term in query for term in ("hotel", "calle", "paseo", "avenida", "plaza", "melia", "alhambra", "atocha")):
        return "city_approximation"
    return "known_location"


def mapbox_feature_candidate(feature: Any, query: str) -> LocationCandidate | None:
    if not isinstance(feature, dict):
        return None
    properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    lon, lat = mapbox_feature_coordinates(feature, properties)
    if lat is None or lon is None:
        return None
    label = mapbox_label(properties, feature)
    if not label:
        return None
    feature_type = display_text(
        properties.get("feature_type") or first_list_item(feature.get("place_type")),
        "place",
    )
    precision = mapbox_precision(feature_type)
    confidence = mapbox_confidence(feature, properties, precision)
    return LocationCandidate(
        label=label[:160],
        lat=lat,
        lon=lon,
        precision=precision,
        source="mapbox",
        is_approximate=mapbox_is_approximate(precision, confidence),
        confidence=confidence,
        query=query,
        source_id=display_text(properties.get("mapbox_id") or feature.get("id"), ""),
    )


def mapbox_feature_coordinates(feature: dict[str, Any], properties: dict[str, Any]) -> tuple[float | None, float | None]:
    coordinates = properties.get("coordinates")
    if isinstance(coordinates, dict):
        lon = optional_float(coordinates.get("longitude"))
        lat = optional_float(coordinates.get("latitude"))
        if lat is not None and lon is not None:
            return lon, lat
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    coords = geometry.get("coordinates")
    if isinstance(coords, list) and len(coords) >= 2:
        lon = optional_float(coords[0])
        lat = optional_float(coords[1])
        if lat is not None and lon is not None:
            return lon, lat
    center = feature.get("center")
    if isinstance(center, list) and len(center) >= 2:
        lon = optional_float(center[0])
        lat = optional_float(center[1])
        return lon, lat
    return None, None


def mapbox_label(properties: dict[str, Any], feature: dict[str, Any]) -> str:
    name = display_text(properties.get("name_preferred") or properties.get("name") or feature.get("text"), "")
    full_address = display_text(properties.get("full_address") or feature.get("place_name"), "")
    place = display_text(properties.get("place_formatted"), "")
    if name and full_address and name not in full_address:
        return f"{name}, {full_address}"
    if name and place and name != place:
        return f"{name}, {place}"
    return display_text(full_address or place or name, "")


def mapbox_precision(feature_type: str) -> str:
    normalized = normalize_location_query(feature_type)
    if normalized in {"address", "street", "poi"}:
        return normalized
    if normalized in {"postcode", "district", "locality", "neighborhood"}:
        return "zone"
    if normalized in {"place", "region", "country"}:
        return "city" if normalized == "place" else normalized
    return "approximate"


def mapbox_confidence(feature: dict[str, Any], properties: dict[str, Any], precision: str) -> float | None:
    for key in ("relevance", "score"):
        value = optional_float(feature.get(key) or properties.get(key))
        if value is not None:
            return max(0.0, min(value, 1.0))
    match_code = properties.get("match_code")
    if isinstance(match_code, dict):
        confidence = display_text(match_code.get("confidence"), "").lower()
        if confidence == "exact":
            return 1.0
        if confidence == "high":
            return 0.86
        if confidence == "medium":
            return 0.68
        if confidence == "low":
            return 0.42
    return 0.9 if precision in {"address", "poi"} else 0.72


def mapbox_is_approximate(precision: str, confidence: float | None) -> bool:
    if precision in {"address", "poi"} and (confidence is None or confidence >= 0.75):
        return False
    if precision in {"city", "zone", "region", "country"}:
        return True
    return confidence is not None and confidence < 0.75


DISTINCTIVE_STOPWORDS = {
    "area",
    "servicio",
    "hotel",
    "calle",
    "avenida",
    "avda",
    "paseo",
    "plaza",
    "poligono",
    "industrial",
    "estacion",
    "cerca",
    "desde",
    "hacia",
    "hasta",
    "para",
    "del",
    "de",
    "la",
    "las",
    "los",
    "el",
    "en",
    "un",
    "una",
}


def candidate_matches_query(label: str, query: str, precision: str) -> bool:
    query_tokens = distinctive_tokens(query)
    if not query_tokens:
        return True
    label_tokens = distinctive_tokens(label)
    if query_tokens & label_tokens:
        return True
    if precision in {"city", "region", "country"}:
        return True
    return False


def candidate_rank(candidate: LocationCandidate, query: str) -> tuple[int, int]:
    normalized = normalize_location_query(query)
    precision = candidate.precision
    if any(term in normalized for term in ("calle", "avenida", "avda", "paseo", "plaza")):
        return (0 if precision in {"address", "street"} else 1, precision_rank(precision))
    if any(term in normalized for term in ("hotel", "estacion", "ifema", "alhambra")):
        if precision == "poi":
            return (0, precision_rank(precision))
        if precision in {"city", "zone", "region"}:
            return (1, precision_rank(precision))
        return (2, precision_rank(precision))
    if len(distinctive_tokens(query)) <= 2:
        if precision in {"city", "region", "country"}:
            return (0, precision_rank(precision))
        return (1, precision_rank(precision))
    return (0, precision_rank(precision))


def precision_rank(precision: str) -> int:
    order = {
        "address": 0,
        "poi": 1,
        "street": 2,
        "zone": 3,
        "city": 4,
        "region": 5,
        "country": 6,
    }
    return order.get(precision, 7)


def mapbox_search_api_for_query(query: str, configured_api: str, search_mode: str = "auto") -> str:
    if search_mode == "poi":
        return "searchbox"
    if search_mode in {"address", "place"}:
        return "geocoding"
    if configured_api != "auto":
        return configured_api
    normalized = normalize_location_query(query)
    if any(
        term in normalized
        for term in (
            "hotel",
            "estacion",
            "ifema",
            "alhambra",
            "atocha",
            "aeropuerto",
            "area de servicio",
            "area servicio",
            "cerca de",
        )
    ):
        return "searchbox"
    if "," in query and not any(term in normalized for term in ("calle", "avenida", "avda", "paseo", "plaza")):
        return "searchbox"
    return "geocoding"


def distinctive_tokens(value: str) -> set[str]:
    normalized = normalize_location_query(value)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) >= 3 and token not in DISTINCTIVE_STOPWORDS
    }


def first_list_item(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


def display_text(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
