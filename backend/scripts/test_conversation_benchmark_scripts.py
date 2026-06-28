from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parent


def load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def benchmark_summary(
    *,
    label: str,
    passed: int,
    repair_count: int = 0,
    fallback_count: int = 0,
    total_cost_usd: float = 0.0,
    results: list[dict] | None = None,
) -> dict:
    total = 3
    return {
        "label": label,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "aggregate": {
            "usage": {"inputTokens": 1_000, "outputTokens": 200},
            "cost": {"currency": "USD", "estimated": True, "totalCostUsd": total_cost_usd},
            "durationMs": 1_500,
            "llmCallCount": 4,
            "toolCallCount": 2,
            "repairCount": repair_count,
            "fallbackCount": fallback_count,
        },
        "results": results
        or [
            {"case": 1, "ok": True, "failures": []},
            {"case": 2, "ok": True, "failures": []},
            {"case": 3, "ok": passed == 3, "failures": [] if passed == 3 else ["fallo"]},
        ],
    }


def test_compare_benchmark_flags_regressions():
    compare = load_script("compare_conversation_benchmarks")

    baseline = benchmark_summary(label="deepseek-current", passed=3, repair_count=0, total_cost_usd=0.01)
    candidate = benchmark_summary(
        label="pydantic-ai-deepseek",
        passed=2,
        repair_count=1,
        total_cost_usd=0.02,
    )

    comparison = compare.build_comparison(baseline, candidate)

    assert comparison["baseline"]["passRate"] == "100.0%"
    assert comparison["candidate"]["passRate"] == "66.7%"
    assert comparison["delta"]["passed"] == -1
    assert comparison["delta"]["repairCount"] == 1
    assert comparison["caseChanges"]["regressed"] == [{"case": 3, "failures": ["fallo"]}]
    assert comparison["recommendation"] == "descartar_o_iterar"


def test_compare_benchmark_recommends_adoption_when_candidate_preserves_quality_and_reduces_cost():
    compare = load_script("compare_conversation_benchmarks")

    baseline = benchmark_summary(label="deepseek-current", passed=3, repair_count=2, total_cost_usd=0.02)
    candidate = benchmark_summary(label="pydantic-ai-deepseek", passed=3, repair_count=1, total_cost_usd=0.01)

    comparison = compare.build_comparison(baseline, candidate)

    assert comparison["caseChanges"]["regressed"] == []
    assert comparison["delta"]["totalCostUsd"] == -0.01
    assert comparison["recommendation"] == "adoptar_si_reduce_complejidad"


def test_compare_cli_writes_output_file(tmp_path, capsys):
    compare = load_script("compare_conversation_benchmarks")
    baseline_path = tmp_path / "deepseek-current.json"
    candidate_path = tmp_path / "pydantic-ai-deepseek.json"
    output_path = tmp_path / "comparison.json"
    baseline_path.write_text(
        json.dumps(benchmark_summary(label="deepseek-current", passed=3)),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(benchmark_summary(label="pydantic-ai-deepseek", passed=3)),
        encoding="utf-8",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "compare_conversation_benchmarks.py",
                str(baseline_path),
                str(candidate_path),
                "--output",
                str(output_path),
            ],
        )
        assert compare.main() == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert payload["candidate"]["label"] == "pydantic-ai-deepseek"
    assert '"recommendation"' in captured.out


def test_combine_benchmark_chunks_recalculates_totals(tmp_path):
    combine = load_script("combine_conversation_benchmark_chunks")
    first = benchmark_summary(
        label="deepseek-current",
        passed=2,
        total_cost_usd=0.01,
        results=[
            {"case": 1, "ok": True, "failures": []},
            {"case": 2, "ok": False, "failures": ["fallo"]},
        ],
    )
    first["total"] = 2
    first["passed"] = 1
    first["failed"] = 1
    second = benchmark_summary(
        label="deepseek-current",
        passed=2,
        total_cost_usd=0.02,
        results=[
            {"case": 3, "ok": True, "failures": []},
            {"case": 4, "ok": True, "failures": []},
        ],
    )
    second["total"] = 2
    second["passed"] = 2
    second["failed"] = 0
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(first), encoding="utf-8")
    second_path.write_text(json.dumps(second), encoding="utf-8")

    summary = combine.combine([first_path, second_path], "combined")

    assert summary["label"] == "combined"
    assert summary["total"] == 4
    assert summary["passed"] == 3
    assert summary["failed"] == 1
    assert summary["aggregate"]["cost"]["totalCostUsd"] == 0.03
    assert summary["aggregate"]["llmCallCount"] == 8
    assert [item["case"] for item in summary["results"]] == [1, 2, 3, 4]


