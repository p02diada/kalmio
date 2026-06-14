from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REVE_PUBLIC_API_BASE_URL = "https://www.mapareve.es/api/public/v1"
REVE_SOURCE_NAME = "REVE public map dev scrape"
REVE_SOURCE_KIND = "reve-dev"
REVE_SOURCE_LICENSE = "Development-only cache from mapareve.es public map; not approved for production use."
REVE_SOURCE_NOTES = (
    "Captured from REVE public map endpoints for local development tests only. "
    "Request official API access before using REVE data outside dev."
)
SPAIN_BBOX = {
    "latitude_ne": 43.8,
    "longitude_ne": 4.5,
    "latitude_sw": 35.7,
    "longitude_sw": -9.5,
    "zoom": 6,
}
REVE_PAGE_SIZE = 10


class ReveDevScrapeError(ValueError):
    pass


@dataclass(frozen=True)
class RevePage:
    locations: list[dict[str, Any]]
    page: int
    next_page: int | None
    total_pages: int | None
    total_count: int | None


def fetch_reve_locations(
    *,
    bbox: dict[str, float] | None = None,
    max_pages: int | None = None,
    delay_seconds: float = 1.0,
    timeout_seconds: float = 30,
    max_retries: int = 8,
    retry_seconds: float = 60,
    cache_dir: str | Path | None = None,
    offline: bool = False,
    user_agent: str = "Kalmio dev REVE data importer (local development; contact: dev@kalmio.local)",
    progress_callback: Callable[[RevePage], None] | None = None,
) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    next_page: int | None = 1
    pages_fetched = 0
    payload = bbox or SPAIN_BBOX
    cache_path = Path(cache_dir) if cache_dir else None

    while next_page is not None:
        if max_pages is not None and pages_fetched >= max_pages:
            break

        page = read_cached_reve_page(cache_path, next_page) if cache_path else None
        page_from_cache = page is not None
        if page is None:
            if offline:
                raise ReveDevScrapeError(f"Missing cached REVE page {next_page}.")
            page = fetch_reve_page(
                page=next_page,
                bbox=payload,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_seconds=retry_seconds,
                user_agent=user_agent,
                cache_dir=cache_path,
            )
        locations.extend(page.locations)
        pages_fetched += 1
        if progress_callback:
            progress_callback(page)
        next_page = page.next_page

        if not page_from_cache and next_page is not None and delay_seconds > 0:
            time.sleep(delay_seconds)

    return locations


