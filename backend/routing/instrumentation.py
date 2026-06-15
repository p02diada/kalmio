from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from config.middleware import request_id_var
from django.conf import settings


agent_turn_id_var: ContextVar[str] = ContextVar("agent_turn_id", default="-")
logger = logging.getLogger("kalmio.agent_trace")

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "csrf",
    "csrfmiddlewaretoken",
    "password",
    "secret",
    "token",
}


@contextmanager
def agent_trace_turn(provider: str) -> Iterator[str]:
    turn_id = uuid4().hex
    token = agent_turn_id_var.set(turn_id)
    start = time.perf_counter()
    record_trace_event(
        event="agent_turn",
        name="conversation",
        status="started",
        provider=provider,
    )
    try:
        yield turn_id
    except Exception as exc:
        record_trace_event(
            event="agent_turn",
            name="conversation",
            status="error",
            provider=provider,
            duration_ms=elapsed_ms(start),
            error=str(exc),
        )
        raise
    else:
        record_trace_event(
            event="agent_turn",
            name="conversation",
            status="ok",
            provider=provider,
            duration_ms=elapsed_ms(start),
        )
    finally:
        agent_turn_id_var.reset(token)


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def record_trace_event(
    *,
    event: str,
    name: str,
    status: str,
    provider: str | None = None,
    model: str | None = None,
    duration_ms: float | None = None,
    usage: dict[str, Any] | None = None,
    cost: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    request_payload: Any | None = None,
    response_payload: Any | None = None,
    error: str | None = None,
) -> None:
    if not getattr(settings, "KALMIO_AGENT_TRACE_ENABLED", False):
        return

    payload: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "event": event,
        "name": name,
        "status": status,
        "requestId": request_id_var.get(),
        "turnId": agent_turn_id_var.get(),
    }
    optional = {
        "provider": provider,
        "model": model,
        "durationMs": duration_ms,
        "usage": usage,
        "cost": cost,
        "metadata": metadata,
        "error": sanitize_error(error),
    }
    payload.update({key: value for key, value in optional.items() if value not in (None, {}, [])})

    if getattr(settings, "KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS", False):
        if request_payload is not None:
            payload["request"] = sanitize_payload(request_payload)
        if response_payload is not None:
            payload["response"] = sanitize_payload(response_payload)

    message = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    logger.info(message)
    write_trace_file(message)


def write_trace_file(message: str) -> None:
    trace_file = str(getattr(settings, "KALMIO_AGENT_TRACE_FILE", "") or "").strip()
    if not trace_file:
        return
    path = Path(trace_file)
    if not path.is_absolute():
        path = settings.BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(message)
        file.write("\n")


def sanitize_payload(value: Any) -> Any:
    plain = to_plain(value)
    sanitized = sanitize_value(plain)
    return truncate_value(sanitized, getattr(settings, "KALMIO_AGENT_TRACE_MAX_PAYLOAD_CHARS", 12000))


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            if key_text.lower().replace("-", "_") in SENSITIVE_KEYS:
                cleaned[key_text] = "[redacted]"
            else:
                cleaned[key_text] = sanitize_value(nested)
        return cleaned
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    return value


def truncate_value(value: Any, max_chars: int) -> Any:
    if max_chars <= 0:
        return value
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(encoded) <= max_chars:
        return value
    return {
        "_truncated": True,
        "chars": len(encoded),
        "preview": encoded[:max_chars],
    }


def sanitize_error(error: str | None) -> str | None:
    if not error:
        return None
    text = str(error)
    api_key = str(getattr(settings, "KALMIO_DEEPSEEK_API_KEY", "") or "")
    if api_key:
        text = text.replace(api_key, "[redacted]")
    return text


def to_plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): to_plain(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    if hasattr(value, "model_dump"):
        return to_plain(value.model_dump())
    if hasattr(value, "dict"):
        return to_plain(value.dict())
    if hasattr(value, "__dict__"):
        public = {
            key: nested
            for key, nested in vars(value).items()
            if not key.startswith("_") and not callable(nested)
        }
        if public:
            return to_plain(public)
    return str(value)


def normalize_usage(usage: Any) -> dict[str, Any]:
    data = to_plain(usage)
    if not isinstance(data, dict):
        return {}

    input_tokens = first_int(data, "prompt_tokens", "input_tokens")
    output_tokens = first_int(data, "completion_tokens", "output_tokens")
    total_tokens = first_int(data, "total_tokens")
    cache_hit_tokens = first_int(data, "prompt_cache_hit_tokens", "cache_hit_tokens", "input_cache_hit_tokens")
    cache_miss_tokens = first_int(data, "prompt_cache_miss_tokens", "cache_miss_tokens", "input_cache_miss_tokens")

    normalized = {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "cacheHitInputTokens": cache_hit_tokens,
        "cacheMissInputTokens": cache_miss_tokens,
    }
    return {key: value for key, value in normalized.items() if value is not None}


def first_int(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def estimate_deepseek_cost(usage: dict[str, Any]) -> dict[str, Any] | None:
    input_tokens = usage.get("inputTokens")
    output_tokens = usage.get("outputTokens")
    if input_tokens is None and output_tokens is None:
        return None

    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    cache_hit_tokens = usage.get("cacheHitInputTokens")
    cache_miss_tokens = usage.get("cacheMissInputTokens")

    hit_price = float(getattr(settings, "KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_HIT_PER_MILLION_USD", 0))
    miss_price = float(getattr(settings, "KALMIO_DEEPSEEK_PRICE_INPUT_CACHE_MISS_PER_MILLION_USD", 0))
    output_price = float(getattr(settings, "KALMIO_DEEPSEEK_PRICE_OUTPUT_PER_MILLION_USD", 0))

    if cache_hit_tokens is not None or cache_miss_tokens is not None:
        hit_tokens = int(cache_hit_tokens or 0)
        miss_tokens = int(cache_miss_tokens) if cache_miss_tokens is not None else max(input_tokens - hit_tokens, 0)
        basis = "provider_cache_breakdown"
    else:
        hit_tokens = 0
        miss_tokens = input_tokens
        basis = "cache_breakdown_missing_assumed_cache_miss"

    input_cost = ((hit_tokens * hit_price) + (miss_tokens * miss_price)) / 1_000_000
    output_cost = (output_tokens * output_price) / 1_000_000
    total = input_cost + output_cost
    return {
        "currency": "USD",
        "estimated": True,
        "basis": basis,
        "inputCostUsd": round(input_cost, 8),
        "outputCostUsd": round(output_cost, 8),
        "totalCostUsd": round(total, 8),
        "pricesPerMillionTokens": {
            "inputCacheHit": hit_price,
            "inputCacheMiss": miss_price,
            "output": output_price,
        },
    }


def tool_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "ok": result.get("ok"),
        "tool": result.get("tool"),
        "error": result.get("error"),
    }
    stops = result.get("stops")
    if isinstance(stops, list):
        summary["stopCount"] = len(stops)
    alternatives = result.get("alternatives")
    if isinstance(alternatives, list):
        summary["alternativeCount"] = len(alternatives)
    if result.get("planningLevel"):
        summary["planningLevel"] = result.get("planningLevel")
    return {key: value for key, value in summary.items() if value is not None}
