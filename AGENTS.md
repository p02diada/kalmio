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
- Fail explicitly and minimally when tools, Codex, provider routing, or authorized charger data cannot produce a reliable answer.

What must not be done:

- Do not build regex, keyword, or parser logic as the primary way to understand user intent in the agentic path.
- Do not make Django decide conversational intent or component choice in Codex mode.
- Do not encode rules such as "urgent means `UrgentChargeCard`" or "hotel means `DestinationChargingCard`" as backend repair logic.
- Do not silently convert a text answer into richer UI because the backend thinks a component would be better.
- Do not fabricate or infer availability, prices, stations, coordinates, route metrics, charger access, or vehicle state.
- Do not let local/dev fallback define production agent behavior.
- Do not use A2UI as arbitrary UI execution. Components, props, and actions must stay inside the allowlisted catalog.
- Do not make the frontend the place where important EV planning decisions happen; user actions go back through the agent/backend boundary.

## Approved Stack

Frontend: React, Vite, TypeScript, TanStack Router, TanStack Query, Tailwind CSS, shadcn/ui, PWA, A2UI renderer.

Backend: Django, Django Ninja, Django ORM, GeoDjango, Postgres/PostGIS, provider-backed routing, authorized charger imports.

## Development Commands

- Frontend: `cd frontend && npm install && npm run dev`.
- Backend: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt && python manage.py migrate && python manage.py runserver`.
- Docker: `docker compose up --build`.

## Agent Runtime Rules

- Use local mode only for automated unit tests and e2e test runs.
- When developing, inspecting the app manually, or starting a dev server to review behavior or UI, run through Codex mode.
- Prefer the smallest, lowest-cost Codex model that can handle the task, and minimize token usage by reading, generating, and retaining only relevant context. For routine local coding tasks, use `gpt-5.4-mini` unless the task clearly requires a stronger model.

## Phase Rules

- Complete Phase 0, Phase 0.5, and Phase 1 before Phase 2.
- Split large features into vertical slices.
- Keep docs current when architecture, A2UI, or design decisions change.
- Keep production docs current when runtime contracts, data imports, routing, A2UI, or design decisions change.

## A2UI Rules

- Only allowlisted components can render as dynamic UI.
- Validate every backend response.
- Unknown frontend blocks render a fallback.
- A broken block cannot crash the whole conversation.
- The A2UI catalog is the UI security boundary: the agent chooses blocks, the backend validates them, and the frontend renders only registered components.
- Describe components to the agent by purpose and data requirements, not as hardcoded intent mappings.
- Repair A2UI only for catalog, structure, action-safety, or data-traceability violations.

## AI Rules

- Do not invent availability, prices, stations, coordinates, or vehicle state.
- Ask clarifying questions when critical data is missing.
- Fail explicitly when provider-backed routing or authorized charger data is unavailable.
- The agent should interpret natural conversation and follow-ups from the full useful conversation context; do not add regex/intent parsers as the primary way to understand user phrasing.
- Backend code may validate structured arguments, enforce safety constraints, and execute approved tools, but should not become the conversational reasoning layer.
- In Codex mode, the backend must not use parsed intent to force tools or components.
- If a response cannot be validated, prefer a minimal honest fallback over backend-authored recommendations.

## Design Rules

- Mobile-first, calm, premium, trustworthy.
- Avoid generic AI UI and generic SaaS dashboards.
- Avoid excess cards without hierarchy.
- Use shadcn/ui as technical base only.
- Use Impeccable before important UI screens.
- Maintain consistent spacing, typography, color, states, and microcopy.
- Avoid generic gradients and overloaded layouts.
- Prefer design tokens and Tailwind utilities directly. Add semantic CSS classes only when they encapsulate reused patterns, complex CSS, or behavior that utilities express poorly; avoid creating a parallel design system with one-off semantic classes.

## Security Rules

- Do not install unknown MCPs without approval.
- Do not grant global filesystem access.
- Do not connect MCPs to real or production data.
- Do not store API keys in the repo.
- Do not execute destructive commands without confirmation.
- Do not allow arbitrary UI outside the A2UI catalog.
