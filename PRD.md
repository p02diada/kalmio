# PRD: Kalmio

## Summary

Kalmio is a mobile-first PWA for EV trip and charging planning. Claim: "Viaja sin ansiedad de carga."

The product turns explicit trip coordinates, an authenticated vehicle profile, and authorized charger data into conservative, explainable charging recommendations. It must never invent stations, availability, prices, coordinates, vehicle state, or route metrics.

## Primary Use Cases

1. Plan a route in an anonymous Django session while keeping enough battery reserve.
2. Find compatible charging stops near a route corridor.
3. Prefer safer, faster, cheaper, or more comfortable stops based on saved preferences.
4. Review previous route plans for the authenticated account.
5. Submit feedback tied to a saved route plan.

## Product Principles

- Ask when critical data is missing.
- Use provider-backed routing and persisted authorized charger data.
- Show uncertainty, confidence, and risk.
- Keep dynamic UI constrained through the approved A2UI catalog when assistant-style UI returns.
- Make the primary recommendation actionable, with nearby alternatives where data supports them.
- Fail explicitly when provider or station data is unavailable.

## Approved Stack

Frontend: React, Vite, TypeScript, TanStack Router, TanStack Query, Tailwind CSS, shadcn/ui, PWA manifest and service worker, MapLibre GL JS or future map provider, A2UI renderer.

Backend: Django, Django Ninja, Django ORM, GeoDjango, Postgres with PostGIS, OSRM-compatible routing provider, authorized charger imports, optional Redis/Celery only if needed later.

## Out Of Scope

Native mobile apps, Flutter, CarPlay, Android Auto, turn-by-turn navigation, payments, reservations, community, direct vehicle integration, REVE scraping, unauthorized real REVE data, and any runtime fake charger data.

## Success Metrics

- Anonymous session route planning works through `/api/conversation/route`.
- Authenticated saved route planning works through `/api/plans/route`.
- `/api/ready` returns `200` only when the backend has database access, applied migrations, route-provider configuration, and authorized charger data with connectors.
- The planner never silently violates the configured battery reserve.
- Route-plan history is scoped to the authenticated account.
- Feedback is accepted only for a route plan owned by the authenticated account.
- README setup and production configuration can be followed on a clean machine.

## Risks

- EV planning can imply precision beyond the available provider and charger data.
- Stale imported charger availability and pricing can be mistaken for live guarantees.
- A2UI flexibility can become arbitrary UI unless constrained.
- PostGIS and GeoDjango add environment complexity.
- The app must handle missing provider or charger data without degrading into fabricated answers.

## Roadmap

Phase 0: docs and acceptance criteria.
Phase 0.5: agentic environment, skills, MCP guardrails, visual direction.
Phase 1: scaffold frontend, backend, Docker, healthcheck.
Phase 2: A2UI contract and safe renderer.
Phase 3: mobile-first route-planning home.
Phase 4: authenticated accounts and vehicle profile.
Phase 5: authorized charger data import.
Phase 6: provider-backed route planning.
Phase 7: saved route-plan history and feedback.
Phase 8: contextual map and external navigation.
Phase 9: production settings, readiness, and deployment hardening.
Phase 10: provider expansion and observability.

## Implementation Status

Done in this workspace:

- React/Vite/TypeScript PWA with TanStack Router, TanStack Query, Tailwind, shadcn-style primitives, manifest, icons, and service worker.
- Mobile-first routes: `/`, `/vehicle`, `/activity`, `/settings`.
- Django/Ninja backend with `/api/health`, `/api/ready`, `/api/auth/*`, `/api/conversation`, `/api/conversation/route`, `/api/vehicle-profile`, `/api/vehicle-catalog`, `/api/plans/route`, `/api/stations/nearby`, `/api/stations/{id}`, and `/api/feedback`.
- Authenticated Django sessions with CSRF protection on unsafe endpoints.
- Persisted per-user vehicle profile and planning preferences.
- Provider-backed anonymous and authenticated route planning through OSRM-compatible routing plus persisted authorized station data.
- Authorized EV catalog import through `import_vehicles`, rejecting sample, fixture, mock, and test sources.
- Authorized charger import through `import_chargers`, rejecting sample, fixture, mock, and test sources.
- Saved route plans owned by the authenticated user.
- Feedback model and API scoped to saved route-plan ownership.
- Production runtime checks for secure settings, PostGIS database backend, explicit hosts/origins, disabled public docs by default, and readiness gating.

Explicit limitations:

- Kalmio does not guarantee live charger availability or price unless the imported provider data contains current observations.
- Navigation is opened externally; Kalmio does not provide turn-by-turn navigation.
- Vehicle data can be manually configured or copied from an authorized imported catalog entry; there is no direct vehicle integration.
- The contextual map remains secondary to the route recommendation until a production map provider is configured.
- A2UI remains available as a constrained rendering catalog for future assistant flows, but route planning currently returns typed route-plan schemas.
