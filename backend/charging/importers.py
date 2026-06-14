from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from charging.models import (
    AvailabilitySnapshot,
    Connector,
    DataSource,
    EVSE,
    Operator,
    ReliabilityScore,
    Station,
    Tariff,
)


class ChargerImportError(ValueError):
    pass


@dataclass(frozen=True)
class ImportResult:
    stations: int
    evses: int
    connectors: int


REQUIRED_FIELDS = {
    "source_name",
    "operator_name",
    "station_external_id",
    "station_name",
    "latitude",
    "longitude",
    "evse_uid",
    "connector_type",
    "max_power_kw",
}


def import_chargers(path: str | Path, *, replace_source: bool = False) -> ImportResult:
    records = load_records(path)
    validate_records(records)

    with transaction.atomic():
        if replace_source:
            source_names = sorted({str(record["source_name"]) for record in records})
            Station.objects.filter(data_source__name__in=source_names).delete()

        station_ids: set[int] = set()
        evse_ids: set[int] = set()
        connector_count = 0

        for record in records:
            source = upsert_source(record)
            operator = upsert_operator(record)
            station = upsert_station(record, source, operator)
            evse = upsert_evse(record, station)
            upsert_connector(record, evse)
            upsert_tariff(record, station)
            upsert_reliability(record, station)
            upsert_availability(record, evse, source)

            station_ids.add(station.id)
            evse_ids.add(evse.id)
            connector_count += 1

        return ImportResult(stations=len(station_ids), evses=len(evse_ids), connectors=connector_count)


def validate_charger_file(path: str | Path) -> ImportResult:
    records = load_records(path)
    validate_records(records)
    station_ids = {str(record["station_external_id"]).strip() for record in records}
    evse_ids = {str(record["evse_uid"]).strip() for record in records}
    return ImportResult(stations=len(station_ids), evses=len(evse_ids), connectors=len(records))


def load_records(path: str | Path) -> list[dict[str, Any]]:
    source_path = Path(path)
    if not source_path.exists():
        raise ChargerImportError(f"El fichero no existe: {source_path}")

    if source_path.suffix.lower() == ".json":
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        records = payload["stations"] if isinstance(payload, dict) and "stations" in payload else payload
        if not isinstance(records, list):
            raise ChargerImportError("El JSON debe ser una lista de registros o un objeto con clave 'stations'.")
        return [dict(record) for record in records]

    if source_path.suffix.lower() == ".csv":
        with source_path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    raise ChargerImportError("Formato no soportado. Usa CSV o JSON.")


def validate_records(records: list[dict[str, Any]]) -> None:
    if not records:
        raise ChargerImportError("El fichero no contiene registros.")

    for index, record in enumerate(records, start=1):
        missing = [field for field in sorted(REQUIRED_FIELDS) if is_blank(record.get(field))]
        if missing:
            raise ChargerImportError(f"Registro {index}: faltan campos requeridos: {', '.join(missing)}")

        lat = parse_decimal(record["latitude"], "latitude", index)
        lon = parse_decimal(record["longitude"], "longitude", index)
        if not Decimal("-90") <= lat <= Decimal("90"):
            raise ChargerImportError(f"Registro {index}: latitude fuera de rango.")
        if not Decimal("-180") <= lon <= Decimal("180"):
            raise ChargerImportError(f"Registro {index}: longitude fuera de rango.")

        power = parse_int(record["max_power_kw"], "max_power_kw", index)
        if power <= 0:
            raise ChargerImportError(f"Registro {index}: max_power_kw debe ser positivo.")

        if bool_from_record(record, "is_sample_data", default=False):
            raise ChargerImportError(f"Registro {index}: import_chargers solo acepta datos autorizados/no sample.")
        if str(record.get("source_kind") or "").strip().lower() in {"mock", "sample", "fixture", "test"}:
            raise ChargerImportError(f"Registro {index}: source_kind debe identificar una fuente autorizada.")


