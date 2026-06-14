from __future__ import annotations

import hashlib
from datetime import timedelta
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import AuthThrottle


@dataclass(frozen=True)
class ConversationThrottleResult:
    allowed: bool
    limit: int
    window_seconds: int


def check_conversation_throttle(request) -> ConversationThrottleResult:
    limit = conversation_throttle_limit()
    key = conversation_throttle_key(request)
    throttle = AuthThrottle.objects.filter(key=key).first()
    attempts = 0 if throttle is None or conversation_throttle_is_expired(throttle) else throttle.attempts

    return ConversationThrottleResult(
        allowed=attempts < limit,
        limit=limit,
        window_seconds=conversation_throttle_window_seconds(),
    )


def record_conversation_attempt(request) -> None:
    key = conversation_throttle_key(request)
    now = timezone.now()
    prune_expired_conversation_throttles(now=now)
    with transaction.atomic():
        throttle, created = AuthThrottle.objects.select_for_update().get_or_create(
            key=key,
            defaults={"attempts": 1, "window_started_at": now},
        )
        if created:
            return

        if conversation_throttle_is_expired(throttle, now=now):
            throttle.attempts = 1
            throttle.window_started_at = now
        else:
            throttle.attempts += 1
        throttle.save(update_fields=["attempts", "window_started_at", "updated_at"])


def clear_conversation_throttle(request) -> None:
    AuthThrottle.objects.filter(key=conversation_throttle_key(request)).delete()


def conversation_throttle_key(request) -> str:
    session_id = request.session.session_key or "anonymous"
    identity = f"conversation:{session_id}:{request.META.get('REMOTE_ADDR', 'unknown')}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"kalmio:conversation-throttle:{digest}"


def conversation_throttle_limit() -> int:
    return int(getattr(settings, "KALMIO_ROUTE_CONVERSATION_THROTTLE_LIMIT", 30))


def conversation_throttle_window_seconds() -> int:
    return int(getattr(settings, "KALMIO_ROUTE_CONVERSATION_THROTTLE_WINDOW_SECONDS", 120))


def conversation_throttle_is_expired(throttle: AuthThrottle, *, now=None) -> bool:
    current_time = now or timezone.now()
    elapsed = current_time - throttle.window_started_at
    return elapsed.total_seconds() >= conversation_throttle_window_seconds()


def prune_expired_conversation_throttles(*, now=None) -> None:
    current_time = now or timezone.now()
    cutoff = current_time - timedelta(seconds=conversation_throttle_window_seconds())
    AuthThrottle.objects.filter(window_started_at__lt=cutoff).delete()
