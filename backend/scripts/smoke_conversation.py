#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from urllib.request import build_opener, HTTPCookieProcessor

from urllib.request import Request


def request_json(opener, url: str, method: str, headers=None, body=None):
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with opener.open(req, timeout=10) as response:
        data = response.read().decode("utf-8")
        return response.getcode(), json.loads(data or "{}")


def require(condition: bool, message: str, detail: object | None = None):
    if not condition:
        if detail:
            print(f"{message}: {detail}")
        raise SystemExit(1)


def cookie_value(opener, name: str) -> str | None:
    for handler in opener.handlers:
        cookiejar = getattr(handler, "cookiejar", None)
        if cookiejar is None:
            continue
        for cookie in cookiejar:
            if cookie.name == name:
                return cookie.value
    return None


def cookie_header(opener) -> str | None:
    parts = []
    for handler in opener.handlers:
        cookiejar = getattr(handler, "cookiejar", None)
        if cookiejar is None:
            continue
        for cookie in cookiejar:
            parts.append(f"{cookie.name}={cookie.value}")
    return "; ".join(parts) if parts else None


def cookie_headers(opener) -> dict[str, str] | None:
    cookies = cookie_header(opener)
    return {"Cookie": cookies} if cookies else None


def csrf_request_headers(opener, csrf_token: str) -> dict[str, str]:
    headers = {"X-CSRFToken": csrf_token}
    cookies = cookie_header(opener)
    if cookies:
        headers["Cookie"] = cookies
    return headers


def components_from_payload(payload: dict) -> list[dict]:
    messages = payload.get("messages")
    require(isinstance(messages, list), "Respuesta sin lista de mensajes A2UI", payload)

    components: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        update_components = message.get("updateComponents")
        if not isinstance(update_components, dict):
            continue
        message_components = update_components.get("components")
        if isinstance(message_components, list):
            components.extend(component for component in message_components if isinstance(component, dict))
    return components


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke check for anonymous conversation flow.")
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="Backend API base URL.",
    )
    args = parser.parse_args()

    api_base = args.api_base.rstrip("/")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))

    print("==> comprobando /api/ready")
    try:
        status, ready_payload = request_json(opener, f"{api_base}/api/ready", method="GET")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        raise SystemExit(f"Readiness falló (status {exc.code}): {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se pudo conectar con /api/ready: {exc}")

    require(status == 200, "Readiness no disponible", status)
    require(ready_payload.get("status") == "ready", "Backend no ready", ready_payload.get("status"))

    print("==> obteniendo CSRF")
    try:
        status, csrf_payload = request_json(opener, f"{api_base}/api/auth/csrf", method="GET")
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se pudo obtener CSRF: {exc}")

    require(status == 200, "Endpoint CSRF falla", status)
    csrf_token = csrf_payload.get("csrf_token")
    require(isinstance(csrf_token, str) and csrf_token, "Token CSRF faltante")
    require(cookie_value(opener, "csrftoken") is not None, "Cookie CSRF faltante")

    print("==> leyendo mensajes iniciales A2UI")
    try:
        status, initial_payload = request_json(
            opener,
            f"{api_base}/api/conversation/messages",
            method="GET",
            headers=cookie_headers(opener),
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        raise SystemExit(f"No se pudieron leer mensajes iniciales (status {exc.code}): {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se pudieron leer mensajes iniciales: {exc}")

    require(status == 200, "Mensajes iniciales no válidos", status)
    initial_components = components_from_payload(initial_payload)
    require(initial_components, "Sin componentes A2UI iniciales")
    require(
        initial_components[0].get("component") == "AssistantMessage",
        "Primer componente A2UI inesperado",
        initial_components[0],
    )

    print("==> enviando intención al agente A2UI")
    try:
        status, message_payload = request_json(
            opener,
            f"{api_base}/api/conversation/message",
            method="POST",
            headers=csrf_request_headers(opener, csrf_token),
            body={"text": "Quiero ver cargadores cerca de un hotel en Valencia"},
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        raise SystemExit(f"Conversación falló (status {exc.code}): {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se pudo crear conversación: {exc}")

    require(status == 200, "Conversación A2UI no válida", status)
    components = components_from_payload(message_payload)
    component_types = {component.get("component") for component in components if isinstance(component, dict)}
    require("UserMessage" in component_types, "La respuesta no incluye eco de usuario", component_types)
    require(
        "PlaceDetailCard" in component_types or "ClarifyingQuestionCard" in component_types,
        "La respuesta no incluye bloque de lugar ni aclaración",
        component_types,
    )

    print(
        "Conversación A2UI creada:",
        ", ".join(sorted(str(component_type) for component_type in component_types)),
    )

    print("==> validando mensajes guardados en sesión")
    try:
        status, active_payload = request_json(
            opener,
            f"{api_base}/api/conversation/messages",
            method="GET",
            headers=cookie_headers(opener),
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        raise SystemExit(f"No se pudieron leer mensajes guardados (status {exc.code}): {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se pudieron leer mensajes guardados: {exc}")

    require(status == 200, "Lectura de conversación A2UI falla", status)
    active_components = components_from_payload(active_payload)
    require(active_components, "Conversación activa sin componentes A2UI", active_payload)
    require(len(active_components) >= len(components), "La sesión no conservó los componentes A2UI")

    print("==> borrando conversación")
    try:
        status, _ = request_json(
            opener,
            f"{api_base}/api/conversation",
            method="DELETE",
            headers=csrf_request_headers(opener, csrf_token),
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        raise SystemExit(f"No se pudo eliminar conversación (status {exc.code}): {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se pudo eliminar conversación: {exc}")

    require(status == 200, "El borrado de conversación no devolvió 200", status)

    print("Smoke de conversación OK")


if __name__ == "__main__":
    main()
