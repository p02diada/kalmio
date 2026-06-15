# Kalmio

Kalmio is a mobile-first PWA assistant for EV drivers. It helps plan charging stops through provider-backed routing and authorized charger data.

Claim: "Viaja sin ansiedad de carga."

## Current Status

The current build includes the React/Vite PWA, Django/Ninja API, anonymous session-based route conversations, authenticated accounts, route-plan history/feedback plumbing, PWA assets, and a provider-backed route-planning flow that uses OSRM plus persisted authorized station data. Vehicle profiles and vehicle catalogs are intentionally removed, but a conversation can still provide explicit vehicle characteristics for one plan.

## Local Setup

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py runserver
```

Run backend tests:

```bash
cd backend
source .venv/bin/activate
pytest
```

Run frontend checks:

```bash
cd frontend
npm run lint
npm run test
npm run build
```

Run the full reproducible gate set in containers:

```bash
docker compose -f docker-compose.ci.yml build backend-ci
docker compose -f docker-compose.ci.yml run --rm backend-ci
docker compose -f docker-compose.ci.yml run --rm frontend-ci
docker compose -f docker-compose.ci.yml down -v --remove-orphans
```

The backend CI service runs Django deployment checks inside the backend image, where GDAL/GEOS/PostGIS libraries are installed, then verifies migrations and runs pytest against a PostGIS database. The frontend CI service runs install, lint, tests, and production build in a clean Node container. GitHub Actions uses the same compose file.

Frontend API configuration:

```bash
VITE_API_BASE_URL=https://api.example.com npm run build
```

If `VITE_API_BASE_URL` is omitted, local development uses `http://127.0.0.1:8000`; production builds use same-origin API paths such as `/api/auth/me`. Use an explicit `VITE_API_BASE_URL` only when the PWA and backend are served from different origins.

Para pruebas e2e con Cloudflare Tunnel (dominios distintos), aplica además:

```bash
export CSRF_TRUSTED_ORIGINS="https://TU_FRONTEND_TUNNEL.trycloudflare.com"
export CORS_ALLOWED_ORIGINS="https://TU_FRONTEND_TUNNEL.trycloudflare.com"
export DJANGO_ALLOWED_HOSTS=".trycloudflare.com,localhost,127.0.0.1"
export SESSION_COOKIE_SAMESITE=None
export CSRF_COOKIE_SAMESITE=None
export SESSION_COOKIE_SECURE=true
export CSRF_COOKIE_SECURE=true

VITE_API_BASE_URL=https://TU_BACKEND_TUNNEL.trycloudflare.com
```

`SESSION_COOKIE_SAMESITE=None` y `CSRF_COOKIE_SAMESITE=None` son necesarios para enviar cookies por `fetch` entre dominios distintos (con `credentials: include`) cuando frontend y backend no comparten origen.

Docker:

```bash
docker compose up --build
```

The Compose file is for local development. Production must run the backend image with `KALMIO_ENV=production`, `DJANGO_DEBUG=false`, a real `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS`, HTTPS origins in `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`, `KALMIO_DB_ENGINE=postgis`, and an explicit absolute HTTP(S) production `KALMIO_OSRM_BASE_URL`. The backend image defaults to Gunicorn; the frontend image builds static assets and serves them with Nginx; OpenAPI/Swagger docs are disabled by default in production; do not use `runserver`, the Vite dev server, or the public OSRM development endpoint outside local development.

Production compose example:

```bash
cp .env.production.example .env.production
# Edit .env.production with real secrets, hosts, HTTPS origins, and routing provider.
docker compose --env-file .env.production -f docker-compose.production.yml build
docker compose --env-file .env.production -f docker-compose.production.yml run --rm backend python manage.py migrate --noinput
docker compose --env-file .env.production -f docker-compose.production.yml up -d
curl https://api.kalmio.example/api/ready
```

`docker-compose.production.yml` is an operational example, not a managed hosting substitute. It requires real secrets through `.env.production`, refuses missing critical variables, rejects placeholder secrets at Django startup, builds the frontend with an explicit HTTPS `VITE_API_BASE_URL`, runs the backend with Gunicorn, and uses PostGIS. If you replace the bundled database with managed Postgres, set `POSTGRES_SSLMODE=require`.

Authentication endpoints validate email/password input and throttle repeated failed register/login attempts through persisted hashed throttle keys. Tune `KALMIO_AUTH_THROTTLE_LIMIT` and `KALMIO_AUTH_THROTTLE_WINDOW_SECONDS` per environment.

