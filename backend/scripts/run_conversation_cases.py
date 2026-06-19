#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
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


CASE_SPECS: dict[int, CaseSpec] = {
    10: CaseSpec(
        turns=["Voy de Zaragoza a Barcelona y quiero llegar con al menos 25%"],
        any_components=({"StationList", "StationDetailCard"},),
        expected_tools={"plan_route"},
    ),
    11: CaseSpec(
        turns=["Quiero la ruta mas barata, pero sin bajar del 20%"],
        any_components=({"ClarifyingQuestionCard", "AssistantMessage"},),
        forbidden_tools={"plan_route", "search_destination_chargers"},
        expected_text_any=("origen", "destino", "vehiculo", "bateria", "consumo"),
    ),
    12: CaseSpec(
        turns=["Evita cargadores caros si hay alternativas razonables"],
        expected_components={"AssistantMessage"},
        forbidden_tools={"plan_route", "search_destination_chargers"},
    ),
    13: CaseSpec(
        turns=["Me conviene cargar antes de salir o al llegar?"],
        any_components=({"ClarifyingQuestionCard", "AssistantMessage"},),
        forbidden_tools={"plan_route", "search_destination_chargers"},
        expected_text_any=("origen", "destino", "bateria", "vehiculo", "consumo"),
    ),
    14: CaseSpec(
        turns=["Quiero cargar lo justo para llegar, sin pagar de mas"],
        any_components=({"ClarifyingQuestionCard", "AssistantMessage"},),
        forbidden_tools={"plan_route", "search_destination_chargers"},
        expected_text_any=("origen", "destino", "bateria", "vehiculo", "consumo"),
    ),
    15: CaseSpec(
        turns=["Compara ruta rapida contra ruta barata"],
        any_components=({"ClarifyingQuestionCard", "AssistantMessage"},),
        forbidden_tools={"plan_route", "search_destination_chargers"},
        expected_text_any=("origen", "destino"),
    ),
    16: CaseSpec(
        turns=["Me voy 3 dias a Cordoba y me quedo en el hotel Melia"],
        expected_components={"PlaceDetailCard"},
        expected_text_any=("aproxim", "referencia", "hotel", "zona", "direccion"),
    ),
    17: CaseSpec(
        turns=["Voy el finde a Granada y duermo cerca de la Alhambra"],
        expected_components={"PlaceDetailCard"},
        any_components=({"StationList", "StationDetailCard"},),
        expected_tools={"search_destination_chargers"},
    ),
    18: CaseSpec(
        turns=["Voy a un hotel sin cargador, necesito cargar durante la estancia", "En Valencia centro"],
        expected_components={"PlaceDetailCard"},
        any_components=({"StationList", "StationDetailCard"},),
        expected_tools={"search_destination_chargers"},
    ),
    19: CaseSpec(
        turns=["Voy una semana a Cadiz y necesito cargar durante la estancia"],
        expected_components={"PlaceDetailCard"},
        any_components=({"StationList", "StationDetailCard"},),
        expected_tools={"search_destination_chargers"},
    ),
    20: CaseSpec(
        turns=["Voy a Cordoba el viernes y vuelvo el domingo, donde cargo?"],
        expected_components={"ClarifyingQuestionCard"},
        forbidden_tools={"plan_route", "search_destination_chargers"},
        expected_text_any=("origen", "desde donde", "sales", "salida"),
    ),
}


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

    events = read_new_trace_events(trace_file, trace_start)
    return evaluate_case(case_id, spec, payload or {}, events)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Kalmio conversation acceptance cases against a live backend.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--from", dest="case_from", type=int, default=10)
    parser.add_argument("--to", dest="case_to", type=int, default=20)
    parser.add_argument("--trace-file", default="backend/.tmp/agent-traces.jsonl")
    parser.add_argument("--json", action="store_true", help="Print only machine-readable JSON.")
    args = parser.parse_args()

    api_base = args.api_base.rstrip("/")
    trace_file = Path(args.trace_file) if args.trace_file else None
    case_ids = [case_id for case_id in range(args.case_from, args.case_to + 1) if case_id in CASE_SPECS]
    missing = sorted(set(range(args.case_from, args.case_to + 1)) - set(case_ids))
    if missing:
        print(f"Casos sin spec en este runner: {missing}", file=sys.stderr)
        return 2

    results = []
    for case_id in case_ids:
        try:
            result = run_case(api_base, case_id, CASE_SPECS[case_id], trace_file)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            result = {"case": case_id, "ok": False, "failures": [f"HTTP {exc.code}: {detail[:500]}"]}
        except Exception as exc:
            result = {"case": case_id, "ok": False, "failures": [repr(exc)]}
        results.append(result)
        if not args.json:
            status = "PASS" if result["ok"] else "FAIL"
            print(f"{status} case {case_id}: components={result.get('components', [])} tools={result.get('tools', [])}")
            for failure in result.get("failures", []):
                print(f"  - {failure}")

    summary = {"total": len(results), "passed": sum(1 for item in results if item["ok"]), "results": results}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif summary["passed"] != summary["total"]:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
