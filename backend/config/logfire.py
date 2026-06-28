from __future__ import annotations

import os
from typing import Any


def configure_logfire(*, service_name: str, environment: str, local_default: bool) -> Any | None:
    enabled = os.getenv("KALMIO_LOGFIRE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return None

    try:
        import logfire
    except ImportError:
        return None

    token = os.getenv("LOGFIRE_TOKEN") or os.getenv("KALMIO_LOGFIRE_TOKEN") or None
    send_to_logfire = os.getenv("KALMIO_LOGFIRE_SEND_TO_LOGFIRE", "").strip().lower()
    if send_to_logfire in {"1", "true", "yes", "on"}:
        send: bool | str | None = True
    elif send_to_logfire in {"0", "false", "no", "off"}:
        send = False
    else:
        send = "if-token-present"

    instance = logfire.configure(
        service_name=service_name,
        environment=environment,
        token=token,
        send_to_logfire=send,
        local=False,
        console=False,
    )
    if os.getenv("KALMIO_LOGFIRE_INSTRUMENT_DJANGO", "true").strip().lower() in {"1", "true", "yes", "on"}:
        logfire.instrument_django(capture_headers=False)
    if os.getenv("KALMIO_LOGFIRE_INSTRUMENT_HTTPX", "true").strip().lower() in {"1", "true", "yes", "on"}:
        logfire.instrument_httpx(capture_all=False)
    return instance
