from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import AuthThrottle


@dataclass(frozen=True)
class ThrottleResult:
    allowed: bool
    limit: int
    window_seconds: int


def check_auth_throttle(scope: str, email: str, request) -> ThrottleResult:
    limit = auth_throttle_limit()
    key = auth_throttle_key(scope, email, request)
    throttle = AuthThrottle.objects.filter(key=key).first()
    attempts = 0 if throttle is None or throttle_is_expired(throttle) else throttle.attempts

    return ThrottleResult(
        allowed=attempts < limit,
        limit=limit,
        window_seconds=auth_throttle_window_seconds(),
    )


def record_auth_failure(scope: str, email: str, request) -> None:
    key = auth_throttle_key(scope, email, request)
    now = timezone.now()
    prune_expired_auth_throttles(now=now)
    with transaction.atomic():
        throttle, created = AuthThrottle.objects.select_for_update().get_or_create(
            key=key,
            defaults={"attempts": 1, "window_started_at": now},
        )
        if created:
            return

        if throttle_is_expired(throttle, now=now):
            throttle.attempts = 1
            throttle.window_started_at = now
        else:
            throttle.attempts += 1
        throttle.save(update_fields=["attempts", "window_started_at", "updated_at"])


def clear_auth_throttle(scope: str, email: str, request) -> None:
    AuthThrottle.objects.filter(key=auth_throttle_key(scope, email, request)).delete()


def auth_throttle_key(scope: str, email: str, request) -> str:
    identity = f"{scope}:{email.strip().lower()}:{client_ip(request)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"kalmio:auth-throttle:{digest}"


def client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR") or "unknown"


def auth_throttle_limit() -> int:
    return int(getattr(settings, "KALMIO_AUTH_THROTTLE_LIMIT", 5))


def auth_throttle_window_seconds() -> int:
    return int(getattr(settings, "KALMIO_AUTH_THROTTLE_WINDOW_SECONDS", 15 * 60))


def throttle_is_expired(throttle: AuthThrottle, *, now=None) -> bool:
    current_time = now or timezone.now()
    elapsed = current_time - throttle.window_started_at
    return elapsed.total_seconds() >= auth_throttle_window_seconds()


def prune_expired_auth_throttles(*, now=None) -> None:
    current_time = now or timezone.now()
    cutoff = current_time - timedelta(seconds=auth_throttle_window_seconds())
    AuthThrottle.objects.filter(window_started_at__lt=cutoff).delete()
