"""Django settings for Kalmio."""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def require_https_origins(name: str, origins: list[str]) -> None:
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ImproperlyConfigured(f"{name} must contain only HTTPS origins in production.")


def require_http_url(name: str, value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImproperlyConfigured(f"{name} must be an absolute HTTP(S) URL.")


def _ensure_value(values: list[str], candidate: str) -> list[str]:
    if candidate and candidate not in values:
        values.append(candidate)
    return values


KALMIO_ENV = os.getenv("KALMIO_ENV", "development").strip().lower()
IS_PRODUCTION = KALMIO_ENV == "production"
KALMIO_LOGFIRE_ENABLED = env_bool("KALMIO_LOGFIRE_ENABLED", default=False)

DEBUG = env_bool("DJANGO_DEBUG", default=not IS_PRODUCTION)
if IS_PRODUCTION and DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG must be false when KALMIO_ENV=production.")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when KALMIO_ENV=production.")
    SECRET_KEY = get_random_secret_key()
if IS_PRODUCTION and any(marker in SECRET_KEY.lower() for marker in {"replace-with", "change-me", "dev-only"}):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a real production secret.")

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    default="" if IS_PRODUCTION else "localhost,127.0.0.1,0.0.0.0,testserver",
)
if IS_PRODUCTION and (not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS):
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must contain explicit production hosts.")
if not IS_PRODUCTION:
    ALLOWED_HOSTS = _ensure_value(ALLOWED_HOSTS, ".trycloudflare.com")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "accounts",
    "api",
    "charging",
    "vehicles",
    "routing",
    "feedback",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.RequestIDMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DB_ENGINE = os.getenv("KALMIO_DB_ENGINE", "sqlite")
if DB_ENGINE not in {"sqlite", "postgis"}:
    raise ImproperlyConfigured("KALMIO_DB_ENGINE must be either 'sqlite' for unit tests or 'postgis'.")
if IS_PRODUCTION and DB_ENGINE != "postgis":
    raise ImproperlyConfigured("KALMIO_DB_ENGINE=postgis is required when KALMIO_ENV=production.")

if DB_ENGINE == "postgis":
    database_password = os.getenv("POSTGRES_PASSWORD", "kalmio")
    unsafe_database_passwords = {"", "kalmio", "postgres", "password"}
    if IS_PRODUCTION and (
        database_password.lower() in unsafe_database_passwords
        or any(marker in database_password.lower() for marker in {"replace-with", "change-me", "dev-only"})
    ):
        raise ImproperlyConfigured("POSTGRES_PASSWORD must be a real production secret.")
    database_options = {}
    database_sslmode = os.getenv("POSTGRES_SSLMODE", "require" if IS_PRODUCTION else "")
    if database_sslmode:
        database_options["sslmode"] = database_sslmode

    DATABASES = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": os.getenv("POSTGRES_DB", "kalmio"),
            "USER": os.getenv("POSTGRES_USER", "kalmio"),
            "PASSWORD": database_password,
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("POSTGRES_CONN_MAX_AGE", "600" if IS_PRODUCTION else "0")),
            "OPTIONS": database_options,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-es"
TIME_ZONE = "Europe/Madrid"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if KALMIO_LOGFIRE_ENABLED:
    from config.logfire import configure_logfire

    configure_logfire(
        service_name=os.getenv("KALMIO_LOGFIRE_SERVICE_NAME", "kalmio-backend"),
        environment=KALMIO_ENV,
        local_default=not IS_PRODUCTION,
    )

KALMIO_ENABLE_ADMIN = env_bool("KALMIO_ENABLE_ADMIN", default=not IS_PRODUCTION)
KALMIO_ADMIN_PATH = os.getenv("KALMIO_ADMIN_PATH", "admin/").strip().lstrip("/")
if KALMIO_ENABLE_ADMIN and not KALMIO_ADMIN_PATH:
    raise ImproperlyConfigured("KALMIO_ADMIN_PATH is required when KALMIO_ENABLE_ADMIN=true.")