Backend logs are written to stdout/stderr for container collection and include `request_id`. Incoming safe `X-Request-ID` values are preserved; otherwise the backend generates one and returns it on every response. Tune `KALMIO_LOG_LEVEL` per environment.

Django Admin is enabled by default only outside production. In production it is not mounted unless `KALMIO_ENABLE_ADMIN=true`; set `KALMIO_ADMIN_PATH` to a controlled path ending in `/` if an operational admin surface is required.

Healthcheck and readiness:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ready
```

`/api/health` is a lightweight liveness check. `/api/ready` returns `503` until the database is reachable, migrations are applied, the route provider is configured, and at least one authorized non-sample charger station with connectors has been imported.

Para un chequeo e2e de conversación sin usar navegador:

```bash
cd backend
python scripts/smoke_conversation.py --api-base http://127.0.0.1:8000
```

El script valida:

- `GET /api/ready`
- `GET /api/auth/csrf`
- `GET /api/conversation/messages`
- `POST /api/conversation/message` (flujo A2UI anónimo)
- `DELETE /api/conversation` (limpieza del estado)

Es útil antes de habilitar el endpoint público para confirmar que la cadena de conversación está operativa.

The chat screen uses `/api/conversation/message`. The backend stores A2UI blocks in the Django session, validates component types against the local catalog, and decides whether to clarify, search destination charging, or call route planning tools. Tune the local agent mode with:

- `KALMIO_CONVERSATION_AGENT_MODE=local` for deterministic local development.
- `KALMIO_CONVERSATION_AGENT_MODE=codex` to use the local Codex CLI adapter.
- `KALMIO_CODEX_COMMAND` (default `codex`)
- `KALMIO_CODEX_MODEL` (default `gpt-5.4-mini`)
- `KALMIO_CODEX_TIMEOUT_SECONDS` (default `60`)
- `KALMIO_CODEX_MAX_TOOL_CALLS` (default `3`)

In `codex` mode, Codex does not access the database or providers directly. It can request a bounded sequence of allowlisted Django tool calls (`resolve_location`, `search_destination_chargers`, or `plan_route`), Django executes them, and Codex receives only the validated tool results to compose final A2UI blocks. Codex chooses the UI blocks that best fit the user request and tool results; Django validates the catalog, factual constraints, and semantic obligations. If an allowlisted tool returns no usable data, Codex receives that failure and must answer honestly from the validated state. If the final A2UI is incomplete, Django asks Codex for one repair with the concrete contract issues. If Codex asks for an unknown tool, repeats the same tool call, exceeds `KALMIO_CODEX_MAX_TOOL_CALLS`, fails repair, or fails to return final A2UI, the backend returns safe fallback A2UI instead of executing arbitrary behavior.

Codex receives the available conversation context for each turn so it can resolve natural follow-ups; Django should validate the resulting structured tool arguments instead of parsing natural phrasing with feature-specific regexes.

Conversation endpoints are throttled by session/IP to reduce abuse. Tune in settings:

- `KALMIO_ROUTE_CONVERSATION_THROTTLE_LIMIT` (default `30`)
- `KALMIO_ROUTE_CONVERSATION_THROTTLE_WINDOW_SECONDS` (default `120`)

Clear the current in-session conversation:

```bash
curl -b cookies.txt -X DELETE -H "X-CSRFToken: $CSRF_TOKEN" \
  http://localhost:8000/api/conversation
```

Create an anonymous session and CSRF token, then send a free-form message to the agent:

```bash
curl -c cookies.txt http://localhost:8000/api/auth/csrf
CSRF_TOKEN=$(grep csrftoken cookies.txt | awk '{print $7}')
curl -b cookies.txt -H 'Content-Type: application/json' -H "X-CSRFToken: $CSRF_TOKEN" \
  -d '{"text":"Quiero ver cargadores cerca de un hotel en Valencia"}' \
  http://localhost:8000/api/conversation/message
curl -b cookies.txt http://localhost:8000/api/conversation/messages
```

The response shape is:

```json
{"blocks":[{"id":"...","type":"AssistantMessage","version":1,"props":{"text":"..."}}]}
```

Create a typed route plan directly only when testing the backend route-planning tool outside the chat host. The PWA chat does not call this endpoint directly; it sends free-form text to `/api/conversation/message` and lets the backend agent decide when route planning is appropriate:

```bash
curl -b cookies.txt -H 'Content-Type: application/json' -H "X-CSRFToken: $CSRF_TOKEN" \
  -d '{"origin":{"lat":37.8882,"lon":-4.7794},"destination":{"lat":39.4699,"lon":-0.3763},"origin_label":"Córdoba","destination_label":"Valencia","corridor_radius_km":35,"vehicle":{"model":"Mi EV","battery":58,"usable_battery_kwh":64,"consumption_kwh_per_100km":17.8,"connector":"CCS2","max_charge_kw":150},"preferences":{"reserve_min_percent":20,"prefer_fast":false,"prefer_cheap":false,"prefer_low_stress":true,"avoid_single_connector":true,"prefer_services":true,"prefer_large_hubs":true}}' \
  http://localhost:8000/api/plans/route
