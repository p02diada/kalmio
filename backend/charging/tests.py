import json
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from charging.models import Connector, DataSource, EVSE, Operator, Station
from charging.reve_dev import normalize_reve_connector, reve_locations_to_charger_records, reve_page_cache_file
from charging.selectors import get_nearby_stations


@pytest.fixture
def authorized_chargers(db, tmp_path):
    csv_path = tmp_path / "chargers.csv"
    csv_path.write_text(
        "\n".join(
            [
                "source_name,source_kind,source_license,operator_name,station_external_id,station_name,address,latitude,longitude,amenities,evse_uid,status,connector_type,max_power_kw,price_per_kwh,currency,tariff_is_estimated,reliability_score",
                "Authorized OCPI,ocpi,Provider license,Operator Uno,auth-001,Almansa HPC,A-31 Almansa,38.870000,-1.090000,restaurant|bathroom,auth-001-1,available,CCS2,180,0.490,EUR,false,88",
            ]
        ),
        encoding="utf-8",
    )
    call_command("import_chargers", str(csv_path), verbosity=0)


@pytest.mark.django_db
def test_nearby_selector_filters_by_connector_and_power(authorized_chargers):
    nearby = get_nearby_stations(
        lat=38.9,
        lon=-1.1,
        radius_km=120,
        connector="CCS2",
        min_power_kw=150,
        available_only=True,
    )

    assert nearby
    assert nearby[0].station.external_id == "auth-001"
    assert nearby[0].max_power_kw >= 150


@pytest.mark.django_db
def test_nearby_api_returns_authorized_data(client, authorized_chargers):
    response = client.get("/api/stations/nearby?lat=38.9&lon=-1.1&radius_km=120&connector=CCS2")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["external_id"] == "auth-001"
    assert "is_sample_data" not in body[0]
    assert body[0]["distance_km"] is not None


