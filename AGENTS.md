# Agent Guide

## Product

Kalmio is a mobile-first PWA AI assistant for EV trip and charging planning. Claim: "Viaja sin ansiedad de carga."

## Product Philosophy: Agentic EV Assistant

Kalmio is an agentic product, not a deterministic intent-parser with a chat skin. The assistant must reason from the full useful conversation context and decide what the driver needs: urgent charging, route planning, destination/hotel charging, stay planning, follow-up corrections, missing data clarification, risk explanation, or a simple answer.

What the agent can and should do:

- Infer intent from natural conversation and follow-ups, including corrections such as changed location, battery, connector, destination, or preference.
- Decide whether to ask a clarifying question, call an approved backend tool, or return final A2UI blocks.
- Choose A2UI components by usefulness and context, not by rigid keyword rules.
- Return different UI for similar messages when prior context changes the driver need.
- Use structured metadata such as `intent`, `confidence`, or internal rationale when it helps validation, without exposing chain-of-thought or hidden reasoning to the user.
- Be honest about uncertainty, missing vehicle data, stale/unknown provider data, and unavailable route or charger data.

What the backend can and should do:

- Execute approved tools for factual work: location resolution, authorized charger lookup, provider-backed routing, scoring, persistence, and safety checks.
- Validate structured tool arguments, coordinate ranges, connector/preference schemas, session boundaries, throttling, CSRF, auth, and provider/data availability.
- Validate A2UI allowlists, prop structure, action support, and data traceability before anything reaches the frontend.
- Normalize harmless prop variants from the agent when the meaning is clear and still safe.
- Ask the agent for one repair when blocks violate catalog, action, or data-traceability contracts.
- Fail explicitly and minimally when tools, DeepSeek, provider routing, or authorized charger data cannot produce a reliable answer.

What must not be done:

- Do not build regex, keyword, or parser logic as the primary way to understand user intent in the agentic path.
- Do not make Django decide conversational intent or component choice in DeepSeek mode.
- Do not encode rules such as "urgent means `UrgentChargeCard`" or "hotel means `DestinationChargingCard`" as backend repair logic.
- Do not silently convert a text answer into richer UI because the backend thinks a component would be better.
- Do not fabricate or infer availability, prices, stations, coordinates, route metrics, charger access, or vehicle state.
- Do not let local/dev fallback define production agent behavior.
- Do not use A2UI as arbitrary UI execution. Components, props, and actions must stay inside the allowlisted catalog.
- Do not make the frontend the place where important EV planning decisions happen; user actions go back through the agent/backend boundary.

## Approved Stack

Frontend: React, Vite, TypeScript, TanStack Router, TanStack Query, Tailwind CSS, shadcn/ui, PWA, A2UI renderer.

Backend: Django, Django Ninja, Django ORM, GeoDjango, Docker PostGIS, provider-backed routing, authorized charger imports.

## Development Commands

- Frontend: `cd frontend && npm install && npm run dev`.
- Backend: `docker compose up --build`. Host-run Django against PostGIS is only for machines with GDAL/GEOS/database client libraries installed; Docker is the supported default.
- Docker: `docker compose up --build`.

## Conversation Evals

- Use `backend/scripts/run_conversation_evals.py` for one backend/model run against an already running API. `outcome` is the product benchmark dataset.
- Use `backend/scripts/run_conversation_eval_matrix.py` when comparing agent modes or OpenAI-compatible models. It starts a temporary backend per variant and writes JSON, Markdown and trace JSONL artifacts.
- Keep eval artifacts under `reports/` with labels that identify agent mode, model, dataset, and any material agent-contract version. Do not add runtime prompt modes; Kalmio currently has one production agent contract.
- Run automated tests in local mode: `cd backend && KALMIO_CONVERSATION_AGENT_MODE=local .venv/bin/python -m pytest`.
- For live model evals, provide API keys through environment variables only. Do not store keys in the repo or committed reports.

## Agent Runtime Rules

