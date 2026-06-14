from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from accounts.models import AuthThrottle
from accounts.security import auth_throttle_key


@pytest.fixture(autouse=True)
def clear_auth_throttles(db):
    AuthThrottle.objects.all().delete()
    yield
    AuthThrottle.objects.all().delete()


@pytest.mark.django_db
def test_register_login_logout_session_flow_with_csrf():
    client = Client(enforce_csrf_checks=True)
    csrf_response = client.get("/api/auth/csrf")
    csrf_token = csrf_response.cookies["csrftoken"].value

    register_response = client.post(
        "/api/auth/register",
        data={"email": "driver@example.com", "password": "safe-password-123"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert register_response.status_code == 200
    assert register_response.json()["authenticated"] is True
    assert register_response.json()["csrf_token"]
    assert get_user_model().objects.filter(username="driver@example.com").exists()
    csrf_token = register_response.json()["csrf_token"]

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "driver@example.com"

    logout_response = client.post("/api/auth/logout", HTTP_X_CSRFTOKEN=csrf_token)
    assert logout_response.status_code == 200
    assert logout_response.json()["authenticated"] is False
    assert logout_response.json()["csrf_token"]


@pytest.mark.django_db
def test_current_user_anonymous_response_matches_public_contract(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"id": None, "email": "", "authenticated": False, "csrf_token": None}


@pytest.mark.django_db
def test_register_rejects_missing_csrf_token():
    client = Client(enforce_csrf_checks=True)

    response = client.post(
        "/api/auth/register",
        data={"email": "driver@example.com", "password": "safe-password-123"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_register_rejects_invalid_email_with_csrf():
    client = Client(enforce_csrf_checks=True)
    csrf_token = client.get("/api/auth/csrf").cookies["csrftoken"].value

    response = client.post(
        "/api/auth/register",
        data={"email": "not-an-email", "password": "safe-password-123"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Introduce un email válido."
    assert get_user_model().objects.count() == 0


def test_auth_throttle_key_fits_model_field():
    request = type("Request", (), {"META": {"REMOTE_ADDR": "203.0.113.10"}})()
    key = auth_throttle_key("register", "driver@example.com", request)
    key_field = AuthThrottle._meta.get_field("key")

    assert len(key) <= key_field.max_length
    assert key.startswith("kalmio:auth-throttle:")


@pytest.mark.django_db
def test_login_throttles_repeated_failed_attempts(settings):
    settings.KALMIO_AUTH_THROTTLE_LIMIT = 2
    settings.KALMIO_AUTH_THROTTLE_WINDOW_SECONDS = 60
    get_user_model().objects.create_user(
        username="driver@example.com",
        email="driver@example.com",
        password="safe-password-123",
    )
    client = Client(enforce_csrf_checks=True)
    csrf_token = client.get("/api/auth/csrf").cookies["csrftoken"].value

    for _ in range(2):
        response = client.post(
            "/api/auth/login",
            data={"email": "driver@example.com", "password": "wrong-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        assert response.status_code == 400

    throttled_response = client.post(
        "/api/auth/login",
        data={"email": "driver@example.com", "password": "wrong-password"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert throttled_response.status_code == 429
    assert "Demasiados intentos" in throttled_response.json()["detail"]
    assert AuthThrottle.objects.count() == 1


@pytest.mark.django_db
def test_login_success_clears_failed_attempt_counter(settings):
    settings.KALMIO_AUTH_THROTTLE_LIMIT = 2
    settings.KALMIO_AUTH_THROTTLE_WINDOW_SECONDS = 60
    get_user_model().objects.create_user(
        username="driver@example.com",
        email="driver@example.com",
        password="safe-password-123",
    )
    client = Client(enforce_csrf_checks=True)
    csrf_token = client.get("/api/auth/csrf").cookies["csrftoken"].value

    first_failure = client.post(
        "/api/auth/login",
        data={"email": "driver@example.com", "password": "wrong-password"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert first_failure.status_code == 400

    success = client.post(
        "/api/auth/login",
        data={"email": "driver@example.com", "password": "safe-password-123"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert success.status_code == 200
    csrf_token = success.json()["csrf_token"]
    assert AuthThrottle.objects.count() == 0

    for _ in range(2):
        response = client.post(
            "/api/auth/login",
            data={"email": "driver@example.com", "password": "wrong-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        assert response.status_code == 400

    throttled_response = client.post(
        "/api/auth/login",
        data={"email": "driver@example.com", "password": "wrong-password"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert throttled_response.status_code == 429


@pytest.mark.django_db
def test_auth_throttle_prunes_expired_attempts(settings):
    settings.KALMIO_AUTH_THROTTLE_LIMIT = 2
    settings.KALMIO_AUTH_THROTTLE_WINDOW_SECONDS = 60
    AuthThrottle.objects.create(
        key="a" * 64,
        attempts=2,
        window_started_at=timezone.now() - timedelta(minutes=10),
    )
    get_user_model().objects.create_user(
        username="driver@example.com",
        email="driver@example.com",
        password="safe-password-123",
    )
    client = Client(enforce_csrf_checks=True)
    csrf_token = client.get("/api/auth/csrf").cookies["csrftoken"].value

    response = client.post(
        "/api/auth/login",
        data={"email": "driver@example.com", "password": "wrong-password"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 400
    assert not AuthThrottle.objects.filter(key="a" * 64).exists()
