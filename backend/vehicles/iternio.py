from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.db import transaction
from django.utils import timezone

from vehicles.models import VehicleProfile, VehicleProfileSource


ITERNIO_DEFAULT_BASE_URL = "https://api.iternio.com/2"
ITERNIO_VEHICLE_LIST_PATH = "/vehicle/_list"
ITERNIO_SOURCE_NAME = "Iternio Planning API vehicle catalog"
ITERNIO_SOURCE_LICENSE = "Requires Kalmio-issued Iternio/ABRP API access. Do not use ABRP web-client credentials."


class IternioVehicleImportError(ValueError):
    pass


@dataclass(frozen=True)
class VehicleImportResult:
    vehicles: int
    options: int
    display_groups: int


def fetch_iternio_vehicle_catalog(
    *,
    api_key: str,
    base_url: str = ITERNIO_DEFAULT_BASE_URL,
    country_code3: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    if not api_key.strip():
        raise IternioVehicleImportError("ITERNIO_API_KEY is required.")

    query = urlencode({"countryCode3": country_code3}) if country_code3 else ""
    url = f"{base_url.rstrip('/')}{ITERNIO_VEHICLE_LIST_PATH}"
    if query:
        url = f"{url}?{query}"

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "X-API-KEY": api_key,
            "User-Agent": "Kalmio vehicle-profile importer; contact: dev@kalmio.local",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise IternioVehicleImportError(f"Iternio returned HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise IternioVehicleImportError(f"Could not fetch Iternio vehicle catalog: {exc}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise IternioVehicleImportError("Iternio vehicle catalog response was not valid JSON.") from exc

    validate_catalog_payload(payload)
    return payload


def import_iternio_vehicle_catalog(
    payload: dict[str, Any],
    *,
    base_url: str = ITERNIO_DEFAULT_BASE_URL,
    replace: bool = False,
) -> VehicleImportResult:
    validate_catalog_payload(payload)
    vehicles = payload["vehicles"]

    with transaction.atomic():
        source = upsert_source(base_url)
        if replace:
            VehicleProfile.objects.filter(source=source).delete()

        for vehicle in vehicles:
            upsert_vehicle_profile(vehicle, source)

        source.imported_at = timezone.now()
        source.save(update_fields=["imported_at", "updated_at"])

    return VehicleImportResult(
        vehicles=len(vehicles),
        options=len(payload.get("options") or []),
        display_groups=len(payload.get("display") or []),
    )


def validate_catalog_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise IternioVehicleImportError("Iternio vehicle catalog response must be a JSON object.")
    vehicles = payload.get("vehicles")
    if not isinstance(vehicles, list):
        raise IternioVehicleImportError("Iternio vehicle catalog response must contain a vehicles list.")

    for index, vehicle in enumerate(vehicles, start=1):
        if not isinstance(vehicle, dict):
            raise IternioVehicleImportError(f"Vehicle {index}: expected object.")
        for field in ("typecode", "manufacturer", "model", "title"):
            if is_blank(vehicle.get(field)):
                raise IternioVehicleImportError(f"Vehicle {index}: missing required field {field}.")


def upsert_source(base_url: str) -> VehicleProfileSource:
    return VehicleProfileSource.objects.update_or_create(
        name=ITERNIO_SOURCE_NAME,
        defaults={
            "kind": "iternio",
            "license": ITERNIO_SOURCE_LICENSE,
            "is_authorized": True,
            "base_url": base_url.rstrip("/"),
            "notes": "Imported through a configured Iternio API key issued for Kalmio.",
        },
    )[0]


def upsert_vehicle_profile(vehicle: dict[str, Any], source: VehicleProfileSource) -> VehicleProfile:
    return VehicleProfile.objects.update_or_create(
        typecode=str(vehicle["typecode"]).strip(),
        defaults={
            "source": source,
            "manufacturer": str(vehicle["manufacturer"]).strip(),
            "model": str(vehicle["model"]).strip(),
            "title": str(vehicle["title"]).strip(),
            "maturity": value_or_default(vehicle.get("maturity"), ""),
            "drive_train": value_or_default(vehicle.get("driveTrain"), ""),
            "start_year": positive_int_or_none(vehicle.get("startYear")),
            "end_year": positive_int_or_none(vehicle.get("endYear")),
            "battery_capacity_wh": positive_int_or_none(vehicle.get("batteryCapacityWh")),
            "battery_chemistry": value_or_default(vehicle.get("batteryChemistry"), ""),
            "battery_name": value_or_default(vehicle.get("batteryName"), ""),
            "reference_consumption_wh_km": decimal_or_none(vehicle.get("referenceConsumption")),
            "recommended_max_speed_kmh": decimal_or_none(vehicle.get("recommendedMaxSpeed")),
            "default_connectors": string_list(vehicle.get("defaultConnectors")),
            "dc_connectors": string_list(vehicle.get("dcConnectors")),
            "dc_connector_powers_w": int_list(vehicle.get("dcConnectorPowers")),
            "ac_connectors": string_list(vehicle.get("acConnectors")),
            "has_dcfc_preconditioning": bool_or_none(vehicle.get("hasDcfcPreconditioning")),
            "has_heatpump": bool_or_none(vehicle.get("hasHeatpump")),
            "options": vehicle.get("options") if isinstance(vehicle.get("options"), list) else [],
            "display_hints": vehicle.get("displayHints") if isinstance(vehicle.get("displayHints"), dict) else {},
            "ideal_trip": vehicle.get("idealTrip") if isinstance(vehicle.get("idealTrip"), dict) else {},
            "raw_payload": vehicle,
        },
    )[0]


def is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def value_or_default(value: Any, default: str) -> str:
    if is_blank(value):
        return default
    return str(value).strip()


def positive_int_or_none(value: Any) -> int | None:
    if is_blank(value):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise IternioVehicleImportError(f"Expected positive integer, got {value!r}.") from exc
    if parsed < 0:
        raise IternioVehicleImportError(f"Expected positive integer, got {value!r}.")
    return parsed


def decimal_or_none(value: Any) -> Decimal | None:
    if is_blank(value):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise IternioVehicleImportError(f"Expected decimal, got {value!r}.") from exc
    if parsed < 0:
        raise IternioVehicleImportError(f"Expected positive decimal, got {value!r}.")
    return parsed


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [positive_int_or_none(item) for item in value if positive_int_or_none(item) is not None]


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in {"true", "1", "yes"}:
        return True
    if str(value).strip().lower() in {"false", "0", "no"}:
        return False
    raise IternioVehicleImportError(f"Expected boolean, got {value!r}.")