- Use local mode only for automated unit tests and e2e test runs.
- When developing, inspecting the app manually, or starting a dev server to review behavior or UI, run through DeepSeek mode.
- DeepSeek mode should use `KALMIO_CONVERSATION_AGENT_RUNTIME=pydantic_ai` by default. Use `legacy` only as a temporary compatibility comparison path.
- Run development servers and DeepSeek/pro conversation evaluations against the local Docker PostGIS charger database, not SQLite. SQLite is acceptable only for explicit fast unit-test commands; it is not representative for tool latency or station selection behavior.
- For repeated DeepSeek/pro eval setup, restore the local charger snapshot with `restore_charger_snapshot` instead of reimporting JSON. Regenerate the snapshot with `import_chargers` + `dump_charger_snapshot` only when charger data, importer behavior, or charging schema changes.
- Prefer the smallest, lowest-cost DeepSeek model that can handle the task, and minimize token usage by reading, generating, and retaining only relevant context.
- Do not send full tool payloads to the agent prompt when they are not useful for reasoning. Compact long outputs such as route geometry, coordinate arrays, provider traces, raw station lists, and repeated UI blocks into factual summaries that preserve decisions, uncertainty, traceability, and user-relevant values.
- For renderable factual tool results such as `plan_route` and `search_destination_chargers`, the Pydantic AI runtime may short-circuit final text generation and return validated A2UI derived from the tool result. This is a latency/safety optimization after the model has decided and called the tool; do not replace it with hardcoded intent routing.
- Pydantic AI output validators may reject an unhelpful final answer and ask the model to retry when the model had enough structured context to call an allowed tool. Example: a known city plus a charging request is enough for a first approximate `search_destination_chargers`; do not ask for an exact barrio before showing authorized options. Keep these as narrow validator guardrails, not Django intent routing.
- Do not add new tool arg/result contracts, A2UI output schemas, factuality rules, action-safety rules, or copy guardrails directly to `conversation_agent_prompt()` or the DeepSeek loop. Put them in versioned Pydantic contracts and policy modules, then keep the prompt as compact behavioral guidance.
- Runtime contract locations:
  - tool args/results: `backend/routing/tool_contracts.py`
  - A2UI final output models: `backend/routing/a2ui_output_models.py`
  - tool/history evidence ledger: `backend/routing/evidence.py`
  - A2UI/factual policies: `backend/routing/policies/`

## Where Agent Logic Lives

- Conversational choice lives in the model/runtime: whether to ask a clarifying question, call a tool, or return final A2UI. Do not replace this with Django keyword routing.
- Tool contracts live in `backend/routing/tool_contracts.py`: tool names, argument/result schemas, validation ranges, generated native tool definitions, compact summaries, and trace metadata.
- Tool execution and factual domain work live in `backend/routing/tools.py` and domain services such as `backend/routing/production_planner.py`: database queries, provider calls, charger scoring, route planning, and explicit provider/data failures.
- A2UI output shape lives in `backend/routing/a2ui_output_models.py`; factual evidence from tools/history lives in `backend/routing/evidence.py`.
- A2UI/factual/copy/action guardrails live in `backend/routing/policies/`. Add new rules there, split by concern, and keep `backend/routing/policies/a2ui.py` as an aggregator.
- `backend/routing/agent.py` may keep compatibility facades, local test mode, prompt construction, fallback composition, and shared low-level helpers, but it must not become the home for new factual, A2UI, copy, or action-safety rules.
- `backend/routing/pydantic_ai_runtime.py` owns the DeepSeek/Pydantic AI loop, registered tool calls, output-validator retries, duplicate/ungrounded tool-call blocking, and renderable-tool short-circuit. Keep runtime guardrails narrow; move product rules to contracts or policies.
- The frontend renderer and `frontend/src/lib/a2ui/kalmio-catalog.json` own renderable components, props, actions, safe functions, and styling. The frontend must not make important EV planning decisions locally.
- Prompts should stay compact behavioral guidance. Do not paste full schemas, long tool outputs, policy rules, or large repair logic into prompts when a typed contract or policy can enforce it.

## Phase Rules

- Complete Phase 0, Phase 0.5, and Phase 1 before Phase 2.
- Split large features into vertical slices.
- Keep docs current when architecture, A2UI, or design decisions change.
- Keep production docs current when runtime contracts, data imports, routing, A2UI, or design decisions change.

## A2UI Rules

