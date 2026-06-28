#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SUM_METRICS = (
    "durationMs",
    "llmCallCount",
    "toolCallCount",
    "repairCount",
    "fallbackCount",
)
USAGE_METRICS = (
    "inputTokens",
    "outputTokens",
    "totalTokens",
    "cacheHitInputTokens",
    "cacheMissInputTokens",
)


def load_summary(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: expected a benchmark summary object.")
    return payload


def number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def int_or_float(value: float) -> int | float:
    if value.is_integer():
        return int(value)
    return round(value, 2)


def combine(paths: list[Path], label: str | None = None) -> dict[str, Any]:
    summaries = [load_summary(path) for path in paths]
    results: list[dict[str, Any]] = []
    aggregate: dict[str, Any] = {
        "usage": {key: 0 for key in USAGE_METRICS},
        "cost": {"currency": "USD", "estimated": True, "totalCostUsd": 0.0},
    }
    for metric in SUM_METRICS:
        aggregate[metric] = 0.0

    for summary in summaries:
        for item in summary.get("results") or []:
            if isinstance(item, dict):
                results.append(item)

        chunk_aggregate = summary.get("aggregate") if isinstance(summary.get("aggregate"), dict) else {}
        for metric in SUM_METRICS:
            aggregate[metric] += number(chunk_aggregate.get(metric))

        usage = chunk_aggregate.get("usage") if isinstance(chunk_aggregate.get("usage"), dict) else {}
        for metric in USAGE_METRICS:
            aggregate["usage"][metric] += int(number(usage.get(metric)))

        cost = chunk_aggregate.get("cost") if isinstance(chunk_aggregate.get("cost"), dict) else {}
        aggregate["cost"]["totalCostUsd"] += number(cost.get("totalCostUsd"))
        if cost.get("estimated") is False:
            aggregate["cost"]["estimated"] = False

    results.sort(key=lambda item: int(item.get("case") or 0))
    passed = sum(1 for item in results if item.get("ok") is True)
    total = len(results)

    for metric in SUM_METRICS:
        aggregate[metric] = int_or_float(round(float(aggregate[metric]), 2))
    aggregate["cost"]["totalCostUsd"] = round(float(aggregate["cost"]["totalCostUsd"]), 8)

    first = summaries[0] if summaries else {}
    return {
        "label": label or first.get("label"),
        "apiBase": "combined",
        "traceFile": None,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "aggregate": aggregate,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine Kalmio conversation benchmark JSON chunks.")
    parser.add_argument("chunks", nargs="+", type=Path)
    parser.add_argument("--label")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary = combine(args.chunks, args.label)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