if KALMIO_ENABLE_ADMIN and not KALMIO_ADMIN_PATH.endswith("/"):
    raise ImproperlyConfigured("KALMIO_ADMIN_PATH must end with '/'.")

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    default="" if IS_PRODUCTION else "http://localhost:5173,http://127.0.0.1:5173",
)
if IS_PRODUCTION and not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured("CORS_ALLOWED_ORIGINS is required when KALMIO_ENV=production.")
if IS_PRODUCTION:
    require_https_origins("CORS_ALLOWED_ORIGINS", CORS_ALLOWED_ORIGINS)
if not IS_PRODUCTION:
    CORS_ALLOWED_ORIGINS = _ensure_value(CORS_ALLOWED_ORIGINS, "https://*.trycloudflare.com")
CORS_ALLOWED_ORIGIN_REGEXES = env_list("CORS_ALLOWED_ORIGIN_REGEXES")
if not IS_PRODUCTION:
    CORS_ALLOWED_ORIGIN_REGEXES = _ensure_value(
        CORS_ALLOWED_ORIGIN_REGEXES,
        r"^https://[A-Za-z0-9-]+\.trycloudflare\.com$",
    )

CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    default="" if IS_PRODUCTION else "http://localhost:5173,http://127.0.0.1:5173",
)
if IS_PRODUCTION and not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS is required when KALMIO_ENV=production.")
if IS_PRODUCTION:
    require_https_origins("CSRF_TRUSTED_ORIGINS", CSRF_TRUSTED_ORIGINS)
if not IS_PRODUCTION:
    CSRF_TRUSTED_ORIGINS = _ensure_value(CSRF_TRUSTED_ORIGINS, "https://*.trycloudflare.com")

SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=IS_PRODUCTION)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000" if IS_PRODUCTION else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=IS_PRODUCTION)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=IS_PRODUCTION)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.getenv("DJANGO_SECURE_REFERRER_POLICY", "same-origin")
if env_bool("DJANGO_TRUST_X_FORWARDED_PROTO", default=IS_PRODUCTION):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=IS_PRODUCTION)
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=IS_PRODUCTION)
CSRF_COOKIE_HTTPONLY = env_bool("CSRF_COOKIE_HTTPONLY", default=IS_PRODUCTION)
CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "Lax")

KALMIO_AUTH_THROTTLE_LIMIT = int(os.getenv("KALMIO_AUTH_THROTTLE_LIMIT", "5"))
KALMIO_AUTH_THROTTLE_WINDOW_SECONDS = int(os.getenv("KALMIO_AUTH_THROTTLE_WINDOW_SECONDS", "900"))
if KALMIO_AUTH_THROTTLE_LIMIT <= 0:
    raise ImproperlyConfigured("KALMIO_AUTH_THROTTLE_LIMIT must be greater than zero.")
if KALMIO_AUTH_THROTTLE_WINDOW_SECONDS <= 0:
    raise ImproperlyConfigured("KALMIO_AUTH_THROTTLE_WINDOW_SECONDS must be greater than zero.")

KALMIO_ENABLE_API_DOCS = env_bool("KALMIO_ENABLE_API_DOCS", default=not IS_PRODUCTION)
KALMIO_ROUTING_PROVIDER = os.getenv("KALMIO_ROUTING_PROVIDER", "osrm").strip().lower()
KALMIO_GEOCODING_PROVIDER = os.getenv("KALMIO_GEOCODING_PROVIDER", "mapbox").strip().lower()
if KALMIO_GEOCODING_PROVIDER not in {"mapbox", "local"}:
    raise ImproperlyConfigured("KALMIO_GEOCODING_PROVIDER must be mapbox or local.")
KALMIO_MAPBOX_ACCESS_TOKEN = os.getenv("KALMIO_MAPBOX_ACCESS_TOKEN", "").strip()
KALMIO_MAPBOX_GEOCODING_BASE_URL = os.getenv(
    "KALMIO_MAPBOX_GEOCODING_BASE_URL",
    "https://api.mapbox.com",
).strip()
require_http_url("KALMIO_MAPBOX_GEOCODING_BASE_URL", KALMIO_MAPBOX_GEOCODING_BASE_URL)
KALMIO_MAPBOX_SEARCH_API = os.getenv("KALMIO_MAPBOX_SEARCH_API", "auto").strip().lower()
if KALMIO_MAPBOX_SEARCH_API not in {"auto", "searchbox", "geocoding"}:
    raise ImproperlyConfigured("KALMIO_MAPBOX_SEARCH_API must be auto, searchbox, or geocoding.")