- Official A2UI v0.9.1 is the canonical target for production-facing A2UI work unless a newer production version is explicitly adopted and documented.
- Kalmio's current `{id, type, version, props}` block shape is an internal adapter only. Do not treat it as the official protocol, and do not expand it as a new public wire contract.
- Production protocol work must be designed around A2UI envelopes: `createSurface`, `updateComponents`, `updateDataModel`, and `deleteSurface`.
- Conversation endpoints expose A2UI only through a `messages` envelope list. Do not add or consume a public `blocks` response field.
- Kalmio must maintain an application-specific, versioned A2UI catalog at `frontend/src/lib/a2ui/kalmio-catalog.json`. This catalog is the normative source of truth for components, props, actions, functions, theme values, semantic hints, and versioning.
- Do not maintain a second component-prop contract in markdown. Architecture docs and agent instructions may explain boundaries and behavior, but component props must be changed in the catalog/schema before agent use.
- Use stable catalog IDs, preferably URI-shaped, and bump or migrate catalog versions when component semantics or required props change.
- Only allowlisted components can render as dynamic UI.
- Validate every backend response.
- Unknown frontend blocks render a fallback.
- A broken block cannot crash the whole conversation.
- The A2UI catalog is the UI security boundary: the agent chooses blocks, the backend validates them, and the frontend renders only registered components.
- Describe components to the agent by purpose and data requirements, not as hardcoded intent mappings.
- Repair A2UI only for catalog, structure, action-safety, or data-traceability violations.
- Renderer styling is controlled by the renderer/design system. Agents may provide semantic component choices and supported semantic hints, but not arbitrary CSS, raw HTML, scripts, or visual styling.
- For charger capacity props, use EVSE semantics internally: `availableEvses` for available EVSE count and `totalEvses` for total EVSE count. Do not expose `connectorCount` as an A2UI prop. Use `connectorTypes` only for physical connector types such as CCS2 or Type2.
- User interactions must map to official A2UI actions: `event` for backend/agent handling, or registered `functionCall` for safe local renderer behavior such as opening a URL. Do not invent ad hoc action handlers or expose raw `href` as the action model.
- Client-to-server A2UI events must be sent as `{version:"v0.9.1", action:{...}}`; do not convert UI events into visible user chat text in the frontend.
- Prefer `updateDataModel` / data bindings for factual route, charger, location, uncertainty, and vehicle state. Component props may reference or summarize that data, but must not become an untraceable source of facts.
- Client capabilities must advertise supported catalog IDs when A2UI is transported over A2A/AG-UI/SSE/WebSocket. If no compatible catalog exists, the agent should not send UI.

## AI Rules

- Do not invent availability, prices, stations, coordinates, or vehicle state.
- Ask clarifying questions when critical data is missing.
- Fail explicitly when provider-backed routing or authorized charger data is unavailable.
- The agent should interpret natural conversation and follow-ups from the full useful conversation context; do not add regex/intent parsers as the primary way to understand user phrasing.
- Backend code may validate structured arguments, enforce safety constraints, and execute approved tools, but should not become the conversational reasoning layer.
- In DeepSeek mode, the backend must not use parsed intent to force tools or components.
- Kalmio business guardrails belong in Pydantic schemas, evidence-ledger policies, or Pydantic AI validators. `agent.py` may keep compatibility facades, but it must not become the place where new factual/A2UI rules accumulate.
- If a response cannot be validated, prefer a minimal honest fallback over backend-authored recommendations.

## Design Rules

- Mobile-first, calm, premium, trustworthy.
- Avoid generic AI UI and generic SaaS dashboards.
- Avoid excess cards without hierarchy.
- Use shadcn/ui as technical base only.
- Use Impeccable before important UI screens.
- Maintain consistent spacing, typography, color, states, and microcopy.
- Avoid generic gradients and overloaded layouts.
- Keep technical charging terms out of driver-facing labels unless they are widely understood. In visible UI/copy, show EVSE-derived capacity as "puestos de carga" or "puestos" and compact ratios like `4/10`; reserve "conectores" for physical connector types such as CCS2 or Type2. Do not label EVSE counts as connectors.
- Prefer design tokens and Tailwind utilities directly. Add semantic CSS classes only when they encapsulate reused patterns, complex CSS, or behavior that utilities express poorly; avoid creating a parallel design system with one-off semantic classes.

## Security Rules

- Do not install unknown MCPs without approval.
- Do not grant global filesystem access.
- Do not connect MCPs to real or production data.
- Do not store API keys in the repo.
- Do not execute destructive commands without confirmation.
- Do not allow arbitrary UI outside the A2UI catalog.
