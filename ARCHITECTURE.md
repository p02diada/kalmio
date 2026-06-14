# Architecture

## System Shape

Kalmio uses a React/Vite PWA frontend and a Django/Ninja backend. The agent owns conversational reasoning: intent, tool choice, and A2UI component choice. The backend owns provider integration, charger data access, planning logic, tool execution, validation, and safety boundaries. The frontend owns the host app, native rendering of allowlisted A2UI blocks, and local UI state.

## Frontend

- `frontend/src/App.tsx`: TanStack Router route definitions for `/`, `/chat`, `/activity`, `/settings`, plus the app shell, quick-start home, and chat host.
- `frontend/src/components`: A2UI components and shared UI primitives.
- `frontend/src/lib/api`: typed API client.
- `frontend/src/lib/a2ui`: block types, renderer, fallback.
- `frontend/src/lib/settings.ts`: shared planning preference types and defaults.
- `frontend/Dockerfile`: multi-stage build with a Vite dev target and an Nginx production target. Production API calls default to same-origin paths unless `VITE_API_BASE_URL` is set at build time.

## Backend

- `backend/config`: Django settings and URLs.
- `backend/api`: Django Ninja API composition.
- `backend/charging`: operators, stations, EVSEs, connectors, tariffs, availability.
- `backend/routing`: conversation agent adapter, A2UI validation, route provider integration, anonymous session route conversations, persisted-account route planning, and charger scoring.
- `backend/feedback`: authenticated feedback endpoint scoped to saved route plans.
- `backend/accounts`: Django session authentication endpoints for account creation, login, logout, CSRF cookie setup, and current-user lookup.

## A2UI Contract

Every UI block has:

- `type`: allowlisted component name.
- `version`: schema version.
- `id`: stable block id.
- `props`: component-specific payload.

The chat surface renders only allowlisted component types from `A2UI_COMPONENTS.md`. Unknown frontend blocks render a fallback, and backend-generated blocks are validated before being stored in the Django session.

This is a local A2UI adapter shape for the current vertical slice. It is intentionally transport-independent so it can later map to official A2UI `createSurface`, `updateComponents`, and `updateDataModel` messages over JSONL/SSE, WebSocket, A2A, or AG-UI.

## `/api/conversation/message` Flow

1. Require a Django session and CSRF validation.
2. Receive natural-language user input from the chat host.
3. Invoke the configured conversation agent mode:
   - `local`: deterministic local agent adapter for development and tests.
   - `codex`: local Codex CLI adapter using `KALMIO_CODEX_MODEL`, with an internal Django tool loop.
4. In Codex mode, the model receives the useful conversation transcript, the allowed internal tools, and the A2UI catalog described by purpose. The model may return either final A2UI blocks or an allowlisted tool call. Django validates and executes each tool, appends the validated result to the turn history, and asks Codex again until it returns final A2UI or reaches `KALMIO_CODEX_MAX_TOOL_CALLS` (default 3). Codex chooses intent, tool calls, and UI blocks. Django validates component allowlist, structural props, data traceability, and supported actions; it does not choose components from regex or intent rules. Contract violations get one repair request back to Codex with concrete safety/data issues. Unknown tools, repeated identical calls, exhausted budgets, failed repairs, or missing final A2UI return minimal fallback A2UI to avoid loops.
5. Current internal tools are `resolve_location`, `search_destination_chargers`, and `plan_route`. They are Python functions inside Django, not MCP tools, so they keep session, data-source, provider, and authorization boundaries inside the backend.
6. Domain facts come only from authorized charger data, route provider responses, internal tool outputs, or explicit user input.
7. Validate generated A2UI block types against the allowlist and normalize known Codex prop variants before rendering. Structured station data, route metrics, coordinates, costs, availability, and actions are checked against tool results or previously validated session blocks.
8. Store the latest A2UI blocks in the Django session and return `{blocks}` to the frontend.
9. If provider-backed routing or authorized charger data is unavailable, return explicit A2UI risk/error blocks or a structured backend error. Do not fabricate stations, coordinates, vehicle state, price, or availability. A Codex failure does not fall through to the deterministic local parser in normal Codex mode; the fallback is minimal and honest.

`GET /api/conversation/messages` returns the active A2UI block list for the current session, initializing it with an assistant prompt and preference chips when empty. `DELETE /api/conversation` clears both the route-plan session result and the A2UI chat blocks.

## `/api/conversation/route` Flow

`/api/conversation/route` remains a typed route-planning endpoint and may be used as a tool behind the conversation agent. The chat host should use `/api/conversation/message` rather than hardcoding route-planning decisions in the frontend.

1. Require a Django session and CSRF validation.
2. Receive origin and destination coordinates, route-corridor radius, and explicit planning preferences.
3. Request distance, duration, and geometry from the configured routing provider.
4. Query persisted charger data from `Station`, `EVSE`, `Connector`, `Tariff`, and `ReliabilityScore`.
5. With explicit vehicle characteristics, score compatible stations near sampled route geometry and return `planning_level="ev_plan"`.
6. Without explicit vehicle characteristics, return `planning_level="chargers_only"` and score authorized stations near the route without calculating autonomy.
7. Store the latest plan response in the Django session under the active conversation.
8. Return the best stop, alternatives, optional energy estimate, optional arrival battery, and explicit warnings.
9. Return `424` when the route provider is unavailable and `422` when compatible station data is unavailable instead of inventing a result.

`GET /api/conversation` returns the active route conversation for the current session or `404` when none exists. Anonymous session conversations are not persisted to account history and cannot receive saved-plan feedback.

## `/api/plans/route` Flow

