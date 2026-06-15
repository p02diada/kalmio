# A2UI Components

## Official Protocol Target

Kalmio targets official A2UI v0.9.1 for production-facing agent-driven UI.

Canonical server-to-client A2UI messages are:

- `createSurface`: initialize a surface and select a catalog.
- `updateComponents`: add or update components in that surface.
- `updateDataModel`: update the factual state used by components.
- `deleteSurface`: remove a surface.

Kalmio's catalog id is:

```text
https://kalmio.app/a2ui/catalogs/ev-assistant/v1/catalog.json
```

The catalog is application-specific. It constrains the agent to Kalmio EV assistant components, safe registered functions, semantic props, and renderer-owned styling. The Basic Catalog may be useful for reference, but production Kalmio UI should not depend on generic arbitrary components when a domain component is required.

The current catalog schema draft lives at `frontend/src/lib/a2ui/kalmio-catalog.json`. Backend envelope emission lives at `backend/routing/a2ui_protocol.py`; frontend message processing lives at `frontend/src/lib/a2ui/protocol.ts`.

## Local Adapter Contract

The current vertical slice stores validated UI internally as a local adapter shape:

```ts
type KalmioA2UIBlock = {
  id: string
  type: string
  version: number
  props: unknown
}
```

This shape is not the official A2UI wire protocol. It is an internal persistence and renderer-state boundary. `/api/conversation/messages` and `/api/conversation/message` return official A2UI v0.9.1 `messages` snapshots containing `createSurface`, `updateComponents`, and `updateDataModel`.

Only registered types are valid. `/api/conversation/message` validates backend-generated block types before storing them in the Django session. Unknown frontend types render with a safe fallback so a broken or unsupported block cannot crash the whole chat.

The agent chooses the UI that best fits the full conversation, user request, and tool results. The backend does not silently convert a text answer into richer UI and does not choose components from conversational intent. It asks the agent for one repair only when the final A2UI violates the catalog, data-traceability, or action-safety contract.

New work must keep the adapter migrable to official A2UI:

- Component names must exist in the Kalmio catalog.
- Props must be schema-valid for the component.
- Factual values should be representable in `updateDataModel`; props can summarize or reference data but must not become an untraceable fact source.
- Actions must map to official A2UI `event` or `functionCall` semantics.
- Styling belongs to the renderer/design system, not agent-authored props.

## Required Components

- `AssistantMessage`: natural-language assistant response.
- `UserMessage`: user message echo.
- `TripSummaryCard`: route intent, origin, destination, battery, reserve.
- `RouteSummaryCard`: distance, duration, estimated energy, reserve.
- `RecommendedStopCard`: primary charging stop.
- `AlternativeRoutesList`: route alternatives.
- `AlternativeStopsList`: charger alternatives.
- `RiskExplanationCard`: uncertainty, stale data, reserve issues.
- `CostComparisonCard`: cheap route comparison.
- `UrgentChargeCard`: immediate low-battery plan.
- `DestinationChargingCard`: destination or hotel charging.
- `StayPlanningCard`: multi-day stay plan.
- `MapPreviewCard`: contextual visual route preview or placeholder.
- `ActionButtons`: next actions such as open navigation, save, adjust.
- `ClarifyingQuestionCard`: missing critical data.
- `LocationRequestCard`: request browser location or manual city/coordinates when location is critical.
- `LocationDetailCard`: resolved city/coordinate context used for a search, including precision and whether the user should confirm the final place.
- `PreferenceChips`: quick preference controls.
- `ErrorFallbackCard`: unknown or broken component.

## Decision Prop Model

EV planning blocks may share these Kalmio-specific props. These are not official A2UI common types; they are part of the Kalmio catalog and must be represented in the catalog schema.

