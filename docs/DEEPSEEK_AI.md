# DeepSeek Chat Runtime

Kalmio uses DeepSeek as the real LLM runtime for manual chat development and launch-readiness testing. The deterministic `local` agent remains available only for automated unit/e2e tests and emergency local fallback.

## Required Backend Env

```env
KALMIO_CONVERSATION_AGENT_MODE=deepseek
KALMIO_DEEPSEEK_API_KEY=replace-with-deepseek-api-key
KALMIO_DEEPSEEK_BASE_URL=https://api.deepseek.com
KALMIO_DEEPSEEK_MODEL=deepseek-v4-flash
KALMIO_DEEPSEEK_TIMEOUT_SECONDS=30
KALMIO_DEEPSEEK_MAX_TOOL_CALLS=3
KALMIO_DEEPSEEK_MAX_TOKENS=1800
KALMIO_DEEPSEEK_TEMPERATURE=0
KALMIO_DEEPSEEK_USE_NATIVE_TOOLS=true
KALMIO_DEEPSEEK_THINKING=false
```

Experimental Pydantic AI comparison mode uses the same DeepSeek provider settings:

```env
KALMIO_CONVERSATION_AGENT_MODE=pydantic_ai
```

Enable traces during development:

```env
KALMIO_AGENT_TRACE_ENABLED=true
KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS=true
KALMIO_AGENT_TRACE_FILE=.tmp/agent-traces.jsonl
```

Do not enable payload traces in production.

## How To Test

From the backend directory:

```bash
KALMIO_CONVERSATION_AGENT_MODE=deepseek python manage.py runserver
```

Then use the frontend chat or POST to `/api/conversation/message` with session cookies and CSRF. Inspect the latest turns with:

```bash
python .agents/skills/kalmio-chat-trace/scripts/analyze_trace.py --last-turns 10
```

Run the outcome eval matrix and write comparable metrics:

```bash
python scripts/run_conversation_eval_matrix.py \
  --dataset outcome \
  --agent-modes deepseek,pydantic_ai \
  --models deepseek-v4-pro \
  --output-dir ../reports/pydantic-ai-spike
```

Or run one live backend manually:

```bash
python scripts/run_conversation_evals.py \
  --api-base http://127.0.0.1:8000 \
  --dataset outcome \
  --label deepseek-v4-flash-evals \
  --output ../reports/conversation-evals/deepseek-v4-flash.json \
  --markdown-output ../reports/conversation-evals/deepseek-v4-flash.md
```

See `docs/conversation-evals.md` for evaluator layers and Logfire setup.

The app must never invent charger availability, prices, stations, coordinates, route metrics, or vehicle state. If DeepSeek, routing, or authorized charger data cannot validate an answer, the backend should return a minimal honest fallback.
