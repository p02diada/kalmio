#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_summary(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: expected a benchmark summary object.")
    return payload


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def aggregate(summary: dict[str, Any]) -> dict[str, Any]:
    value = summary.get("aggregate")
    return value if isinstance(value, dict) else {}


def total_cost(summary: dict[str, Any]) -> float:
    cost = aggregate(summary).get("cost")
    if not isinstance(cost, dict):
        return 0.0
    return number(cost.get("totalCostUsd"))


def aggregate_metric(summary: dict[str, Any], key: str) -> float:
    return number(aggregate(summary).get(key))


def aggregate_usage(summary: dict[str, Any], key: str) -> float:
    usage = aggregate(summary).get("usage")
    if not isinstance(usage, dict):
        return 0.0
    return number(usage.get(key))


def results_by_case(summary: dict[str, Any]) -> dict[int, dict[str, Any]]:
    results = summary.get("results")
    if not isinstance(results, list):
        return {}
    by_case: dict[int, dict[str, Any]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            case_id = int(item.get("case"))
        except (TypeError, ValueError):
            continue
        by_case[case_id] = item
    return by_case


def pass_rate(summary: dict[str, Any]) -> float:
    total = number(summary.get("total"))
    if total <= 0:
        return 0.0
    return number(summary.get("passed")) / total


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def delta(candidate: float, baseline: float) -> float:
    return round(candidate - baseline, 8)


def changed_cases(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    base_cases = results_by_case(baseline)
    candidate_cases = results_by_case(candidate)
    fixed: list[dict[str, Any]] = []
    regressed: list[dict[str, Any]] = []
    changed_failures: list[dict[str, Any]] = []

    for case_id in sorted(set(base_cases) | set(candidate_cases)):
        base = base_cases.get(case_id, {})
        cand = candidate_cases.get(case_id, {})
        base_ok = bool(base.get("ok"))
        cand_ok = bool(cand.get("ok"))
        if not base_ok and cand_ok:
            fixed.append({"case": case_id})
        elif base_ok and not cand_ok:
            regressed.append({"case": case_id, "failures": cand.get("failures") or []})
        elif not base_ok and not cand_ok and (base.get("failures") or []) != (cand.get("failures") or []):
            changed_failures.append(
                {
                    "case": case_id,
                    "baselineFailures": base.get("failures") or [],
                    "candidateFailures": cand.get("failures") or [],
                }
            )
    return {"fixed": fixed, "regressed": regressed, "changedFailures": changed_failures}


def recommendation(baseline: dict[str, Any], candidate: dict[str, Any], changes: dict[str, list[dict[str, Any]]]) -> str:
    base_pass = pass_rate(baseline)
    cand_pass = pass_rate(candidate)
    regressions = len(changes["regressed"])
    repair_delta = delta(aggregate_metric(candidate, "repairCount"), aggregate_metric(baseline, "repairCount"))
    fallback_delta = delta(aggregate_metric(candidate, "fallbackCount"), aggregate_metric(baseline, "fallbackCount"))
    cost_delta = delta(total_cost(candidate), total_cost(baseline))

    if regressions or cand_pass < base_pass or fallback_delta > 0:
        return "descartar_o_iterar"
    if cand_pass > base_pass:
        return "adoptar_si_revision_manual_confirma_calidad"
    if repair_delta <= 0 and cost_delta <= 0:
        return "adoptar_si_reduce_complejidad"
    return "iterar"


def build_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    changes = changed_cases(baseline, candidate)
    return {
        "baseline": {
            "label": baseline.get("label"),
            "passed": baseline.get("passed"),
            "total": baseline.get("total"),
            "passRate": pct(pass_rate(baseline)),
        },
        "candidate": {
            "label": candidate.get("label"),
            "passed": candidate.get("passed"),
            "total": candidate.get("total"),
            "passRate": pct(pass_rate(candidate)),
        },
        "delta": {
            "passed": delta(number(candidate.get("passed")), number(baseline.get("passed"))),
            "passRate": pct(delta(pass_rate(candidate), pass_rate(baseline))),
            "totalCostUsd": delta(total_cost(candidate), total_cost(baseline)),
            "durationMs": delta(aggregate_metric(candidate, "durationMs"), aggregate_metric(baseline, "durationMs")),
            "llmCallCount": delta(
                aggregate_metric(candidate, "llmCallCount"),
                aggregate_metric(baseline, "llmCallCount"),
            ),
            "toolCallCount": delta(
                aggregate_metric(candidate, "toolCallCount"),
                aggregate_metric(baseline, "toolCallCount"),
            ),
            "repairCount": delta(
                aggregate_metric(candidate, "repairCount"),
                aggregate_metric(baseline, "repairCount"),
            ),
            "fallbackCount": delta(
                aggregate_metric(candidate, "fallbackCount"),
                aggregate_metric(baseline, "fallbackCount"),
            ),
            "inputTokens": delta(
                aggregate_usage(candidate, "inputTokens"),
                aggregate_usage(baseline, "inputTokens"),
            ),
            "outputTokens": delta(
                aggregate_usage(candidate, "outputTokens"),
                aggregate_usage(baseline, "outputTokens"),
            ),
        },
        "caseChanges": changes,
        "recommendation": recommendation(baseline, candidate, changes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two Kalmio conversation benchmark JSON files.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, help="Optional path to write comparison JSON.")
    args = parser.parse_args()

    comparison = build_comparison(load_summary(args.baseline), load_summary(args.candidate))
    text = json.dumps(comparison, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