def upsert_source(record: dict[str, Any]) -> DataSource:
    return DataSource.objects.update_or_create(
        name=str(record["source_name"]).strip(),
        defaults={
            "kind": value_or_default(record.get("source_kind"), "provider"),
            "license": str(record.get("source_license") or "").strip(),
            "is_authorized": True,
            "notes": str(record.get("source_notes") or "").strip(),
        },
    )[0]


def upsert_operator(record: dict[str, Any]) -> Operator:
    return Operator.objects.update_or_create(
        name=str(record["operator_name"]).strip(),
        defaults={
            "website": str(record.get("operator_website") or "").strip(),
            "support_phone": str(record.get("operator_support_phone") or "").strip(),
        },
    )[0]


def upsert_station(record: dict[str, Any], source: DataSource, operator: Operator) -> Station:
    return Station.objects.update_or_create(
        external_id=str(record["station_external_id"]).strip(),
        defaults={
            "operator": operator,
            "data_source": source,
            "name": str(record["station_name"]).strip(),
            "address": str(record.get("address") or "").strip(),
            "latitude": parse_decimal(record["latitude"], "latitude"),
            "longitude": parse_decimal(record["longitude"], "longitude"),
            "amenities": parse_amenities(record.get("amenities")),
            "is_sample_data": False,
        },
    )[0]


def upsert_evse(record: dict[str, Any], station: Station) -> EVSE:
    return EVSE.objects.update_or_create(
        evse_uid=str(record["evse_uid"]).strip(),
        defaults={
            "station": station,
            "max_power_kw": parse_int(record["max_power_kw"], "max_power_kw"),
            "status": value_or_default(record.get("status"), "unknown"),
        },
    )[0]


def upsert_connector(record: dict[str, Any], evse: EVSE) -> Connector:
    return Connector.objects.update_or_create(
        evse=evse,
        connector_type=str(record["connector_type"]).strip(),
        defaults={"max_power_kw": parse_int(record["max_power_kw"], "max_power_kw")},
    )[0]


def upsert_tariff(record: dict[str, Any], station: Station) -> None:
    if is_blank(record.get("price_per_kwh")):
        return

    Tariff.objects.update_or_create(
        station=station,
        defaults={
            "price_per_kwh": parse_decimal(record["price_per_kwh"], "price_per_kwh"),
            "session_fee": parse_decimal(record.get("session_fee") or "0", "session_fee"),
            "currency": value_or_default(record.get("currency"), "EUR"),
            "is_estimated": bool_from_record(record, "tariff_is_estimated", default=False),
        },
    )


def upsert_reliability(record: dict[str, Any], station: Station) -> None:
    if is_blank(record.get("reliability_score")):
        return

    score = parse_int(record["reliability_score"], "reliability_score")
    if not 0 <= score <= 100:
        raise ChargerImportError("reliability_score debe estar entre 0 y 100.")
    ReliabilityScore.objects.update_or_create(
        station=station,
        defaults={"score": score, "reasons": parse_amenities(record.get("reliability_reasons"))},
    )


def upsert_availability(record: dict[str, Any], evse: EVSE, source: DataSource) -> None:
    observed_at = parse_datetime(record.get("observed_at"))
    if observed_at is None:
        return

    AvailabilitySnapshot.objects.update_or_create(
        evse=evse,
        source=source,
        defaults={"status": evse.status, "observed_at": observed_at},
    )


def parse_decimal(value: Any, field: str, index: int | None = None) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        prefix = f"Registro {index}: " if index else ""
        raise ChargerImportError(f"{prefix}{field} debe ser decimal.") from exc


def parse_int(value: Any, field: str, index: int | None = None) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        prefix = f"Registro {index}: " if index else ""
        raise ChargerImportError(f"{prefix}{field} debe ser entero.") from exc


def parse_datetime(value: Any) -> datetime | None:
    if is_blank(value):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed)
    return parsed


def parse_amenities(value: Any) -> list[str]:
    if is_blank(value):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split("|") if item.strip()]


def bool_from_record(record: dict[str, Any], field: str, *, default: bool) -> bool:
    value = record.get(field)
    if is_blank(value):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "si", "sí"}


def value_or_default(value: Any, default: str) -> str:
    if is_blank(value):
        return default
    return str(value).strip()


def is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""
