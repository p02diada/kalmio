from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from vehicles.iternio import import_iternio_vehicle_catalog, validate_catalog_payload
from vehicles.models import VehicleProfile, VehicleProfileSource


@pytest.fixture
def iternio_payload():
    return {
        "vehicles": [
            {
                "typecode": "tesla:my:25:lr:awd",
                "manufacturer": "Tesla",
                "model": "Model Y",
                "title": "Tesla Model Y Long Range AWD",
                "maturity": "MATURE",
                "driveTrain": "AWD",
                "startYear": 2025,
                "batteryCapacityWh": 79000,
                "batteryChemistry": "NMC",
                "batteryName": "Long Range",
                "referenceConsumption": 180,
                "recommendedMaxSpeed": 150,
                "defaultConnectors": ["CCS2"],
                "dcConnectors": ["CCS2"],
                "dcConnectorPowers": [250000],
                "acConnectors": ["TYPE2"],
                "hasDcfcPreconditioning": True,
                "hasHeatpump": True,
                "options": [{"id": "heatpump"}],
                "displayHints": {"tags": ["BATTERY_CAPACITY"]},
                "idealTrip": {"chargeTime": 1200},
            }
        ],
        "options": [{"id": "heatpump"}],
        "display": [{"manufacturer": "Tesla", "model": "Model Y"}],
    }


def test_import_iternio_vehicle_catalog_upserts_vehicle(db, iternio_payload):
    result = import_iternio_vehicle_catalog(iternio_payload)

    assert result.vehicles == 1
    vehicle = VehicleProfile.objects.get(typecode="tesla:my:25:lr:awd")
    assert vehicle.manufacturer == "Tesla"
    assert vehicle.model == "Model Y"
    assert vehicle.battery_capacity_wh == 79000
    assert vehicle.reference_consumption_wh_km == Decimal("180")
    assert vehicle.dc_connectors == ["CCS2"]
    assert vehicle.dc_connector_powers_w == [250000]
    assert vehicle.source.is_authorized is True


def test_import_iternio_vehicle_catalog_replaces_source_profiles(db, iternio_payload):
    import_iternio_vehicle_catalog(iternio_payload)
    payload = {
        **iternio_payload,
        "vehicles": [
            {
                **iternio_payload["vehicles"][0],
                "typecode": "tesla:my:25:rwd",
                "title": "Tesla Model Y RWD",
            }
        ],
    }

    import_iternio_vehicle_catalog(payload, replace=True)

    assert list(VehicleProfile.objects.values_list("typecode", flat=True)) == ["tesla:my:25:rwd"]
    assert VehicleProfileSource.objects.count() == 1


def test_validate_catalog_payload_rejects_missing_required_vehicle_fields():
    with pytest.raises(ValueError, match="missing required field typecode"):
        validate_catalog_payload({"vehicles": [{"manufacturer": "Tesla", "model": "Model Y", "title": "Model Y"}]})


def test_import_iternio_vehicles_requires_explicit_api_key(monkeypatch):
    monkeypatch.delenv("ITERNIO_API_KEY", raising=False)

    with pytest.raises(CommandError, match="ITERNIO_API_KEY is required"):
        call_command("import_iternio_vehicles", verbosity=0)


def test_import_iternio_vehicles_dry_run_fetches_without_writing(db, monkeypatch, iternio_payload):
    def fake_fetch(**kwargs):
        assert kwargs["api_key"] == "issued-key"
        return iternio_payload

    monkeypatch.setattr("vehicles.management.commands.import_iternio_vehicles.fetch_iternio_vehicle_catalog", fake_fetch)

    output = StringIO()
    call_command("import_iternio_vehicles", "--api-key", "issued-key", "--dry-run", stdout=output)

    assert "Validated 1 vehicle profiles" in output.getvalue()
    assert VehicleProfile.objects.count() == 0
