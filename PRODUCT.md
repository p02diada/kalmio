# Kalmio Product Context

## Register

product

## Product Purpose

Kalmio is a mobile-first PWA for electric vehicle drivers who want to plan trips and charging without charge anxiety. It is not a charger map. For the current slice, it turns trip inputs and authorized charger data into conservative, explainable charging-stop recommendations.

Claim: "Viaja sin ansiedad de carga."

## Users

- EV drivers planning intercity trips in Spain.
- Drivers with immediate low-battery stress who need a nearby, plausible charging option.
- Families who want charging stops to fit real travel needs such as food, restrooms, and comfort.
- Travelers staying overnight who need destination charging or a safe plan for several days.

## Core Jobs

- Capture critical route and preference data without guessing.
- Ask for missing critical information instead of inventing it.
- Use provider-backed routing and authorized charger imports only.
- Present one primary stop/place recommendation, alternatives, risk, confidence, and actions.
- Persist authenticated sessions and saved route-plan history when the backend can produce saveable plans.

## Tone

Calm, precise, conservative, and practical. Kalmio should feel like a trusted co-driver, not a flashy AI demo.

## Strategic Principles

- Chat first, map second. The map is contextual, never the home screen.
- Place-first, charger-backed. Drivers choose useful stops; backend facts still come from authorized stations, EVSEs, connectors, and providers.
- Conservative recommendations beat optimistic precision.
- Every recommendation must expose uncertainty when data is old, incomplete, unavailable, or estimated.
- Dynamic UI is allowed only through the approved A2UI component catalog.
- Prefer simple vertical slices over broad unfinished surfaces.

## Anti-References

- Generic AI chat landing pages.
- Charger-map clones where the user must inspect pins manually.
- Overloaded SaaS dashboards.
- Unbounded agent UI that can render arbitrary components.
- Claims of real-time charger availability or pricing without an authorized provider.

## Out Of Scope

- Flutter, native iOS, native Android, CarPlay, Android Auto.
- Turn-by-turn navigation.
- Payments and charger reservations.
- Community features.
- Direct vehicle integration.
- Scraping REVE or using unauthorized real REVE data.
- Claims of live charger availability or live pricing without an authorized provider.

## Success Signals

- A person can create an account, import authorized charger data, and request a real provider-backed charging-stop exploration.
- The backend refuses to invent route, charger, price, or availability data when providers or imports are missing.
- The PWA renders recommendations, alternatives, risk, warnings, and actions on mobile.
- Route-plan history is scoped to the authenticated account.
- Production startup fails closed when required security and data settings are missing.
