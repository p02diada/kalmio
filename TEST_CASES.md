# Test Cases

## Primary Route Scenarios

1. Córdoba to Valencia using explicit anonymous-session vehicle data with 58% battery and CCS2 connector.
2. Route below minimum reserve must warn that charging is required.
3. Route provider unavailable returns a structured provider error.
4. No compatible authorized station data returns a structured planning-data error.
5. Anonymous session can create and read one active route conversation without account history.
6. Authenticated account can list only its saved route plans.
7. Authenticated account can create and update only its own vehicle profile.
8. Authenticated account can apply an authorized catalog vehicle to its profile without inventing missing characteristics.

## Missing Data

- Route request without origin.
- Route request without destination.
- Route request without authenticated session.
- Route request without CSRF token on unsafe methods.
- Anonymous route conversation without explicit vehicle data returns `chargers_only`.
- Registration with invalid email.
- Login after repeated failed attempts.
- Vehicle profile update without CSRF token.
- Authenticated route planning with an incomplete vehicle profile returns non-persisted `chargers_only`.
- Feedback without authenticated route-plan ownership.
- Charger import missing required provider fields.
- Charger import dry-run validates authorized files without database writes.
- Vehicle import missing required catalog fields.
- Vehicle import dry-run validates authorized files without database writes.
- Vehicle catalog freshness check rejects stale authorized imports.

## Fallbacks

- Unknown A2UI component renders `ErrorFallbackCard`.
- Backend unavailable shows frontend error state.
- Broken route-plan response cannot crash the app.

## Reserve And Scoring

- A route below minimum reserve must warn.
- Cheap route cannot choose a low-confidence unsafe stop just because it is cheaper.
- Urgent plan should prefer nearby compatible chargers and show alternatives.

## Backend Errors

- Invalid route-plan payload returns a structured error.
- Unauthenticated route-plan access returns `401`.
- Missing or invalid CSRF on session-mutating endpoints returns `403`.
- Healthcheck remains independent from database readiness when possible.
- Readiness fails when authorized charger data with connectors has not been imported.
- Production URL configuration does not mount Django Admin unless explicitly enabled.
- Production settings reject non-HTTPS CORS and CSRF origins.

## Acceptance Commands

- Backend tests: `cd backend && .venv/bin/python -m pytest`.
- Frontend tests: `npm run test`.
- Frontend lint: `npm run lint`.
- Frontend build: `npm run build`.
- Healthcheck: `curl http://localhost:8000/api/health`.
- Readiness: `curl http://localhost:8000/api/ready`.

## Current Automated Coverage

- `/api/health` status.
- `/api/ready` returns `503` without authorized charger data and `200` after importing authorized charger data.
- Anonymous `/api/conversation/message` stores validated A2UI blocks in the Django session.
- The PWA quick-start flow posts free-form intents to `/api/conversation/message`, not the typed route-planning endpoint.
- A2UI registry and unknown-type validation.
- Account registration, current-user lookup, logout, and CSRF rejection.
- Auth register/login responses refresh the frontend CSRF token before follow-up unsafe requests.
- Account email validation, password validation, persisted failed-login throttling, and expired throttle cleanup.
- Production settings reject insecure origins, missing or invalid route-provider configuration, invalid OSRM timeouts, and default admin exposure.
- Vehicle profile creation, update, user scoping, and CSRF rejection.
- New vehicle profiles return blank/null vehicle state instead of inferred EV defaults.
- Authorized EV catalog import validation, updates, dry-run, and rejection of sample/mock/test sources.
- FuelEconomy.gov vehicle import maps current no-key EPA BEV range and efficiency data without inventing missing charging specs.
- Chargeprice JSON:API vehicle import maps maintained provider data into the internal catalog.
- Vehicle catalog freshness command prefers upstream source freshness over local import time before production use.
- Vehicle catalog API exposes only active vehicles from authorized sources.
- Vehicle profile can copy known characteristics from an authorized catalog vehicle.
- Authorized charger import validation and rejection of sample/mock/test sources.
- Authorized charger import dry-run validates counts and rejects unauthorized sources without writes.
- Nearby charger filtering by connector, power, availability, and radius.
- Station detail rejects sample and unauthorized charger records.
- Provider-backed EV route planning with persisted vehicle profile data and persisted non-sample station data.
- Provider-backed chargers-only route exploration with authorized station data and no vehicle assumptions.
- Route scoring uses real availability timestamps and does not infer available connectors from unknown status.
- Saved route-plan history scoped to the authenticated user.
- Routing provider failure and missing station-data errors.
- Routing provider rejects incomplete distance, duration, or geometry instead of fabricating route data.
- Manual charger records default to unauthorized data sources and unknown EVSE status.
- Feedback creation and unknown feedback-kind validation.
- Feedback authentication, CSRF, and route-plan ownership validation.
- Frontend shell rendering, anonymous conversation route-plan submission, and saved-plan feedback submission.
