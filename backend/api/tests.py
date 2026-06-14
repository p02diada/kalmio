import pytest
from django.core.management import call_command
from django.test import Client


def test_healthcheck():
    response = Client().get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_healthcheck_returns_safe_request_id_header():
    response = Client().get("/api/health", HTTP_X_REQUEST_ID="trace-123")

    assert response.status_code == 200
    assert response["X-Request-ID"] == "trace-123"


def test_healthcheck_replaces_invalid_request_id_header():
    response = Client().get("/api/health", HTTP_X_REQUEST_ID="bad value with spaces")

    assert response.status_code == 200
    assert response["X-Request-ID"] != "bad value with spaces"
    assert len(response["X-Request-ID"]) == 32


@pytest.mark.django_db
def test_readiness_fails_without_authorized_charger_data():
    response = Client().get("/api/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert any(
        check["name"] == "authorized_charger_data" and check["ok"] is False
        for check in body["checks"]
    )


@pytest.mark.django_db
def test_readiness_passes_with_authorized_charger_data(tmp_path):
    csv_path = tmp_path / "chargers.csv"
    csv_path.write_text(
        "\n".join(
            [
                "source_name,source_kind,source_license,operator_name,station_external_id,"
                "station_name,address,latitude,longitude,evse_uid,status,connector_type,max_power_kw",
                "Authorized OCPI,ocpi,Provider license,Operator Uno,ready-001,Almansa HPC,"
                "A-31 Almansa,38.870000,-1.090000,ready-001-1,available,CCS2,180",
            ]
        ),
        encoding="utf-8",
    )
    call_command("import_chargers", str(csv_path), verbosity=0)

    response = Client().get("/api/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert all(check["ok"] is True for check in body["checks"])
    assert next(
        check for check in body["checks"] if check["name"] == "authorized_charger_data"
    )["detail"]["stations"] == 1
    route_provider_check = next(check for check in body["checks"] if check["name"] == "route_provider")
    assert route_provider_check["detail"] == {"provider": "osrm"}
    assert "base_url" not in route_provider_check["detail"]


def test_api_docs_are_available_in_development(settings):
    settings.KALMIO_ENABLE_API_DOCS = True

    response = Client().get("/api/docs")

    assert response.status_code == 200
