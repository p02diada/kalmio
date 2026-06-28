#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


RECOMMENDATION_COPY = {
    "adoptar_si_reduce_complejidad": (
        "Adoptar Pydantic AI es razonable si la revisión del diff confirma una reducción real de complejidad."
    ),
    "adoptar_si_revision_manual_confirma_calidad": (
        "Pydantic AI mejora la tasa automática; adoptar solo tras revisar manualmente calidad y copy de los casos cambiados."
    ),
    "iterar": (
        "Iterar antes de adoptar: no hay regresión automática, pero coste, latencia o reparaciones no mejoran claramente."
    ),
    "descartar_o_iterar": (
        "No adoptar en este estado: hay regresiones, menor pass rate o más fallbacks. Iterar solo si los fallos son acotados."
    ),
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path}: expected JSON object.")
    return payload


def value(data: dict[str, Any], *path: str, default: Any = "") -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def metric_row(label: str, key: str, comparison: dict[str, Any]) -> str:
    delta = value(comparison, "delta", key, default="")
    return f"| {label} | `{delta}` |"


def case_list(items: list[dict[str, Any]], *, include_failures: bool = False) -> str:
    if not items:
        return "- Ninguno."
    lines = []
    for item in items:
        case = item.get("case")
        if include_failures:
            failures = item.get("failures") or item.get("candidateFailures") or []
            suffix = f": {failures}" if failures else ""
            lines.append(f"- Caso {case}{suffix}")
        else:
            lines.append(f"- Caso {case}")
    return "\n".join(lines)


def render_report(comparison: dict[str, Any]) -> str:
    recommendation = str(comparison.get("recommendation") or "iterar")
    recommendation_text = RECOMMENDATION_COPY.get(recommendation, "Revisar manualmente la comparación antes de decidir.")
    fixed = value(comparison, "caseChanges", "fixed", default=[])
    regressed = value(comparison, "caseChanges", "regressed", default=[])
    changed = value(comparison, "caseChanges", "changedFailures", default=[])

    return "\n".join(
        [
            "# Pydantic AI DeepSeek Benchmark Report",
            "",
            "## Summary",
            "",
            f"- Baseline: `{value(comparison, 'baseline', 'label')}` "
            f"({value(comparison, 'baseline', 'passed')}/{value(comparison, 'baseline', 'total')}, "
            f"{value(comparison, 'baseline', 'passRate')})",
            f"- Candidate: `{value(comparison, 'candidate', 'label')}` "
            f"({value(comparison, 'candidate', 'passed')}/{value(comparison, 'candidate', 'total')}, "
            f"{value(comparison, 'candidate', 'passRate')})",
            f"- Recommendation: `{recommendation}`",
            f"- Interpretation: {recommendation_text}",
            "",
            "## Deltas",
            "",
            "| Metric | Candidate minus baseline |",
            "| --- | ---: |",
            metric_row("Passed cases", "passed", comparison),
            metric_row("Pass rate", "passRate", comparison),
            metric_row("Estimated cost USD", "totalCostUsd", comparison),
            metric_row("Duration ms", "durationMs", comparison),
            metric_row("LLM calls", "llmCallCount", comparison),
            metric_row("Tool calls", "toolCallCount", comparison),
            metric_row("A2UI repairs", "repairCount", comparison),
            metric_row("Fallbacks", "fallbackCount", comparison),
            metric_row("Input tokens", "inputTokens", comparison),
            metric_row("Output tokens", "outputTokens", comparison),
            "",
            "## Case Changes",
            "",
            "### Fixed",
            "",
            case_list(fixed),
            "",
            "### Regressed",
            "",
            case_list(regressed, include_failures=True),
            "",
            "### Changed Failures",
            "",
            case_list(changed, include_failures=True),
            "",
            "## Decision Notes",
            "",
            "- Treat this report as an automated gate, not the final product decision.",
            "- Manually inspect any fixed, regressed, or changed-failure cases before adopting Pydantic AI.",
            "- Do not adopt if the candidate invents charger facts, coordinates, availability, prices, route metrics, or vehicle state.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Markdown report from a benchmark comparison JSON.")
    parser.add_argument("comparison", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = render_report(load_json(args.comparison))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
