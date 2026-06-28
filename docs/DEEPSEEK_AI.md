# DeepSeek Chat Runtime

Kalmio uses DeepSeek as the real LLM runtime for manual chat development and launch-readiness testing. The deterministic `local` agent remains available only for automated unit/e2e tests and emergency local fallback.

## Required Backend Env

```env
KALMIO_CONVERSATION_AGENT_MODE=deepseek
KALMIO_CONVERSATION_AGENT_RUNTIME=pydantic_ai
KALMIO_DEEPSEEK_API_KEY=replace-with-deepseek-api-key
KALMIO_DEEPSEEK_BASE_URL=https://api.deepseek.com
KALMIO_DEEPSEEK_MODEL=deepseek-v4-pro
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

## Tool Contracts

Conversation tool args/results are defined in the versioned backend registry at
`backend/routing/tool_contracts.py`, currently
`https://kalmio.app/agent/contracts/conversation-tools/v1`.

The registry is the source of truth for:

- allowed conversation tool names
- native DeepSeek/OpenAI-compatible tool definitions
- Pydantic validation before and after tool execution
- compact prompt summaries
- trace metadata such as contract id, version and validation status

Do not reintroduce full tool arg/result schemas into the agent prompt. The prompt
may include a generated compact summary, but validation and evolution must happen
through the versioned registry.

`KALMIO_CONVERSATION_AGENT_RUNTIME=pydantic_ai` is the canonical DeepSeek runtime.
Pydantic AI owns the agent loop: model request, registered function tools, tool
results, final structured output and output-validator retries. For factual tool
results that are already renderable (`plan_route` and
`search_destination_chargers`), Kalmio short-circuits the post-tool final
generation and returns validated A2UI derived from the tool result. The model
still owns the conversational decision and tool arguments; the short-circuit is
only a latency and factuality boundary after a validated tool result exists.
Output-validator retries may also reject final answers that ask for unnecessary
precision when the user already gave enough safe context for an allowed tool. For
example, a known city plus a charger request should trigger a first approximate
`search_destination_chargers` call instead of asking for an exact barrio before
showing authorized options.
`legacy` remains only as a temporary compatibility path while development is
still in flight.

Kalmio-specific safety rules live outside the prompt and outside the provider
loop:

- Tool args/results: `backend/routing/tool_contracts.py`
- A2UI final output models: `backend/routing/a2ui_output_models.py`
- Tool/history evidence ledger: `backend/routing/evidence.py`
- A2UI/factual policies: `backend/routing/policies/`
  - component/data traceability: `backend/routing/policies/components.py`
  - message component contracts: `backend/routing/policies/messages.py`
  - station component contracts: `backend/routing/policies/stations.py`
  - station, route and map fact matching: `backend/routing/policies/traceability.py`
  - copy and factuality guardrails: `backend/routing/policies/copy.py`
  - A2UI action safety: `backend/routing/policies/actions.py`
  - policy aggregation: `backend/routing/policies/a2ui.py`
- Pydantic AI output-validator guardrails:
  `backend/routing/pydantic_ai_runtime.py`

Do not add new charger, route, copy, factuality, action-safety or A2UI repair
rules directly to `conversation_agent_prompt()` or the DeepSeek loop. Add or
version the Pydantic schema/policy, then make the prompt mention only the compact
behavioral guidance needed by the model. Final A2UI/factual validation runs as a
Pydantic AI output validator. If a renderable tool result exists, invalid final
output is converted to validated tool-result A2UI instead of adding another slow
LLM repair pass.

`backend/routing/agent.py` is allowed to keep legacy facades and shared helpers
while the policy layer is being split, but new guardrails should not be added
there. If a rule checks whether rendered data is traceable, whether copy implies
unverified safety/price/availability, or whether an action is supported, add it
under `backend/routing/policies/` and cover it with a focused test. If a rule is
about tool shape, range, or result validity, add it to
`backend/routing/tool_contracts.py`. If it is factual planning behavior, put it
in the tool/domain service.

## Local Data For DeepSeek Runs

DeepSeek/pro runs should use the local Docker PostGIS charger database. SQLite
is only acceptable for fast unit tests; it is not representative for route-tool
latency or station selection.

Start the database and restore the authorized development charger snapshot:

```bash
make charger-restore
```

Regenerate the snapshot only when the charger fixture or importer changes:

```bash
make reve-import
make charger-snapshot
```

The snapshot contains only `charging_*` tables. The JSON/importer remains the
source-of-truth path for data shape changes; the dump is a fast local cache for
repeatable DeepSeek/pro evals.

## How To Test

From the repository root:

```bash
docker compose up --build backend
```

For the full app, use `docker compose up --build` or `make dev`. Then use the
frontend chat or POST to `/api/conversation/message` with session cookies and
CSRF. Inspect the latest turns with:

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
