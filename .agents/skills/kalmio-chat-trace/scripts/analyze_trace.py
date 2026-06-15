#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Kalmio agent trace JSONL files.")
    parser.add_argument("--file", default="", help="Trace JSONL path. Defaults to backend/.tmp/agent-traces.jsonl.")
    parser.add_argument("--last-turns", type=int, default=5, help="Number of latest chat turns to summarize.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    trace_file = resolve_trace_file(args.file)
    if trace_file is None:
        raise SystemExit("No encuentro trazas. Esperado: backend/.tmp/agent-traces.jsonl o .tmp/agent-traces.jsonl")

    events = load_events(trace_file)
    turns = latest_turns(events, args.last_turns)
    report = {
        "traceFile": str(trace_file),
        "eventCount": len(events),
        "turns": [summarize_turn(turn_id, turn_events) for turn_id, turn_events in turns],
    }
    report["totals"] = totals(report["turns"])

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print_human_report(report)


def resolve_trace_file(value: str) -> Path | None:
    candidates = []
    if value:
        candidates.append(Path(value))
    env_value = os.environ.get("KALMIO_AGENT_TRACE_FILE")
    if env_value:
        candidates.append(Path(env_value))
    cwd = Path.cwd()
    candidates.extend(
        [
            cwd / "backend" / ".tmp" / "agent-traces.jsonl",
            cwd / ".tmp" / "agent-traces.jsonl",
            cwd.parent / "backend" / ".tmp" / "agent-traces.jsonl",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def load_events(path: Path) -> list[dict[str, Any]]:
    events = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def latest_turns(events: list[dict[str, Any]], count: int) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order = []
    for event in events:
        turn_id = str(event.get("turnId") or "-")
        if turn_id == "-":
            continue
        if turn_id not in grouped:
            order.append(turn_id)
        grouped[turn_id].append(event)
    return [(turn_id, grouped[turn_id]) for turn_id in order[-max(count, 1) :]]


def summarize_turn(turn_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_events = sorted(events, key=lambda item: str(item.get("ts") or ""))
    llm_events = [event for event in sorted_events if event.get("event") == "llm_api_call"]
    tool_events = [event for event in sorted_events if event.get("event") == "internal_tool_call"]
    guardrail_events = [event for event in sorted_events if event.get("event") == "agent_guardrail"]
    turn_events = [event for event in sorted_events if event.get("event") == "agent_turn"]
    final_turn = next((event for event in reversed(turn_events) if event.get("status") != "started"), {})

    usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    cost_usd = 0.0
    cost_basis = set()
    for event in llm_events:
        event_usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        for key in usage:
            usage[key] += int(event_usage.get(key) or 0)
        event_cost = event.get("cost") if isinstance(event.get("cost"), dict) else {}
        cost_usd += float(event_cost.get("totalCostUsd") or 0)
        if event_cost.get("basis"):
            cost_basis.add(str(event_cost["basis"]))

    return {
        "turnId": turn_id,
        "startedAt": sorted_events[0].get("ts") if sorted_events else None,
        "status": final_turn.get("status") or infer_status(sorted_events),
        "provider": first_value(sorted_events, "provider"),
        "model": first_value(sorted_events, "model"),
        "durationMs": final_turn.get("durationMs"),
        "llmCallCount": len(llm_events),
        "toolCallCount": len(tool_events),
        "guardrailCount": len(guardrail_events),
        "usage": {key: value for key, value in usage.items() if value},
        "estimatedCostUsd": round(cost_usd, 8),
        "costBasis": sorted(cost_basis),
        "events": [compact_event(event) for event in sorted_events],
        "warnings": turn_warnings(sorted_events, llm_events, tool_events, guardrail_events, cost_basis),
    }


def infer_status(events: list[dict[str, Any]]) -> str:
    if any(event.get("status") == "error" for event in events):
        return "error"
    return "ok"


def first_value(events: list[dict[str, Any]], key: str) -> Any:
    for event in events:
        if event.get(key):
            return event[key]
    return None


def compact_event(event: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "ts": event.get("ts"),
        "event": event.get("event"),
        "name": event.get("name"),
        "status": event.get("status"),
        "provider": event.get("provider"),
        "model": event.get("model"),
        "durationMs": event.get("durationMs"),
        "usage": event.get("usage"),
        "cost": event.get("cost"),
        "metadata": event.get("metadata"),
        "error": event.get("error"),
    }
    if "request" in event:
        compact["hasRequestPayload"] = True
    if "response" in event:
        compact["hasResponsePayload"] = True
    return {key: value for key, value in compact.items() if value not in (None, {}, [])}


def turn_warnings(
    events: list[dict[str, Any]],
    llm_events: list[dict[str, Any]],
    tool_events: list[dict[str, Any]],
    guardrail_events: list[dict[str, Any]],
    cost_basis: set[str],
) -> list[str]:
    warnings = []
    if any(event.get("status") == "error" for event in llm_events):
        warnings.append("Hay errores en llamadas LLM.")
    if any(event.get("status") == "error" for event in tool_events):
        warnings.append("Hay herramientas internas con error o sin resultados.")
    for event in guardrail_events:
        name = event.get("name") or "guardrail"
        reason = ""
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        if metadata.get("reason"):
            reason = f": {metadata['reason']}"
        warnings.append(f"Guardrail de agente activado ({name}){reason}.")
    if llm_events and not any(event.get("usage") for event in llm_events):
        warnings.append("El proveedor no devolvió usage; no se puede estimar coste.")
    if "cache_breakdown_missing_assumed_cache_miss" in cost_basis:
        warnings.append("Coste estimado asumiendo cache miss porque faltó desglose de caché.")
    if events and not any("request" in event or "response" in event for event in events):
        warnings.append("Payloads no incluidos. Activa KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS=true para ver prompts/args/results.")
    return warnings


def totals(turns: list[dict[str, Any]]) -> dict[str, Any]:
    usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    cost = 0.0
    for turn in turns:
        turn_usage = turn.get("usage") if isinstance(turn.get("usage"), dict) else {}
        for key in usage:
            usage[key] += int(turn_usage.get(key) or 0)
        cost += float(turn.get("estimatedCostUsd") or 0)
    return {
        "turnCount": len(turns),
        "llmCallCount": sum(int(turn.get("llmCallCount") or 0) for turn in turns),
        "toolCallCount": sum(int(turn.get("toolCallCount") or 0) for turn in turns),
        "guardrailCount": sum(int(turn.get("guardrailCount") or 0) for turn in turns),
        "usage": {key: value for key, value in usage.items() if value},
        "estimatedCostUsd": round(cost, 8),
    }


def print_human_report(report: dict[str, Any]) -> None:
    print(f"Trace: {report['traceFile']}")
    print(f"Eventos: {report['eventCount']}")
    totals_data = report["totals"]
    print(
        "Total últimos turnos: "
        f"{totals_data['turnCount']} turnos, "
        f"{totals_data['llmCallCount']} llamadas LLM, "
        f"{totals_data['toolCallCount']} herramientas, "
        f"{totals_data.get('guardrailCount') or 0} guardrails, "
        f"${totals_data['estimatedCostUsd']:.8f} estimados"
    )
    if totals_data.get("usage"):
        print(f"Tokens: {json.dumps(totals_data['usage'], ensure_ascii=False)}")
    print()

    for index, turn in enumerate(report["turns"], start=1):
        print(
            f"Turno {index}: {turn['turnId']} | {turn.get('status')} | "
            f"{turn.get('provider') or '-'} {turn.get('model') or ''} | "
            f"{turn.get('durationMs') or '-'} ms | "
            f"${turn['estimatedCostUsd']:.8f}"
        )
        if turn.get("usage"):
            print(f"  Usage: {json.dumps(turn['usage'], ensure_ascii=False)}")
        if turn.get("warnings"):
            for warning in turn["warnings"]:
                print(f"  Aviso: {warning}")
        for event in turn["events"]:
            print(
                "  - "
                f"{event.get('event')} {event.get('name')} [{event.get('status')}] "
                f"{event.get('durationMs', '-')} ms"
            )
            if event.get("usage"):
                print(f"    usage={json.dumps(event['usage'], ensure_ascii=False)}")
            if event.get("cost"):
                print(f"    cost={json.dumps(event['cost'], ensure_ascii=False)}")
            if event.get("metadata"):
                print(f"    meta={json.dumps(event['metadata'], ensure_ascii=False)}")
            if event.get("error"):
                print(f"    error={event['error']}")
        print()


if __name__ == "__main__":
    main()