```

Anonymous A2UI chat blocks are stored only in the Django session and are not added to account history. Route calculations require CSRF, a reachable routing provider, and authorized charger records. Without vehicle characteristics, Kalmio only shows chargers near the route and does not calculate autonomy, arrival battery, or optimal charging stops.

Create a local account when you want route-plan history and feedback:

```bash
curl -b cookies.txt -c cookies.txt -H 'Content-Type: application/json' -H "X-CSRFToken: $CSRF_TOKEN" \
  -d '{"email":"driver@example.com","password":"safe-password-123"}' \
  http://localhost:8000/api/auth/register
CSRF_TOKEN=$(grep csrftoken cookies.txt | awk '{print $7}')
```

Prepare a route from an authenticated account. Until EV planning returns, this produces a non-persisted charger exploration response:

```bash
curl -b cookies.txt -H 'Content-Type: application/json' -H "X-CSRFToken: $CSRF_TOKEN" \
  -d '{"origin":{"lat":37.8882,"lon":-4.7794},"destination":{"lat":39.4699,"lon":-0.3763},"origin_label":"Córdoba","destination_label":"Valencia","corridor_radius_km":35}' \
  http://localhost:8000/api/plans/route
```

The saved-plan endpoint currently returns a non-persisted `planning_level: "chargers_only"` response because account vehicle profiles are disabled. It returns `424` if the routing provider cannot be reached or `422` if no persisted station data exists near the route corridor.

List saved route plans for the authenticated account:

```bash
curl -b cookies.txt 'http://localhost:8000/api/plans/route'
```

Feedback is rejected unless the plan belongs to the current account.

Import authorized charger data:

```bash
cd backend
source .venv/bin/activate
python manage.py import_chargers ./path/to/authorized-chargers.csv --dry-run
python manage.py import_chargers ./path/to/authorized-chargers.csv
```

Accepted formats are CSV and JSON. Use `--dry-run` to validate counts and authorization rules without writing to the database. The import rejects records marked as sample data or non-provider fixtures. Required fields are `source_name`, `operator_name`, `station_external_id`, `station_name`, `latitude`, `longitude`, `evse_uid`, `connector_type`, and `max_power_kw`.

For local development only, you can build a temporary REVE cache from the public map endpoints and import it into your local database:

```bash
cd backend
source .venv/bin/activate
python manage.py scrape_reve_dev --output .dev-data/reve-chargers.json --page-size 25
python manage.py import_chargers .dev-data/reve-chargers.json --replace-source
```

`scrape_reve_dev` is disabled when `DEBUG=false` unless `KALMIO_ALLOW_REVE_DEV_SCRAPE=1` is explicitly set for an isolated non-production environment. It caches raw REVE pages under `.dev-data/reve-pages`, so a rate-limited run can be repeated later without refetching completed pages. REVE currently accepts up to `--page-size 25`; larger values are rejected by the provider. Use `python manage.py scrape_reve_dev --offline --output .dev-data/reve-chargers.json --page-size 25` to rebuild the import file from cached pages only. The raw cached pages are ignored by git; `.dev-data/reve-chargers.json` can be committed as a development fixture, but is not approved production data.

## Product Boundaries

Kalmio does not implement native apps, Flutter, CarPlay, Android Auto, charger reservations, payments, turn-by-turn navigation, community features, direct vehicle integration, production REVE scraping, or unauthorized real REVE data.

The home screen is a quick-start launcher and the chat screen uses `/api/conversation/message`. The frontend does not decide whether to calculate a route. The backend conversation agent asks for missing critical data, searches authorized charger data when possible, or calls provider-backed route planning only when it has enough route context. Authenticated saved plans remain under `/api/plans/route` and `Planes`. Kalmio does not fabricate recommendations when provider or station data is missing.

## Key Docs

- `PRD.md`
- `ARCHITECTURE.md`
- `ROUTING.md`
- `DESIGN.md`
- `docs/CODEX_AI.md`
- `docs/VEHICLE_DATA_SOURCES.md`
- `A2UI_COMPONENTS.md`
- `DATA_MODEL.md`
- `TEST_CASES.md`
- `AGENTS.md`
