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

The agent chooses the UI that best fits the user request and tool results. The backend does not silently convert a text answer into a richer UI in the normal path; it validates semantic obligations and asks the agent for one repair when the final A2UI is incomplete.

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
- `PreferenceChips`: quick preference controls.
- `ErrorFallbackCard`: unknown or broken component.

## Renderer Rules

- A broken block cannot break the whole conversation.
- Every block needs stable spacing and mobile-safe width.
- Missing or stale provider data must expose uncertainty in the relevant card.
- Action buttons cannot claim unsupported actions such as booking or payment.
- Preference chips may send a new user message back to the conversation agent.

## Semantic Rules

- After `search_destination_chargers`, final A2UI must include a destination context, charger alternatives sourced from the tool result, and an uncertainty/risk explanation.
- After `plan_route`, final A2UI must include a route summary and recommended stop sourced from the tool result.
- If final A2UI violates these rules, Django asks the agent for one repaired `final.blocks` response. If repair fails, Django returns deterministic fallback A2UI.

## Coverage

Each component needs automated rendering coverage before it is exposed through a production assistant flow.