KALMIO_GEOCODING_COUNTRY = os.getenv("KALMIO_GEOCODING_COUNTRY", "ES").strip()
KALMIO_GEOCODING_LANGUAGE = os.getenv("KALMIO_GEOCODING_LANGUAGE", "es").strip()
try:
    KALMIO_GEOCODING_TIMEOUT_SECONDS = float(os.getenv("KALMIO_GEOCODING_TIMEOUT_SECONDS", "4"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_GEOCODING_TIMEOUT_SECONDS must be a number.") from exc
if KALMIO_GEOCODING_TIMEOUT_SECONDS <= 0:
    raise ImproperlyConfigured("KALMIO_GEOCODING_TIMEOUT_SECONDS must be greater than zero.")
try:
    KALMIO_GEOCODING_REQUEST_RETRIES = int(os.getenv("KALMIO_GEOCODING_REQUEST_RETRIES", "1"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_GEOCODING_REQUEST_RETRIES must be an integer.") from exc
if KALMIO_GEOCODING_REQUEST_RETRIES < 0:
    raise ImproperlyConfigured("KALMIO_GEOCODING_REQUEST_RETRIES must be greater than or equal to zero.")
try:
    KALMIO_GEOCODING_LIMIT = int(os.getenv("KALMIO_GEOCODING_LIMIT", "5"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_GEOCODING_LIMIT must be an integer.") from exc
if KALMIO_GEOCODING_LIMIT < 1 or KALMIO_GEOCODING_LIMIT > 10:
    raise ImproperlyConfigured("KALMIO_GEOCODING_LIMIT must be between 1 and 10.")
if IS_PRODUCTION and KALMIO_GEOCODING_PROVIDER == "mapbox" and not KALMIO_MAPBOX_ACCESS_TOKEN:
    raise ImproperlyConfigured("KALMIO_MAPBOX_ACCESS_TOKEN is required when KALMIO_GEOCODING_PROVIDER=mapbox.")

KALMIO_ROUTE_CONVERSATION_THROTTLE_LIMIT = int(os.getenv("KALMIO_ROUTE_CONVERSATION_THROTTLE_LIMIT", "30"))
KALMIO_ROUTE_CONVERSATION_THROTTLE_WINDOW_SECONDS = int(
    os.getenv("KALMIO_ROUTE_CONVERSATION_THROTTLE_WINDOW_SECONDS", "120")
)
if KALMIO_ROUTE_CONVERSATION_THROTTLE_LIMIT <= 0:
    raise ImproperlyConfigured("KALMIO_ROUTE_CONVERSATION_THROTTLE_LIMIT must be greater than zero.")
if KALMIO_ROUTE_CONVERSATION_THROTTLE_WINDOW_SECONDS <= 0:
    raise ImproperlyConfigured(
        "KALMIO_ROUTE_CONVERSATION_THROTTLE_WINDOW_SECONDS must be greater than zero.",
    )

default_agent_mode = "local" if "pytest" in Path(sys.argv[0]).name else "deepseek"
KALMIO_CONVERSATION_AGENT_MODE = os.getenv("KALMIO_CONVERSATION_AGENT_MODE", default_agent_mode).strip().lower()
if KALMIO_CONVERSATION_AGENT_MODE not in {"local", "deepseek", "pydantic_ai"}:
    raise ImproperlyConfigured("KALMIO_CONVERSATION_AGENT_MODE must be local, deepseek, or pydantic_ai.")
KALMIO_CONVERSATION_AGENT_RUNTIME = os.getenv("KALMIO_CONVERSATION_AGENT_RUNTIME", "pydantic_ai").strip().lower()
if KALMIO_CONVERSATION_AGENT_RUNTIME not in {"legacy", "pydantic_ai"}:
    raise ImproperlyConfigured("KALMIO_CONVERSATION_AGENT_RUNTIME must be legacy or pydantic_ai.")

KALMIO_DEEPSEEK_API_KEY = (
    os.getenv("KALMIO_DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or ""
).strip()
if KALMIO_CONVERSATION_AGENT_MODE in {"deepseek", "pydantic_ai"} and not KALMIO_DEEPSEEK_API_KEY:
    raise ImproperlyConfigured(
        "KALMIO_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY is required when KALMIO_CONVERSATION_AGENT_MODE uses DeepSeek."
    )
KALMIO_DEEPSEEK_BASE_URL = os.getenv("KALMIO_DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
require_http_url("KALMIO_DEEPSEEK_BASE_URL", KALMIO_DEEPSEEK_BASE_URL)
KALMIO_DEEPSEEK_MODEL = os.getenv("KALMIO_DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"
try:
    KALMIO_DEEPSEEK_TIMEOUT_SECONDS = float(os.getenv("KALMIO_DEEPSEEK_TIMEOUT_SECONDS", "30"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_TIMEOUT_SECONDS must be a number.") from exc
if KALMIO_DEEPSEEK_TIMEOUT_SECONDS <= 0:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_TIMEOUT_SECONDS must be greater than zero.")
try:
    KALMIO_DEEPSEEK_MAX_TOOL_CALLS = int(os.getenv("KALMIO_DEEPSEEK_MAX_TOOL_CALLS", "3"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_MAX_TOOL_CALLS must be an integer.") from exc
if KALMIO_DEEPSEEK_MAX_TOOL_CALLS < 0 or KALMIO_DEEPSEEK_MAX_TOOL_CALLS > 8:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_MAX_TOOL_CALLS must be between 0 and 8.")
try:
    KALMIO_DEEPSEEK_MAX_TOKENS = int(os.getenv("KALMIO_DEEPSEEK_MAX_TOKENS", "1800"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_MAX_TOKENS must be an integer.") from exc
if KALMIO_DEEPSEEK_MAX_TOKENS <= 0:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_MAX_TOKENS must be greater than zero.")
try:
    KALMIO_DEEPSEEK_TEMPERATURE = float(os.getenv("KALMIO_DEEPSEEK_TEMPERATURE", "0"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_TEMPERATURE must be a number.") from exc
if KALMIO_DEEPSEEK_TEMPERATURE < 0 or KALMIO_DEEPSEEK_TEMPERATURE > 2:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_TEMPERATURE must be between 0 and 2.")
KALMIO_DEEPSEEK_USE_NATIVE_TOOLS = env_bool("KALMIO_DEEPSEEK_USE_NATIVE_TOOLS", default=True)
KALMIO_DEEPSEEK_THINKING = env_bool("KALMIO_DEEPSEEK_THINKING", default=False)
KALMIO_DEEPSEEK_REASONING_EFFORT = os.getenv("KALMIO_DEEPSEEK_REASONING_EFFORT", "high").strip().lower()
if KALMIO_DEEPSEEK_REASONING_EFFORT not in {"high", "max"}:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_REASONING_EFFORT must be high or max.")
deepseek_default_prices = {
    "deepseek-v4-flash": ("0.0028", "0.14", "0.28"),
    "deepseek-v4-pro": ("0.003625", "0.435", "0.87"),
}
deepseek_price_defaults = deepseek_default_prices.get(KALMIO_DEEPSEEK_MODEL, deepseek_default_prices["deepseek-v4-pro"])
try:
    KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_HIT_PER_MILLION_USD = float(
        os.getenv("KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_HIT_PER_MILLION_USD", deepseek_price_defaults[0])
    )
    KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_MISS_PER_MILLION_USD = float(
        os.getenv("KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_MISS_PER_MILLION_USD", deepseek_price_defaults[1])
    )
    KALMIO_DEEPSEEK_PRICE_OUTPUT_PER_MILLION_USD = float(
        os.getenv("KALMIO_DEEPSEEK_PRICE_OUTPUT_PER_MILLION_USD", deepseek_price_defaults[2])
    )
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_PRICE_* values must be numbers.") from exc
if min(
    KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_HIT_PER_MILLION_USD,
    KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_MISS_PER_MILLION_USD,
    KALMIO_DEEPSEEK_PRICE_OUTPUT_PER_MILLION_USD,
) < 0:
    raise ImproperlyConfigured("KALMIO_DEEPSEEK_PRICE_* values must be greater than or equal to zero.")

KALMIO_AGENT_TRACE_ENABLED = env_bool("KALMIO_AGENT_TRACE_ENABLED", default=not IS_PRODUCTION)
KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS = env_bool("KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS", default=False)
if IS_PRODUCTION and KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS:
    raise ImproperlyConfigured("KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS must be false in production.")
KALMIO_AGENT_TRACE_FILE = os.getenv("KALMIO_AGENT_TRACE_FILE", ".tmp/agent-traces.jsonl").strip()
try:
    KALMIO_AGENT_TRACE_MAX_PAYLOAD_CHARS = int(os.getenv("KALMIO_AGENT_TRACE_MAX_PAYLOAD_CHARS", "12000"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_AGENT_TRACE_MAX_PAYLOAD_CHARS must be an integer.") from exc
if KALMIO_AGENT_TRACE_MAX_PAYLOAD_CHARS < 0:
    raise ImproperlyConfigured("KALMIO_AGENT_TRACE_MAX_PAYLOAD_CHARS must be greater than or equal to zero.")

PUBLIC_OSRM_DEVELOPMENT_URL = "https://router.project-osrm.org"
KALMIO_OSRM_BASE_URL = os.getenv(
    "KALMIO_OSRM_BASE_URL",
    "" if IS_PRODUCTION else PUBLIC_OSRM_DEVELOPMENT_URL,
).strip()
if KALMIO_ROUTING_PROVIDER == "osrm":
    if not KALMIO_OSRM_BASE_URL:
        if IS_PRODUCTION:
            raise ImproperlyConfigured("KALMIO_OSRM_BASE_URL is required when KALMIO_ENV=production.")
    else:
        require_http_url("KALMIO_OSRM_BASE_URL", KALMIO_OSRM_BASE_URL)
        if IS_PRODUCTION and KALMIO_OSRM_BASE_URL.rstrip("/") == PUBLIC_OSRM_DEVELOPMENT_URL:
            raise ImproperlyConfigured("KALMIO_OSRM_BASE_URL must point to an explicit production routing provider.")

try:
    KALMIO_OSRM_TIMEOUT_SECONDS = float(os.getenv("KALMIO_OSRM_TIMEOUT_SECONDS", "5"))
except ValueError as exc:
    raise ImproperlyConfigured("KALMIO_OSRM_TIMEOUT_SECONDS must be a number.") from exc
if KALMIO_OSRM_TIMEOUT_SECONDS <= 0:
    raise ImproperlyConfigured("KALMIO_OSRM_TIMEOUT_SECONDS must be greater than zero.")

KALMIO_ROUTING_REQUEST_RETRIES = int(os.getenv("KALMIO_ROUTING_REQUEST_RETRIES", "1"))
if KALMIO_ROUTING_REQUEST_RETRIES < 0:
    raise ImproperlyConfigured("KALMIO_ROUTING_REQUEST_RETRIES must be greater than or equal to zero.")

KALMIO_ROUTING_READINESS_CHECK = env_bool(
    "KALMIO_ROUTING_READINESS_CHECK", default=IS_PRODUCTION
)

KALMIO_LOG_LEVEL = os.getenv("KALMIO_LOG_LEVEL", "INFO").strip().upper()
if KALMIO_LOG_LEVEL not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
    raise ImproperlyConfigured("KALMIO_LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, or CRITICAL.")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "config.middleware.RequestIDLogFilter",
        },
    },
    "formatters": {
        "kalmio": {
            "format": "{levelname} {asctime} request_id={request_id} logger={name} message={message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "kalmio",
            "filters": ["request_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": KALMIO_LOG_LEVEL,
    },
    "loggers": {
        "django.server": {
            "handlers": ["console"],
            "level": KALMIO_LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "kalmio.agent_trace": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