```ts
type KalmioEvidence = {
  label: string
  value: string | number | boolean | null
  unit?: string
  status?: "known" | "estimated" | "unknown"
  sourcePath?: string
}

type KalmioUncertainty = {
  level: "info" | "medium" | "high"
  text: string
  source?: string
  freshness?: string
}

type KalmioAction = {
  label: string
  priority?: "primary" | "secondary"
  disabled?: boolean
  reason?: string
  event?: {
    name: string
    context?: Record<string, unknown>
  }
  functionCall?: {
    call: "openUrl"
    args: { url: string }
  }
}

type KalmioDecisionProps = {
  title?: string
  takeaway?: string
  why?: string
  evidence?: KalmioEvidence[]
  uncertainty?: KalmioUncertainty
  primaryAction?: KalmioAction
}
```

Use these for decision-heavy components such as `RecommendedStopCard`, `UrgentChargeCard`, `DestinationChargingCard`, `StayPlanningCard`, and `RiskExplanationCard` when the current simple props cannot explain the decision safely.

## Renderer Rules

- A broken block cannot break the whole conversation.
- Every block needs stable spacing and mobile-safe width.
- Renderer styles, colors, spacing, typography, and visual hierarchy come from Kalmio's design system. The agent can choose components and semantic props, not arbitrary styling.
- Renderer text helpers must normalize object labels before display; raw props such as `{"label": "..."}` or Python dict strings must never be visible.
- Unknown route, energy, arrival, price, or availability values must render as `No calculado`, `No disponible`, or equivalent explicit uncertainty, never as calculated-looking zeroes.
- Missing or stale provider data must expose uncertainty in the relevant card.
- Action buttons cannot claim unsupported actions such as booking or payment.
- `ActionButtons` and component-level actions must use `KalmioAction.event` for backend/agent work or `KalmioAction.functionCall` for registered safe local behavior. Raw `href` is not part of Kalmio's A2UI action contract.
- Preference chips may send a new user message back to the conversation agent.
- Location requests may trigger browser geolocation only through the frontend renderer and must offer manual city/coordinate entry.

## Agent And Backend Boundary

- The agent infers intent from the useful conversation context and decides whether to call a tool, ask a question, or return final A2UI.
- Components are described to the agent by purpose, not as hardcoded intent mappings. Similar user messages may produce different blocks when context justifies it.
- Django validates allowlisted component types, normalizes known prop variants, and renders unsupported component requests as `ErrorFallbackCard`.
- Structured charger/station facts in blocks such as `AlternativeStopsList`, `RecommendedStopCard`, and `UrgentChargeCard` must trace to current tool results or previously validated session blocks.
- Route metrics in `RouteSummaryCard` must trace to `plan_route`. Coordinates in `LocationDetailCard` must come from a tool or explicit user coordinates.
- Prices, availability, station details, route metrics, and vehicle state must not be invented. If current tools do not provide prices, `CostComparisonCard` cannot show prices.
- `ActionButtons` can expose only safe supported actions such as opening navigation/map links, refining the search, or disabled save actions. Booking, payment, and arbitrary script actions are not supported.
- Opening navigation/map links is a registered local function call. Refining a search, saving a plan, or submitting manual input is an event sent back to the backend/agent.
- Repair is for contract and data-safety violations only. Django must not repair by intent rules such as "urgent implies `UrgentChargeCard`" or "destination search implies `DestinationChargingCard`".
- `local` conversation mode may keep deterministic behavior for development and automated tests, but it does not define the primary agentic product behavior.

## Protocol Requirements

For the current REST snapshot transport and future streamed transports:

1. Publish and validate the Kalmio catalog schema for `ev-assistant/v1`.
2. Return A2UI v0.9.1 envelopes from backend conversation endpoints; do not expose local blocks as the frontend contract.
3. Include `catalogId` in every `createSurface`.
4. Advertise supported catalog IDs from the client when using A2A, AG-UI, SSE, or WebSocket transports.
5. Move factual route, charger, location, uncertainty, and vehicle state into a data model where practical.
6. Map user interactions to `action.event` or registered `action.functionCall` payloads.
7. Keep unknown or invalid components recoverable through graceful fallback and error reporting.

## Coverage

Each component needs automated rendering coverage before it is exposed through a production assistant flow.
