# Conversation Evals

Kalmio conversation quality is evaluated with the `outcome` dataset. It accepts behavior changes while preserving safety, usefulness, tool policy, A2UI contract health, latency and cost visibility.

## Runner

Use the current `outcome` dataset in `backend/scripts/run_conversation_evals.py`
and evaluate with `deepseek-v4-pro` unless an experiment explicitly says
otherwise. The current dataset contains 50 cases (`101`-`150`); seeing only 30
cases means an old script or old worktree is being used.

Run DeepSeek/pro evals against the local Docker PostGIS charger database.
SQLite is only for unit tests and will distort route-tool latency. Prefer restoring the local
charger snapshot for repeated eval runs; reimport the JSON only when regenerating
the snapshot after data or importer changes.

```bash
make charger-restore
```

Regenerate the snapshot from the canonical JSON fixture when needed:

```bash
make reve-import
make charger-snapshot
```

Run against a live backend:

```bash
docker compose up -d backend
docker compose run --rm backend python scripts/run_conversation_evals.py \
  --api-base http://backend:8000 \
  --dataset outcome \
  --label deepseek-v4-pro-evals \
  --output ../reports/conversation-evals/deepseek-v4-pro.json \
  --markdown-output ../reports/conversation-evals/deepseek-v4-pro.md
```

Use `--repeat 3` for stability checks. Keep `--max-concurrency 1` when using the session-based Django conversation endpoint.

Latest local launch-readiness run, 2026-06-28:

- Runtime: `KALMIO_CONVERSATION_AGENT_RUNTIME=pydantic_ai`
- Model: `deepseek-v4-pro`
- DB: local Docker PostGIS charger data
- Dataset: `outcome` cases `101`-`150`
- Result: `50/50` task success, hard contracts, tool policy, UI family and safety
- Report: `reports/conversation-eval-direct-pro-postgis/101-150-full-guardrail.json`
- Average duration: `5660.9534 ms`, repairs `0`, fallbacks `0`

Run a controlled matrix when comparing runtimes or models. The matrix runner starts one temporary backend per variant and writes JSON, Markdown and trace JSONL artifacts:

```bash
docker compose run --rm backend python scripts/run_conversation_eval_matrix.py \
  --dataset outcome \
  --agent-modes deepseek \
  --models deepseek-v4-pro \
  --repeat 3 \
  --max-concurrency 1 \
  --output-dir ../reports/outcome-runtime-spike
```

OpenAI-compatible model experiments can use the same runner without storing keys in the repo:

```bash
export OPENAI_API_KEY=...
docker compose run --rm -e OPENAI_API_KEY backend python scripts/run_conversation_eval_matrix.py \
  --dataset outcome \
  --agent-modes deepseek \
  --base-url https://api.openai.com/v1 \
  --api-key-env OPENAI_API_KEY \
  --models gpt-5.5 \
  --output-dir ../reports/outcome-openai-spike
```

## Evaluation Layers

- `case_acceptance`: pass/fail from the case spec.
- `hard_contract_pass`: no HTTP 502, no LLM/tool errors, no fallback.
- `tool_policy_pass`: required tools were called and forbidden tools were not called.
- `ui_family_pass`: response fits an allowed UI family, not one exact component recipe.
- `safety_pass`: no detected fabrication or tool failure.
- `task_success`: pragmatic success combining contract, tool policy and flexible UI family.
- score metrics: duration, LLM calls, tool calls, repairs, fallbacks and estimated cost.

This lets us distinguish:

- model quality problems;
- agent or A2UI contract mismatch;
- overly strict case assertions;
- actual safety or backend failures.

## Logfire

Logfire is optional and disabled by default.

Development/local trace setup:

```env
KALMIO_LOGFIRE_ENABLED=true
KALMIO_LOGFIRE_SERVICE_NAME=kalmio-backend
KALMIO_LOGFIRE_SEND_TO_LOGFIRE=if-token-present
KALMIO_LOGFIRE_INSTRUMENT_DJANGO=true
KALMIO_LOGFIRE_INSTRUMENT_HTTPX=true
```

To send traces to Logfire, provide a token outside the repo:

```env
LOGFIRE_TOKEN=...
```

The eval runner can also enable Logfire for a run:

```bash
docker compose run --rm backend python scripts/run_conversation_evals.py \
  --api-base http://backend:8000 \
  --dataset outcome \
  --label deepseek-pro-evals \
  --logfire
```

Do not enable payload capture with real user data unless the data has been reviewed for privacy.

## Model Decision Rule

A candidate is worth production consideration only if:

- `hard_contract_pass` does not regress;
- `task_success` improves or stays stable;
- HTTP 502 and invalid responses do not increase;
- safety pass stays at 100%;
- cost and latency are acceptable for production volume;
- regressions are manually reviewed.

## Agent Contract Versioning

Kalmio currently has one production agent contract. When it changes materially, record the version in the eval label and report artifacts instead of adding runtime behavior modes.
