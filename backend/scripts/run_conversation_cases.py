#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.request import HTTPCookieProcessor, Request, build_opener


@dataclass(frozen=True)
class CaseSpec:
    turns: list[str]
    expected_components: set[str] = field(default_factory=set)
    any_components: tuple[set[str], ...] = ()
    expected_tools: set[str] = field(default_factory=set)
    forbidden_tools: set[str] = field(default_factory=set)
    expected_text_any: tuple[str, ...] = ()


def request_json(opener, url: str, method: str = "GET", headers=None, body=None, timeout=180):
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with opener.open(req, timeout=timeout) as response:
        return response.getcode(), json.loads(response.read().decode("utf-8") or "{}")


def cookie_header(opener) -> str:
    parts = []
    for handler in opener.handlers:
        cookiejar = getattr(handler, "cookiejar", None)
        if cookiejar is not None:
            parts.extend(f"{cookie.name}={cookie.value}" for cookie in cookiejar)
    return "; ".join(parts)


def csrf_headers(opener, csrf_token: str) -> dict[str, str]:
    headers = {"X-CSRFToken": csrf_token}
    cookies = cookie_header(opener)
    if cookies:
        headers["Cookie"] = cookies
    return headers


def components_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        update_components = message.get("updateComponents")
        if not isinstance(update_components, dict):
            continue
        for component in update_components.get("components") or []:
            if isinstance(component, dict):
                components.append(component)
    return components


NON_DECISION_COMPONENTS = {"AssistantMessage", "UserMessage", "PreferenceChips"}
ACTION_COMPONENTS = {"ActionButtons"}
ALTERNATIVE_LIST_COMPONENTS = {"StationList", "AlternativeStopsList"}


def latest_turn_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_user_index = -1
    for index, component in enumerate(components):
        if component.get("component") == "UserMessage":
            last_user_index = index
    return components[last_user_index + 1 :]


def density_metrics(components: list[dict[str, Any]]) -> dict[str, Any]:
    latest_components = latest_turn_components(components)
    latest_types = [str(component.get("component")) for component in latest_components]
    card_types = [
        component_type
        for component_type in latest_types
        if component_type not in NON_DECISION_COMPONENTS
    ]
    return {
        "latestTurnComponents": latest_types,
        "latestTurnCardCount": len(card_types),
        "latestTurnActionCount": sum(1 for component_type in card_types if component_type in ACTION_COMPONENTS),
        "latestTurnAlternativeListCount": sum(
            1 for component_type in card_types if component_type in ALTERNATIVE_LIST_COMPONENTS
        ),
        "latestTurnOverOneCard": len(card_types) > 1,
    }


def visible_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(visible_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(visible_text(item) for item in value)
    return ""


def normalize(value: str) -> str:
    substitutions = str.maketrans("áéíóúüñ", "aeiouun")
    return value.lower().translate(substitutions)


def trace_position(trace_file: Path | None) -> int:
    if trace_file is None or not trace_file.exists():
        return 0
    return trace_file.stat().st_size


def read_new_trace_events(trace_file: Path | None, position: int) -> list[dict[str, Any]]:
    if trace_file is None or not trace_file.exists():
        return []
    with trace_file.open("rb") as handle:
        handle.seek(position)
        data = handle.read().decode("utf-8", errors="replace")
    events = []
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def internal_tool_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event") == "internal_tool_call"]


def factual_charger_claim_without_tool(text: str, tools: set[str]) -> bool:
    if tools & {"search_destination_chargers", "plan_route"}:
        return False
    normalized = normalize(text)
    if any(term in normalized for term in ("no he encontrado", "no encontre", "sin resultados", "puedo buscar")):
        return False
    return any(
        term in normalized
        for term in (
            "he encontrado",
            "encontre",
            "te muestro cargadores",
            "cargadores disponibles",
            "estos son los cargadores",
        )
    )


def evaluate_case(case_id: int, spec: CaseSpec, payload: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    components = components_from_payload(payload)
    component_types = {str(component.get("component")) for component in components}
    tools = internal_tool_events(events)
    tool_names = {str(event.get("name")) for event in tools}
    tool_errors = [
        {
            "tool": event.get("name"),
            "status": event.get("status"),
            "metadata": event.get("metadata"),
        }
        for event in tools
        if event.get("status") != "ok" or (isinstance(event.get("metadata"), dict) and event["metadata"].get("ok") is False)
    ]
    text = visible_text(components)

    failures: list[str] = []
    missing_components = spec.expected_components - component_types
    if missing_components:
        failures.append(f"faltan componentes: {sorted(missing_components)}")
    for options in spec.any_components:
        if not (options & component_types):
            failures.append(f"falta algun componente de: {sorted(options)}")
    missing_tools = spec.expected_tools - tool_names
    if missing_tools:
        failures.append(f"faltan herramientas: {sorted(missing_tools)}")
    forbidden_tools = spec.forbidden_tools & tool_names
    if forbidden_tools:
        failures.append(f"herramientas no esperadas: {sorted(forbidden_tools)}")
    if tool_errors:
        failures.append(f"herramientas con error: {tool_errors}")
    if spec.expected_text_any and not any(term in normalize(text) for term in spec.expected_text_any):
        failures.append(f"no aparece texto esperado: {spec.expected_text_any}")
    if factual_charger_claim_without_tool(text, tool_names):
        failures.append("afirma cargadores encontrados/disponibles sin herramienta de busqueda/ruta")

    return {
        "case": case_id,
        "ok": not failures,
        "failures": failures,
        "components": sorted(component_types),
        "tools": sorted(tool_names),
        "density": density_metrics(components),
    }


def run_case(api_base: str, case_id: int, spec: CaseSpec, trace_file: Path | None) -> dict[str, Any]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    status, ready_payload = request_json(opener, f"{api_base}/api/ready", timeout=20)
    if status != 200 or ready_payload.get("status") != "ready":
        return {"case": case_id, "ok": False, "failures": [f"backend no ready: {ready_payload}"]}

    status, csrf_payload = request_json(opener, f"{api_base}/api/auth/csrf", timeout=20)
    csrf_token = csrf_payload.get("csrf_token")
    if status != 200 or not csrf_token:
        return {"case": case_id, "ok": False, "failures": [f"csrf invalido: {csrf_payload}"]}

    request_json(opener, f"{api_base}/api/conversation/messages", headers={"Cookie": cookie_header(opener)}, timeout=20)

    trace_start = trace_position(trace_file)
    started = time.perf_counter()
    payload: dict[str, Any] | None = None
    for turn in spec.turns:
        status, payload = request_json(
            opener,
            f"{api_base}/api/conversation/message",
            method="POST",
            headers=csrf_headers(opener, csrf_token),
            body={"text": turn},
        )
        if status != 200:
            return {"case": case_id, "ok": False, "failures": [f"HTTP {status}: {payload}"]}
        time.sleep(0.05)

    duration_ms = (time.perf_counter() - started) * 1000
    events = read_new_trace_events(trace_file, trace_start)
    return evaluate_case(case_id, spec, payload or {}, events, duration_ms)