@pytest.mark.django_db
def test_station_detail_api(client, authorized_chargers):
    station = Station.objects.get(external_id="auth-001")
    response = client.get(f"/api/stations/{station.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["external_id"] == "auth-001"
    assert "is_sample_data" not in body
    assert body["warnings"] == []


@pytest.mark.django_db
def test_station_detail_rejects_sample_and_unauthorized_data(client):
    operator = Operator.objects.create(name="Operator Uno")
    authorized_source = DataSource.objects.create(name="Authorized OCPI", kind="ocpi", is_authorized=True)
    unauthorized_source = DataSource.objects.create(name="Unauthorized dump", kind="fixture", is_authorized=False)
    sample_station = Station.objects.create(
        external_id="sample-001",
        operator=operator,
        data_source=authorized_source,
        name="Sample Station",
        latitude=Decimal("38.870000"),
        longitude=Decimal("-1.090000"),
        is_sample_data=True,
    )
    unauthorized_station = Station.objects.create(
        external_id="unauth-001",
        operator=operator,
        data_source=unauthorized_source,
        name="Unauthorized Station",
        latitude=Decimal("38.870000"),
        longitude=Decimal("-1.090000"),
        is_sample_data=False,
    )

    sample_response = client.get(f"/api/stations/{sample_station.id}")
    unauthorized_response = client.get(f"/api/stations/{unauthorized_station.id}")

    assert sample_response.status_code == 404
    assert unauthorized_response.status_code == 404


@pytest.mark.django_db
def test_import_chargers_creates_authorized_non_sample_data(client, authorized_chargers):
    station = Station.objects.get(external_id="auth-001")
    assert station.is_sample_data is False
    assert station.data_source.is_authorized is True
    assert station.data_source.kind == "ocpi"
    assert DataSource.objects.filter(is_authorized=False).count() == 0

    response = client.get("/api/stations/nearby?lat=38.9&lon=-1.1&radius_km=120&connector=CCS2")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["external_id"] == "auth-001"
    assert "is_sample_data" not in body[0]


@pytest.mark.django_db
def test_import_chargers_rejects_sample_records(tmp_path):
    csv_path = tmp_path / "chargers.csv"
    csv_path.write_text(
        "\n".join(
            [
                "source_name,operator_name,station_external_id,station_name,latitude,longitude,evse_uid,connector_type,max_power_kw,is_sample_data",
                "Bad Source,Operator Uno,bad-001,Bad Sample,38.870000,-1.090000,bad-001-1,CCS2,180,true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="solo acepta datos autorizados/no sample"):
        call_command("import_chargers", str(csv_path), verbosity=0)


@pytest.mark.django_db
def test_import_chargers_dry_run_validates_without_writing(tmp_path):
    csv_path = tmp_path / "chargers.csv"
    csv_path.write_text(
        "\n".join(
            [
                "source_name,source_kind,source_license,operator_name,station_external_id,"
                "station_name,address,latitude,longitude,evse_uid,status,connector_type,max_power_kw",
                "Authorized OCPI,ocpi,Provider license,Operator Uno,dry-001,Almansa HPC,"
                "A-31 Almansa,38.870000,-1.090000,dry-001-1,available,CCS2,180",
                "Authorized OCPI,ocpi,Provider license,Operator Uno,dry-001,Almansa HPC,"
                "A-31 Almansa,38.870000,-1.090000,dry-001-2,available,CCS2,180",
            ]
        ),
        encoding="utf-8",
    )
    output = StringIO()

    call_command("import_chargers", str(csv_path), "--dry-run", stdout=output)

    assert "Validated 1 stations, 2 EVSEs, 2 connectors. No database changes were made." in output.getvalue()
    assert Station.objects.count() == 0
    assert EVSE.objects.count() == 0
    assert Connector.objects.count() == 0


@pytest.mark.django_db
def test_import_chargers_dry_run_rejects_unauthorized_source_kind(tmp_path):
    csv_path = tmp_path / "chargers.csv"
    csv_path.write_text(
        "\n".join(
            [
                "source_name,source_kind,operator_name,station_external_id,station_name,"
                "latitude,longitude,evse_uid,connector_type,max_power_kw",
                "Bad Source,test,Operator Uno,bad-001,Bad Source,"
                "38.870000,-1.090000,bad-001-1,CCS2,180",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="source_kind debe identificar una fuente autorizada"):
        call_command("import_chargers", str(csv_path), "--dry-run", verbosity=0)
    assert Station.objects.count() == 0


@pytest.mark.django_db
def test_manual_charger_records_default_to_untrusted_and_unknown():
    source = DataSource.objects.create(name="Manual source")
    operator = Operator.objects.create(name="Manual operator")
    station = Station.objects.create(
        external_id="manual-001",
        operator=operator,
        data_source=source,
        name="Manual Station",
        latitude=Decimal("38.870000"),
        longitude=Decimal("-1.090000"),
    )
    evse = EVSE.objects.create(station=station, evse_uid="manual-001-1", max_power_kw=50)

    assert source.is_authorized is False
    assert evse.status == "unknown"


def test_reve_dev_locations_are_converted_to_import_records():
    records = reve_locations_to_charger_records([reve_location_payload()])

    assert records == [
        {
            "source_name": "REVE public map dev scrape",
            "source_kind": "reve-dev",
            "source_license": "Development-only cache from mapareve.es public map; not approved for production use.",
            "source_notes": (
                "Captured from REVE public map endpoints for local development tests only. "
                "Request official API access before using REVE data outside dev."
            ),
            "operator_name": "REPSOL SOLUCIONES ENERGETICAS SA",
            "operator_website": "https://WWW.REPSOL.COM",
            "operator_support_phone": "676461625",
            "station_external_id": "reve:0008eb32-d6c0-4485-a41f-1d81566db05b",
            "station_name": "Repsol, Elorrio, Via Publica",
            "address": "Nizeto Urkizu Kalea 4, 48230, ESP",
            "latitude": "43.130332",
            "longitude": "-2.541078",
            "amenities": "restaurant|bathroom",
            "evse_uid": "reve:ES*REP*E3125*1",
            "status": "available",
            "connector_type": "CCS2",
            "max_power_kw": 150,
            "tariff_is_estimated": False,
            "observed_at": "2026-06-13T21:49:55.847Z",
            "price_per_kwh": "0.36",
            "currency": "EUR",
        }
    ]


def test_reve_dev_connector_normalization_keeps_common_vehicle_values():
    assert normalize_reve_connector("IEC_62196_T2_COMBO") == "CCS2"
    assert normalize_reve_connector("IEC_62196_T2") == "TYPE2"
    assert normalize_reve_connector("CHADEMO") == "CHAdeMO"


@override_settings(DEBUG=True)
def test_scrape_reve_dev_command_rebuilds_from_cached_pages_offline(tmp_path):
    cache_dir = tmp_path / "reve-pages"
    output_path = tmp_path / "reve-chargers.json"
    cache_dir.mkdir()
    reve_page_cache_file(cache_dir, 1).write_text(
        json.dumps(
            {
                "data": [reve_location_payload()],
                "pagination": {"page": 1, "per_page": 10, "next": None, "prev": None, "total_count": 1, "total_pages": 1},
            }
        ),
        encoding="utf-8",
    )

    call_command(
        "scrape_reve_dev",
        "--offline",
        f"--cache-dir={cache_dir}",
        f"--output={output_path}",
        verbosity=0,
    )

    records = json.loads(output_path.read_text(encoding="utf-8"))["stations"]
    assert len(records) == 1
    assert records[0]["station_external_id"] == "reve:0008eb32-d6c0-4485-a41f-1d81566db05b"
    assert records[0]["connector_type"] == "CCS2"


@override_settings(DEBUG=False)
def test_scrape_reve_dev_command_is_disabled_outside_debug(monkeypatch):
    monkeypatch.delenv("KALMIO_ALLOW_REVE_DEV_SCRAPE", raising=False)

    with pytest.raises(CommandError, match="disabled when DEBUG=false"):
        call_command("scrape_reve_dev", "--max-pages=1", verbosity=0)


def reve_location_payload():
    return {
        "id": "0008eb32-d6c0-4485-a41f-1d81566db05b",
        "status": "AVAILABLE",
        "name": "Repsol, Elorrio, Via Publica",
        "address": "Nizeto Urkizu Kalea 4",
        "postal_code": "48230",
        "country": "ESP",
        "owner": {
            "name": "REPSOL SOLUCIONES ENERGETICAS SA",
            "website": "WWW.REPSOL.COM",
            "phone": "676461625",
        },
        "coordinates": {"latitude": "43.130332", "longitude": "-2.541078"},
        "facilities": ["restaurant", "bathroom"],
        "evses": [
            {
                "evse_id": "ES*REP*E3125*1",
                "status": "AVAILABLE",
                "status_updated_at": "2026-06-13T21:49:55.847Z",
                "connectors": [
                    {
                        "standard": "IEC_62196_T2_COMBO",
                        "max_electric_power": 150000,
                        "tariffs": [
                            {
                                "human": ["0.36 EUR/kWh"],
                                "tariff": {
                                    "currency": "EUR",
                                    "elements": [
                                        {
                                            "price_components": [
                                                {"type": "ENERGY", "price": 0.36, "vat": 21.0}
                                            ]
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
