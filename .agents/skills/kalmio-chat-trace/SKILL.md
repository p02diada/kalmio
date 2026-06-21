---
name: kalmio-chat-trace
description: Analyze Kalmio chat instrumentation after manual or automated chat tests. Use when the user asks to inspect the latest chat run, DeepSeek/API calls, token usage, estimated costs, internal Django tool calls, A2UI agent behavior, trace JSONL files, or why a Kalmio chat response behaved a certain way.
---

# Kalmio Chat Trace

Use this skill to analyze Kalmio agent traces written by the backend instrumentation.

## Trace Source

Default trace file:

```text
backend/.tmp/agent-traces.jsonl
```

Each JSONL line is one structured event. Important event types:

- `agent_turn`: one chat turn grouped by `turnId`.
- `llm_api_call`: Codex/DeepSeek call, duration, usage, and estimated cost when available.
- `internal_tool_call`: Django tool execution such as `resolve_location`, `search_destination_chargers`, or `plan_route`.
- `agent_guardrail`: backend guardrail such as repeated tool-call blocking or exhausted tool budget, usually followed by a final-only recovery pass.

Payloads are present only when `KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS=true`. Treat payloads as local/private because they may contain user text, route context, coordinates, and tool results. Never print API keys or secrets.

## Quick Analysis

Run the bundled analyzer from the repo root:

```bash
python .agents/skills/kalmio-chat-trace/scripts/analyze_trace.py --last-turns 5
```

For machine-readable output:

```bash
python .agents/skills/kalmio-chat-trace/scripts/analyze_trace.py --last-turns 5 --json
```

If the trace file is elsewhere:

```bash
python .agents/skills/kalmio-chat-trace/scripts/analyze_trace.py --file backend/.tmp/agent-traces.jsonl --last-turns 10
```

## Review Workflow

1. Run the analyzer for the latest 3-10 turns.
2. Identify total LLM calls, internal tool calls, duration, tokens, estimated cost, and cache hit/miss rate.
3. Check warnings first: LLM errors, tool errors, missing usage, cache-cost assumptions, unexpectedly low cache hit rate, or missing payloads.
4. Reconstruct the sequence for each `turnId`: agent turn -> LLM decision -> internal tool calls -> final LLM response.
5. If payloads are enabled, inspect only the relevant request/response fields needed to explain behavior. Summarize sensitive user data instead of dumping it.
6. Compare tool results against final A2UI behavior: stations, coordinates, route metrics, and prices must come from tool results or explicit user input.
7. State whether the issue is model decision quality, tool/data availability, A2UI validation/repair, provider/API failure, or frontend rendering.

## Interpretation Rules

- DeepSeek cost is an estimate based on API `usage` and configured per-1M-token rates.
- If cache hit/miss tokens are missing, the backend assumes cache miss for input cost and marks the basis.
- The analyzer reports cache hit/miss tokens and hit percentage when the provider returns cache counters or the backend can derive them from cached-token fields.
- Internal tools have duration and status but no direct monetary cost unless a future provider exposes one.
- A tool event with `status=error` may be an honest no-data result, not necessarily a crash.
- Missing payloads mean the high-level trace can still show cost/duration/sequence, but not prompts, tool args, or final raw model output.

## Common Follow-Ups

- If costs are unexpectedly high, inspect `promptChars`, `messageCount`, repeated tool calls, repair calls, and `maxTokens`.
- If the model hallucinated a charger, compare final A2UI payloads with `internal_tool_call.response.stops`.
- If a hotel/destination query failed, check whether the model called `resolve_location` or `search_destination_chargers`, and whether the tool returned `ok=false`.
- If a response fell back, look for `llm_api_call status=error`, `agent_guardrail`, repeated tool calls, exhausted tool budget, or A2UI repair failure.