1. Require an authenticated Django session.
2. Receive origin and destination coordinates plus route-corridor radius from the authenticated frontend.
3. Use conservative default planning preferences.
4. Request distance, duration, and geometry from the configured routing provider.
5. Query persisted charger data from `Station`, `EVSE`, `Connector`, `Tariff`, and `ReliabilityScore`.
6. Return `planning_level="chargers_only"` without saving history while account vehicle profiles are disabled.
7. Persist only future full EV plans as `RoutePlan` records owned by `request.user`.
9. Return the best stop, alternatives, optional energy estimate, optional arrival battery, and explicit warnings.
10. Return `401` when unauthenticated, `424` when the route provider is unavailable, and `422` when compatible station data is unavailable instead of inventing a result.

## `/api/plans/route` History

`GET /api/plans/route` returns the latest persisted plans for the authenticated account. The frontend no longer uses a local device identifier for route-plan access control. Saved route plans are distinct from anonymous session conversations.

## `/api/feedback`

`POST /api/feedback` requires an authenticated session, CSRF validation, and a `route_plan_id` owned by the current user. Anonymous or cross-account feedback is rejected.

## EV Planner

The planner estimates energy from route distance:

`energy_kwh = distance_km * consumption_kwh_per_100km / 100 * safety_factor`

It must respect minimum reserve. If a plan cannot respect reserve, it must warn explicitly and lower confidence.

## Providers And Adapters

The production route-planning path uses:

- `OsrmRouteProvider`, configured with `KALMIO_OSRM_BASE_URL`.
- Persisted charger data loaded from authorized sources.
- Explicit provider/data errors when a real answer cannot be produced.

Future adapters can target Valhalla, GraphHopper, MapLibre-compatible tiles, or additional authorized charger data providers.

## Production Runtime

- `KALMIO_ENV=production` disables development defaults and fails startup unless `DJANGO_SECRET_KEY`, explicit hosts, CORS origins, CSRF trusted origins, and PostGIS are configured.
- Production rejects non-HTTPS entries in `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`.
- Production fails startup unless `KALMIO_OSRM_BASE_URL` is an absolute HTTP(S) URL pointing to an explicit production routing provider; the public OSRM development endpoint is not accepted in production.
- Production enables secure cookies, HTTPS redirect, HSTS, content-type nosniff, and proxy HTTPS awareness by default.
- OpenAPI and Swagger docs are disabled by default when `KALMIO_ENV=production`; set `KALMIO_ENABLE_API_DOCS=true` only for controlled internal environments.
- Django Admin is not mounted by default in production. Enable it explicitly with `KALMIO_ENABLE_ADMIN=true` and a controlled `KALMIO_ADMIN_PATH` only when needed operationally.
- The backend container defaults to Gunicorn. The frontend production container serves static assets through Nginx with SPA fallback. `docker-compose.yml` remains a local development profile and intentionally uses `runserver` plus the Vite dev server.
- The frontend production Nginx config sends security headers for clickjacking, MIME sniffing, referrer policy, feature permissions, and a restrictive CSP while allowing same-origin PWA assets and HTTPS API connections. `/api/*` is explicitly excluded from the SPA fallback so proxy mistakes fail as JSON `404` instead of returning `index.html`.
- Production frontend builds accept same-origin API calls or absolute HTTPS `VITE_API_BASE_URL` values only; ambiguous relative hosts and HTTP API origins fail fast.
- The service worker excludes `/api/*` from navigation fallback and has no runtime API caching; authenticated data must come from live backend responses.
- Frontend API clients validate critical backend response shapes at runtime before updating UI state. Malformed JSON is treated as an explicit contract error instead of being rendered as partial data.
- `backend/requirements.txt` contains runtime dependencies only. Local development and CI install `backend/requirements-dev.txt`, which layers pytest tooling on top.
- Public auth endpoints validate email/password input, require CSRF on unsafe methods, and throttle repeated failed register/login attempts through persisted hashed throttle keys.
- Backend logging writes container-friendly lines to stdout/stderr with `request_id`. `RequestIDMiddleware` preserves safe incoming `X-Request-ID` values, generates one when missing or invalid, and returns it on every response.
- `/api/health` is a lightweight liveness check. `/api/ready` is the production readiness gate and returns `503` until database access, migrations, route-provider configuration, and authorized charger data with connectors are all valid. Readiness reports the configured provider type but does not expose internal provider URLs.

## Data Strategy

Production charger data enters through `python manage.py import_chargers <csv-or-json>`. Operators can run `python manage.py import_chargers <csv-or-json> --dry-run` to validate counts and authorization rules without database writes. The importer rejects records marked as sample or fixture data and stores imported stations with `DataSource.is_authorized=true` and `Station.is_sample_data=false`.

No fictitious charger seed is shipped. API selectors exclude sample records and unauthorized sources. No production REVE scraping or unauthorized real REVE data. Local development can use `scrape_reve_dev` to create a temporary REVE cache for tests; the command is disabled when `DEBUG=false` unless explicitly overridden in an isolated non-production environment.

The implementation stores station latitude and longitude in portable decimal columns so local SQLite tests can run without GDAL installed on the host. Production still requires a PostGIS database backend, but the current charger lookup path uses persisted station coordinates and a portable Haversine selector until database-backed distance queries are implemented.

## Technical Decisions

- Django Ninja provides OpenAPI and Pydantic-style schemas.
- PostGIS is required for production database deployments and remains the long-term geospatial base.
- SQLite may be used only for narrow test commands that do not exercise geospatial queries.
- TanStack Query handles server state.
- TanStack Router handles typed frontend routing.
- shadcn/ui provides component primitives, not visual identity.
- Charger APIs currently use persisted non-sample station data and a Haversine selector for portability. A future upgrade can replace this with database distance queries against PostGIS-backed geospatial columns.
