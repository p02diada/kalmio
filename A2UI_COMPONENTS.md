# A2UI Components

## Contract

```ts
type A2UIBlock = {
  id: string
  type: string
  version: number
  props: unknown
}
```

Only registered types are valid. `/api/conversation/message` validates backend-generated block types before storing them in the Django session. Unknown frontend types render with a safe fallback so a broken or unsupported block cannot crash the whole chat.

This is Kalmio's local A2UI adapter for the current vertical slice. It is intentionally compatible with a later migration to official A2UI surface messages such as `createSurface`, `updateComponents`, and `updateDataModel`.

The agent chooses the UI that best fits the full conversation, user request, and tool results. The backend does not silently convert a text answer into richer UI and does not choose components from conversational intent. It asks the agent for one repair only when the final A2UI violates the catalog, data-traceability, or action-safety contract.

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

## Renderer Rules

- A broken block cannot break the whole conversation.
- Every block needs stable spacing and mobile-safe width.
- Renderer text helpers must normalize object labels before display; raw props such as `{"label": "..."}` or Python dict strings must never be visible.
- Unknown route, energy, arrival, price, or availability values must render as `No calculado`, `No disponible`, or equivalent explicit uncertainty, never as calculated-looking zeroes.
- Missing or stale provider data must expose uncertainty in the relevant card.
- Action buttons cannot claim unsupported actions such as booking or payment.
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
- Repair is for contract and data-safety violations only. Django must not repair by intent rules such as "urgent implies `UrgentChargeCard`" or "destination search implies `DestinationChargingCard`".
- `local` conversation mode may keep deterministic behavior for development and automated tests, but it does not define the primary agentic product behavior.

## Coverage

Each component needs automated rendering coverage before it is exposed through a production assistant flow.