def test_conversation_evals_builds_dataset_and_scores_flexible_ui_family():
    evals = load_script("run_conversation_evals")
    dataset = evals.build_dataset([103], specs=evals.OUTCOME_CASE_SPECS)
    output = {
        "case": 103,
        "ok": False,
        "failures": ["faltan componentes: ['RouteCorridorCard']"],
        "components": ["AssistantMessage", "StationPreviewCard", "ActionButtons", "UserMessage"],
        "tools": ["plan_route"],
        "visibleText": "No puedo validar consumo exacto con tu perfil, pero te propongo una parada.",
        "metrics": {
            "durationMs": 1000,
            "llmCallCount": 2,
            "toolCallCount": 1,
            "repairCount": 0,
            "fallbackCount": 0,
            "llmErrorCount": 0,
            "toolErrorCount": 0,
            "cost": {"totalCostUsd": 0.001},
        },
    }

    report = dataset.evaluate_sync(lambda _inputs: output, progress=False)
    summary = evals.report_to_dict(report)

    assert summary["assertionSummary"]["case_acceptance"]["passed"] == 0
    assert summary["assertionSummary"]["ui_family_pass"]["passed"] == 1
    assert summary["assertionSummary"]["tool_policy_pass"]["passed"] == 1
    assert summary["assertionSummary"]["task_success"]["passed"] == 1
    assert summary["scoreAverages"]["estimated_cost_usd"] == 0.001


def test_conversation_evals_marks_http_errors_as_hard_contract_failures():
    evals = load_script("run_conversation_evals")
    dataset = evals.build_dataset([115], specs=evals.OUTCOME_CASE_SPECS)
    output = {
        "case": 115,
        "ok": False,
        "failures": ["HTTP 502: agent_invalid_response"],
        "components": [],
        "tools": [],
        "metrics": {},
    }

    report = dataset.evaluate_sync(lambda _inputs: output, progress=False)
    summary = evals.report_to_dict(report)

    assert summary["assertionSummary"]["no_http_error"]["passed"] == 0
    assert summary["assertionSummary"]["hard_contract_pass"]["passed"] == 0
    assert summary["assertionSummary"]["task_success"]["passed"] == 0


def test_conversation_evals_outcome_dataset_is_default_product_benchmark():
    evals = load_script("run_conversation_evals")
    specs = evals.specs_for_dataset("outcome")
    dataset = evals.build_dataset([101], specs=specs)

    assert 101 in specs
    assert len(specs) == 50
    assert dataset.name == "kalmio-conversation-evals"
    assert dataset.cases[0].metadata["category"] == "urgent_charging"
    assert dataset.cases[0].metadata["allowedUiFamilies"] == ["charger_recommendation"]
    assert all(evals.CATEGORY_BY_CASE.get(case_id) for case_id in specs)
    assert all(evals.ALLOWED_UI_FAMILIES_BY_CASE.get(case_id) for case_id in specs)


def test_render_report_summarizes_recommendation_and_changed_cases():
    render = load_script("render_conversation_benchmark_report")
    comparison = {
        "baseline": {"label": "deepseek-current", "passed": 30, "total": 30, "passRate": "100.0%"},
        "candidate": {"label": "pydantic-ai-deepseek", "passed": 29, "total": 30, "passRate": "96.7%"},
        "delta": {
            "passed": -1,
            "passRate": "-3.3%",
            "totalCostUsd": 0.001,
            "durationMs": 100,
            "llmCallCount": 1,
            "toolCallCount": 0,
            "repairCount": 2,
            "fallbackCount": 0,
            "inputTokens": 100,
            "outputTokens": 25,
        },
        "caseChanges": {
            "fixed": [{"case": 2}],
            "regressed": [{"case": 4, "failures": ["missing PositionRequestCard"]}],
            "changedFailures": [],
        },
        "recommendation": "descartar_o_iterar",
    }

    report = render.render_report(comparison)

    assert "# Pydantic AI DeepSeek Benchmark Report" in report
    assert "Recommendation: `descartar_o_iterar`" in report
    assert "- Caso 2" in report
    assert "- Caso 4: ['missing PositionRequestCard']" in report
    assert "Do not adopt" in report or "No adoptar" in report
