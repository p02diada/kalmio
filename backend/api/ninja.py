from datetime import datetime, timezone

from accounts.api import router as accounts_router
from charging.api import router as charging_router
from charging.models import Station
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from feedback.api import router as feedback_router
from ninja import NinjaAPI
from routing.api import router as routing_router
from routing.providers import RoutingProviderError, get_route_provider
from routing.providers import Coordinate

api = NinjaAPI(
    title="Kalmio API",
    version="0.1.0",
    openapi_url="/openapi.json" if settings.KALMIO_ENABLE_API_DOCS else None,
    docs_url="/docs" if settings.KALMIO_ENABLE_API_DOCS else None,
)
api.add_router("", accounts_router)
api.add_router("", charging_router)
api.add_router("", feedback_router)
api.add_router("", routing_router)


@api.get("/health")
def health(request):
    return {
        "status": "ok",
        "service": "kalmio-backend",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@api.get("/ready")
def readiness(request):
    checks = [
        check_database(),
        check_migrations(),
        check_route_provider(),
        check_authorized_charger_data(),
    ]
    is_ready = all(check["ok"] for check in checks)

    return JsonResponse(
        {
            "status": "ready" if is_ready else "not_ready",
            "service": "kalmio-backend",
            "time": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        },
        status=200 if is_ready else 503,
    )


def check_database() -> dict:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # pragma: no cover - depends on infrastructure failure mode.
        return {"name": "database", "ok": False, "detail": str(exc)}

    return {"name": "database", "ok": True}


def check_migrations() -> dict:
    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:  # pragma: no cover - depends on infrastructure failure mode.
        return {"name": "migrations", "ok": False, "detail": str(exc)}

    if pending:
        return {"name": "migrations", "ok": False, "detail": f"{len(pending)} pending migrations"}
    return {"name": "migrations", "ok": True}


def check_route_provider() -> dict:
    try:
        provider = get_route_provider()
    except RoutingProviderError as exc:
        return {"name": "route_provider", "ok": False, "detail": str(exc)}

    if getattr(settings, "KALMIO_ROUTING_READINESS_CHECK", False):
        try:
            provider.route(Coordinate(37.8882, -4.7794), Coordinate(39.4699, -0.3763))
        except RoutingProviderError as exc:
            return {"name": "route_provider", "ok": False, "detail": f"provider probe failed: {exc}"}

    return {
        "name": "route_provider",
        "ok": True,
        "detail": {"provider": settings.KALMIO_ROUTING_PROVIDER},
    }


def check_authorized_charger_data() -> dict:
    station_count = (
        Station.objects.filter(
            is_sample_data=False,
            data_source__is_authorized=True,
            evses__connectors__isnull=False,
        )
        .distinct()
        .count()
    )
    if station_count == 0:
        return {
            "name": "authorized_charger_data",
            "ok": False,
            "detail": "No authorized station data with connectors is available.",
        }

    return {"name": "authorized_charger_data", "ok": True, "detail": {"stations": station_count}}
