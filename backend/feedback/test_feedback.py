from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client

from charging.models import DataSource, Operator, Station
from feedback.models import Feedback
from routing.models import RoutePlan


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="driver@example.com", email="driver@example.com", password="safe-password-123")


@pytest.fixture
def route_plan(db, user):
    source = DataSource.objects.create(name="Authorized provider", kind="ocpi", is_authorized=True)
    operator = Operator.objects.create(name="Real Operator")
    station = Station.objects.create(
        external_id="real-feedback-001",
        operator=operator,
        data_source=source,
        name="Feedback HPC",
        address="A-31",
        latitude=Decimal("38.870000"),
        longitude=Decimal("-1.090000"),
        is_sample_data=False,
    )
    return RoutePlan.objects.create(
        user=user,
        origin_label="Córdoba",
        destination_label="Valencia",
        origin_latitude=Decimal("37.888200"),
        origin_longitude=Decimal("-4.779400"),
        destination_latitude=Decimal("39.469900"),
        destination_longitude=Decimal("-0.376300"),
        distance_km=Decimal("520.0"),
        duration_min=355,
        energy_kwh=Decimal("103.6"),
        arrival_battery_percent=Decimal("0.0"),
        recommendation_station=station,
        recommendation_snapshot={"id": station.id, "external_id": station.external_id, "name": station.name},
        alternatives_snapshot=[],
        warnings=[],
        request_payload={},
    )


@pytest.mark.django_db
def test_create_feedback_for_owned_route_plan(client, user, route_plan):
    client.force_login(user)

    response = client.post(
        "/api/feedback",
        data={"route_plan_id": str(route_plan.public_id), "kind": "useful", "comment": "Claro"},
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "stored"
    assert Feedback.objects.filter(user=user, route_plan=route_plan, kind="useful").exists()


@pytest.mark.django_db
def test_feedback_rejects_unknown_kind(client, user, route_plan):
    client.force_login(user)

    response = client.post(
        "/api/feedback",
        data={"route_plan_id": str(route_plan.public_id), "kind": "unknown"},
        content_type="application/json",
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_feedback_requires_authentication(client, route_plan):
    response = client.post(
        "/api/feedback",
        data={"route_plan_id": str(route_plan.public_id), "kind": "useful"},
        content_type="application/json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_feedback_rejects_other_users_route_plan(client, route_plan):
    other_user = get_user_model().objects.create_user(username="other@example.com", email="other@example.com", password="safe-password-123")
    client.force_login(other_user)

    response = client.post(
        "/api/feedback",
        data={"route_plan_id": str(route_plan.public_id), "kind": "useful"},
        content_type="application/json",
    )

    assert response.status_code == 404
    assert Feedback.objects.count() == 0


@pytest.mark.django_db
def test_feedback_rejects_missing_csrf(user, route_plan):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(
        "/api/feedback",
        data={"route_plan_id": str(route_plan.public_id), "kind": "useful"},
        content_type="application/json",
    )

    assert response.status_code == 403


def test_feedback_is_registered_in_admin():
    assert Feedback in admin.site._registry
