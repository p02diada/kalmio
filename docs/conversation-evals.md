# Conversation Evals

Kalmio conversation quality is evaluated with the `outcome` dataset. It accepts behavior changes while preserving safety, usefulness, tool policy, A2UI contract health, latency and cost visibility.

## Runner

Run against a live backend:

```bash
cd backend
python scripts/run_conversation_evals.py \
  --api-base http://127.0.0.1:8000 \
  --dataset outcome \
  --label deepseek-v4-flash-evals \
  --output ../reports/conversation-evals/deepseek-v4-flash.json \
  --markdown-output ../reports/conversation-evals/deepseek-v4-flash.md
```

Use `--repeat 3` for stability checks. Keep `--max-concurrency 1` when using the session-based Django conversation endpoint.

Run a controlled matrix when comparing runtimes or models. The matrix runner starts one temporary backend per variant and writes JSON, Markdown and trace JSONL artifacts:

```bash
cd backend
python scripts/run_conversation_eval_matrix.py \
  --dataset outcome \
  --agent-modes deepseek,pydantic_ai \
  --models deepseek-v4-pro \
  --repeat 3 \
  --max-concurrency 1 \
  --output-dir ../reports/outcome-runtime-spike
```

OpenAI-compatible model experiments can use the same runner without storing keys in the repo:

```bash
cd backend
export OPENAI_API_KEY=...
python scripts/run_conversation_eval_matrix.py \
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
python scripts/run_conversation_evals.py \
  --api-base http://127.0.0.1:8000 \
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
