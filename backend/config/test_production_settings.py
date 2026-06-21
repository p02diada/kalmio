import importlib
import os
import subprocess
import sys

from django.urls import clear_url_caches


BASE_PRODUCTION_ENV = {
    "KALMIO_ENV": "production",
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": "test-secret-key-for-production-settings-checks",
    "DJANGO_ALLOWED_HOSTS": "api.kalmio.example",
    "CORS_ALLOWED_ORIGINS": "https://app.kalmio.example",
    "CSRF_TRUSTED_ORIGINS": "https://app.kalmio.example",
    "KALMIO_DB_ENGINE": "postgis",
    "POSTGRES_DB": "kalmio",
    "POSTGRES_USER": "kalmio",
    "POSTGRES_PASSWORD": "ci-production-db-password-4f750d65",
    "POSTGRES_HOST": "db",
    "POSTGRES_PORT": "5432",
    "KALMIO_DEEPSEEK_API_KEY": "ci-deepseek-key-for-production-settings-checks",
}


def test_production_requires_explicit_osrm_base_url():
    result = import_settings({"KALMIO_OSRM_BASE_URL": None})

    assert result.returncode != 0
    assert "KALMIO_OSRM_BASE_URL is required" in result.stderr


def test_production_rejects_public_development_osrm_url():
    result = import_settings({"KALMIO_OSRM_BASE_URL": "https://router.project-osrm.org"})

    assert result.returncode != 0
    assert "explicit production routing provider" in result.stderr


def test_production_rejects_invalid_osrm_base_url():
    result = import_settings({"KALMIO_OSRM_BASE_URL": "routes.kalmio.internal"})

    assert result.returncode != 0
    assert "KALMIO_OSRM_BASE_URL must be an absolute HTTP(S) URL" in result.stderr


def test_production_rejects_non_http_osrm_base_url():
    result = import_settings({"KALMIO_OSRM_BASE_URL": "ftp://routes.kalmio.example"})

    assert result.returncode != 0
    assert "KALMIO_OSRM_BASE_URL must be an absolute HTTP(S) URL" in result.stderr


def test_production_accepts_explicit_routing_provider_url():
    result = import_settings({"KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example"})

    assert result.returncode == 0, result.stderr


def test_production_rejects_placeholder_secret_key():
    result = import_settings({
        "DJANGO_SECRET_KEY": "replace-with-a-long-random-secret-from-your-secret-manager",
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
    })

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY must be a real production secret" in result.stderr


def test_production_rejects_placeholder_database_password():
    result = import_settings({
        "POSTGRES_PASSWORD": "replace-with-a-strong-database-password",
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
    })

    assert result.returncode != 0
    assert "POSTGRES_PASSWORD must be a real production secret" in result.stderr


def test_production_rejects_default_database_password():
    result = import_settings({
        "POSTGRES_PASSWORD": "kalmio",
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
    })

    assert result.returncode != 0
    assert "POSTGRES_PASSWORD must be a real production secret" in result.stderr


def test_production_rejects_non_https_cors_origin():
    result = import_settings({
        "CORS_ALLOWED_ORIGINS": "http://app.kalmio.example",
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
    })

    assert result.returncode != 0
    assert "CORS_ALLOWED_ORIGINS must contain only HTTPS origins" in result.stderr


def test_production_rejects_non_https_csrf_origin():
    result = import_settings({
        "CSRF_TRUSTED_ORIGINS": "http://app.kalmio.example",
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
    })

    assert result.returncode != 0
    assert "CSRF_TRUSTED_ORIGINS must contain only HTTPS origins" in result.stderr


def test_production_accepts_multiple_https_origins():
    result = import_settings({
        "CORS_ALLOWED_ORIGINS": "https://app.kalmio.example,https://admin.kalmio.example",
        "CSRF_TRUSTED_ORIGINS": "https://app.kalmio.example,https://*.kalmio.example",
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
    })

    assert result.returncode == 0, result.stderr


def test_osrm_timeout_must_be_positive():
    result = import_settings({
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
        "KALMIO_OSRM_TIMEOUT_SECONDS": "0",
    })

    assert result.returncode != 0
    assert "KALMIO_OSRM_TIMEOUT_SECONDS must be greater than zero" in result.stderr


def test_log_level_must_be_supported():
    result = import_settings({
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
        "KALMIO_LOG_LEVEL": "LOUD",
    })

    assert result.returncode != 0
    assert "KALMIO_LOG_LEVEL must be one of" in result.stderr


def test_production_admin_url_is_disabled_by_default():
    patterns = url_patterns_for_admin_setting(enabled=False)

    assert "admin/" not in patterns
    assert "api/" in patterns


def test_production_admin_url_can_be_enabled_with_custom_path():
    patterns = url_patterns_for_admin_setting(enabled=True, path="internal-admin/")

    assert "internal-admin/" in patterns


def test_enabled_admin_path_must_end_with_slash():
    result = import_settings({
        "KALMIO_ENABLE_ADMIN": "true",
        "KALMIO_ADMIN_PATH": "internal-admin",
        "KALMIO_OSRM_BASE_URL": "https://routes.kalmio.example",
    })

    assert result.returncode != 0
    assert "KALMIO_ADMIN_PATH must end with '/'" in result.stderr


def import_settings(overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(BASE_PRODUCTION_ENV)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def url_patterns_for_admin_setting(*, enabled: bool, path: str = "admin/") -> list[str]:
    from django.conf import settings

    settings.KALMIO_ENABLE_ADMIN = enabled
    settings.KALMIO_ADMIN_PATH = path
    clear_url_caches()

    import config.urls

    urls = importlib.reload(config.urls)
    return [str(pattern.pattern) for pattern in urls.urlpatterns]