def fetch_reve_page(
    *,
    page: int,
    bbox: dict[str, float],
    timeout_seconds: float,
    max_retries: int,
    retry_seconds: float,
    user_agent: str,
    cache_dir: Path | None = None,
) -> RevePage:
    body = json.dumps(bbox).encode("utf-8")
    request = Request(
        f"{REVE_PUBLIC_API_BASE_URL}/locations?page={page}&per_page={REVE_PAGE_SIZE}",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Accept-Language": "es",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
    )

    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < max_retries:
                time.sleep(retry_delay(exc, retry_seconds, attempt))
                continue
            raise ReveDevScrapeError(f"REVE returned HTTP {exc.code}: {message}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt < max_retries:
                time.sleep(retry_seconds)
                continue
            raise ReveDevScrapeError(f"Could not fetch REVE page {page}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ReveDevScrapeError(f"Could not decode REVE page {page}: {exc}") from exc
    else:
        raise ReveDevScrapeError(f"Could not fetch REVE page {page}.")

    if isinstance(payload, dict) and payload.get("status_code"):
        raise ReveDevScrapeError(str(payload.get("status_message") or payload))

    page_payload = parse_reve_page_payload(payload, page)
    write_cached_reve_page(cache_dir, page_payload.page, payload)
    return page_payload


def parse_reve_page_payload(payload: Any, requested_page: int) -> RevePage:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ReveDevScrapeError("Unexpected REVE locations response.")

    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    return RevePage(
        locations=payload["data"],
        page=int(pagination.get("page") or requested_page),
        next_page=pagination.get("next"),
        total_pages=pagination.get("total_pages"),
        total_count=pagination.get("total_count"),
    )


def read_cached_reve_page(cache_dir: Path | None, page: int) -> RevePage | None:
    if cache_dir is None:
        return None
    cache_file = reve_page_cache_file(cache_dir, page)
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReveDevScrapeError(f"Cached REVE page {page} is not valid JSON: {cache_file}") from exc
    return parse_reve_page_payload(payload, page)


def write_cached_reve_page(cache_dir: Path | None, page: int, payload: dict[str, Any]) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    reve_page_cache_file(cache_dir, page).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def reve_page_cache_file(cache_dir: Path, page: int) -> Path:
    return cache_dir / f"locations-page-{page:05d}.json"


def retry_delay(exc: HTTPError, retry_seconds: float, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), retry_seconds)
        except ValueError:
            pass
    return min(retry_seconds * (attempt + 1), 300)


def reve_locations_to_charger_records(locations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for location in locations:
        coordinates = location.get("coordinates") or {}
        latitude = value_as_decimal_string(coordinates.get("latitude"))
        longitude = value_as_decimal_string(coordinates.get("longitude"))
        location_id = str(location.get("id") or "").strip()
        if not location_id or latitude is None or longitude is None:
            continue

        owner = location.get("owner") if isinstance(location.get("owner"), dict) else {}
        station_external_id = f"reve:{location_id}"
        amenities = "|".join(str(item).strip() for item in location.get("facilities") or [] if str(item).strip())
        address = station_address(location)
        operator_name = str(owner.get("name") or location.get("operator") or "REVE unknown operator").strip()

        for evse_index, evse in enumerate(location.get("evses") or [], start=1):
            evse_uid = str(evse.get("evse_id") or f"{station_external_id}:evse:{evse_index}").strip()
            status = normalize_reve_status(evse.get("status") or location.get("status"))
            observed_at = evse.get("status_updated_at") or evse.get("last_updated")

            for connector_index, connector in enumerate(evse.get("connectors") or [], start=1):
                connector_type = normalize_reve_connector(connector.get("standard"))
                max_power_kw = watts_to_kw(connector.get("max_electric_power"))
                if not connector_type or max_power_kw <= 0:
                    continue

                record = {
                    "source_name": REVE_SOURCE_NAME,
                    "source_kind": REVE_SOURCE_KIND,
                    "source_license": REVE_SOURCE_LICENSE,
                    "source_notes": REVE_SOURCE_NOTES,
                    "operator_name": operator_name,
                    "operator_website": normalize_website(owner.get("website")),
                    "operator_support_phone": str(owner.get("phone") or "").strip(),
                    "station_external_id": station_external_id,
                    "station_name": str(location.get("name") or station_external_id).strip(),
                    "address": address,
                    "latitude": latitude,
                    "longitude": longitude,
                    "amenities": amenities,
                    "evse_uid": f"reve:{evse_uid}:{connector_index}" if connector_index > 1 else f"reve:{evse_uid}",
                    "status": status,
                    "connector_type": connector_type,
                    "max_power_kw": max_power_kw,
                    "tariff_is_estimated": False,
                }
                if observed_at:
                    record["observed_at"] = observed_at

                price = extract_energy_price(connector.get("tariffs") or [])
                if price is not None:
                    record["price_per_kwh"] = price
                    record["currency"] = "EUR"

                records.append(record)

    return records


def station_address(location: dict[str, Any]) -> str:
    parts = [
        location.get("address"),
        location.get("postal_code"),
        location.get("state"),
        location.get("country"),
    ]
    return ", ".join(str(part).strip() for part in parts if str(part or "").strip())


def normalize_reve_status(value: Any) -> str:
    status = str(value or "").strip().upper()
    return {
        "AVAILABLE": "available",
        "CHARGING": "charging",
        "RESERVED": "reserved",
        "OUTOFORDER": "outoforder",
        "OUT_OF_ORDER": "outoforder",
        "INOPERATIVE": "outoforder",
        "UNKNOWN": "unknown",
    }.get(status, "unknown")


def normalize_reve_connector(value: Any) -> str:
    connector = str(value or "").strip().upper()
    return {
        "IEC_62196_T2_COMBO": "CCS2",
        "IEC_62196_T1_COMBO": "CCS1",
        "IEC_62196_T2": "TYPE2",
        "IEC_62196_T1": "TYPE1",
        "CHADEMO": "CHAdeMO",
        "TESLA_R": "TESLA",
        "TESLA_S": "TESLA",
    }.get(connector, connector)


def watts_to_kw(value: Any) -> int:
    try:
        power = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return 0

    if power <= 0:
        return 0
    if power > 1000:
        power = power / Decimal("1000")
    return max(1, int(power.to_integral_value()))


def extract_energy_price(tariffs: list[dict[str, Any]]) -> str | None:
    for tariff_entry in tariffs:
        tariff = tariff_entry.get("tariff") if isinstance(tariff_entry, dict) else None
        if not isinstance(tariff, dict):
            continue
        for element in tariff.get("elements") or []:
            for component in element.get("price_components") or []:
                if str(component.get("type") or "").upper() == "ENERGY":
                    price = value_as_decimal_string(component.get("price"))
                    if price is not None:
                        return price
        if any("gratuito" in str(item).lower() for item in tariff_entry.get("human") or []):
            return "0"
    return None


def value_as_decimal_string(value: Any) -> str | None:
    try:
        return str(Decimal(str(value)).normalize())
    except (InvalidOperation, TypeError):
        return None


def normalize_website(value: Any) -> str:
    website = str(value or "").strip()
    if not website:
        return ""
    if website.startswith(("http://", "https://")):
        return website
    return f"https://{website}"
