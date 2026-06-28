# Pydantic AI DeepSeek Spike

Status: implemented and benchmarked against DeepSeek.

## Goal

Compare the current hand-rolled DeepSeek conversation runtime with an experimental Pydantic AI runtime using the same DeepSeek model and the same Kalmio backend contracts.

This spike does not compare GPT/OpenAI models.

## Result

Decision: do not adopt Pydantic AI as the default runtime from the initial spike alone. Keep the current DeepSeek runtime and rerun the current outcome eval matrix before making a production runtime decision.

The initial benchmark was executed against the same DeepSeek configuration from the main worktree and the same local authorized charger data. Because live LLM calls are stochastic and the benchmark dataset has since been replaced, treat the earlier result as superseded by the current outcome eval matrix.

## Modes

- `KALMIO_CONVERSATION_AGENT_MODE=deepseek`: current runtime.
- `KALMIO_CONVERSATION_AGENT_MODE=pydantic_ai`: experimental runtime using Pydantic AI with DeepSeek.

Both modes keep the same public endpoints, tools, A2UI validation, grounding checks, repair flow, local mode and fallback behavior.

## Benchmark

With `KALMIO_DEEPSEEK_API_KEY` or `DEEPSEEK_API_KEY` available, run the current outcome eval matrix from `backend/`:

```bash
python scripts/run_conversation_eval_matrix.py \
  --dataset outcome \
  --agent-modes deepseek,pydantic_ai \
  --models deepseek-v4-pro \
  --output-dir ../reports/pydantic-ai-spike
```

This starts the backend once per mode/model variant and writes JSON, Markdown and trace JSONL artifacts.

If the live run is split into chunks, combine JSON summaries before comparing:

```bash
python scripts/combine_conversation_benchmark_chunks.py \
  ../reports/pydantic-ai-spike-1-5/deepseek-current.json \
  ../reports/pydantic-ai-spike-6-10/deepseek-current.json \
  --label deepseek-current \
  --output ../reports/pydantic-ai-spike/deepseek-current.json
```

Manual execution remains useful when debugging one mode at a time. Start the backend with tracing enabled, then run:

```bash
python scripts/run_conversation_evals.py \
  --api-base http://127.0.0.1:8000 \
  --dataset outcome \
  --label deepseek-current \
  --output ../reports/deepseek-current.json \
  --markdown-output ../reports/deepseek-current.md
```

Restart the backend in Pydantic AI mode:

```bash
KALMIO_CONVERSATION_AGENT_MODE=pydantic_ai python manage.py runserver
```

Then run the same outcome eval:

```bash
python scripts/run_conversation_evals.py \
  --api-base http://127.0.0.1:8000 \
  --dataset outcome \
  --label pydantic-ai-deepseek \
  --output ../reports/pydantic-ai-deepseek.json \
  --markdown-output ../reports/pydantic-ai-deepseek.md
```

Compare both benchmark files:

```bash
python scripts/compare_conversation_benchmarks.py \
  ../reports/deepseek-current.json \
  ../reports/pydantic-ai-deepseek.json \
  --output ../reports/pydantic-ai-deepseek-comparison.json
python scripts/render_conversation_benchmark_report.py \
  ../reports/pydantic-ai-deepseek-comparison.json \
  --output ../reports/pydantic-ai-deepseek-report.md
```

## Decision Metrics

Use the generated JSON files to compare:

- pass rate across the outcome cases;
- estimated total and per-case DeepSeek cost;
- input, output, total and cache-hit tokens;
- total latency and LLM latency;
- tool call count and tool errors;
- A2UI repair count;
- fallback count;
- invalid LLM or tool errors.

The comparison JSON reports aggregate deltas and changed cases:

- `caseChanges.fixed`: cases that failed in the current runtime and passed with Pydantic AI.
- `caseChanges.regressed`: cases that passed in the current runtime and failed with Pydantic AI.
- `caseChanges.changedFailures`: cases still failing with different failure reasons.
- `recommendation`: one of `adoptar_si_reduce_complejidad`, `adoptar_si_revision_manual_confirma_calidad`, `iterar`, or `descartar_o_iterar`.

The Markdown report summarizes the same comparison for the final adoption decision. It is still an automated report; inspect changed cases manually before adopting.

## Decision Rule

Adopt Pydantic AI only if it preserves or improves pass rate and safety while reducing runtime complexity or improving benchmark observability.

Iterate if the failures are concentrated in output schema prompting or Pydantic AI settings and the current runtime is not clearly better.

Discard the adapter if it introduces more grounding failures, more A2UI repairs, higher invalid response rates, or materially worse latency/cost with the same DeepSeek model.
