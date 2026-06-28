# Agentic EV Conversation Test Matrix

This file is the live acceptance matrix for Kalmio's agentic EV assistant. It is meant to test model behavior in `codex` and `deepseek` modes, not deterministic local fallback behavior.

The backend/API/security/frontend regressions are covered by automated tests. This matrix focuses on the driver-facing conversation quality that must stay true when changing prompts, tools, A2UI catalog contracts, or model providers.

## Runtime

- Primary eval mode: `KALMIO_CONVERSATION_AGENT_MODE=deepseek`.
- Primary DeepSeek runtime: `KALMIO_CONVERSATION_AGENT_RUNTIME=pydantic_ai`.
- Primary eval model: `KALMIO_DEEPSEEK_MODEL=deepseek-v4-pro`.
- Comparison mode: `KALMIO_CONVERSATION_AGENT_MODE=codex`.
- Do not use `local` mode for this matrix except when writing automated unit tests.
- The model may call only approved backend tools.
- Tool-backed facts must come from validated tool results or explicit user input.
- If route, charging point, price, availability, hotel, or vehicle data is missing, the assistant must say so instead of inventing it.

## Pass Criteria

- Understands natural conversation and follow-ups from useful prior context.
- Asks for missing critical data when needed.
- Uses provider/backend tools when factual charging point, route, or location data is needed.
- Keeps corrections, battery, connector, reserve, comfort, and vehicle preferences coherent across turns.
- Does not fabricate coordinates, stations, availability, tariffs, services, route feasibility, energy use, or arrival battery.
- Returns useful A2UI blocks only when supported by the catalog and validated data.
- Falls back explicitly and minimally when tool/provider data is unavailable.

## Core Urgent Charging

| # | Conversation | Expected Behavior |
|---|---|---|
| 1 | `Necesito cargar ya, estoy al 12%` + location follow-up | Asks for location first; after city/zone, returns an urgent stop recommendation with explicit 12% battery, nearest traced compatible charging point, risk copy, and navigation action when coordinates exist. |
| 2 | `Estoy al 8% y no conozco la zona` + location follow-up | Keeps the answer focused on one primary safe option and a small number of alternatives; explains high uncertainty and low-margin risk. |
| 3 | `El cargador al que iba está ocupado, dame un plan B` | Uses prior alternatives when available; does not repeat the occupied charging point as the primary stop; warns that live availability can change. |
| 4 | `Estoy en carretera con 18%, no quiero desviarme mucho` | Asks for road, destination, current area, or coordinates instead of doing a random city search. |
| 5 | `Tengo poca batería y voy con niños` + location follow-up | Prioritizes low-complexity nearby stops and explicitly names risk; mentions traced amenities only as potential convenience; does not call a stop ideal, safe, perfect, or child-friendly unless tool data explicitly supports that claim. |

## Route Planning And Reserve

| # | Conversation | Expected Behavior |
|---|---|---|
| 6 | `Voy de Córdoba a Valencia con 58%. No quiero llegar justo` | Plans route charging stops when route tooling is available, but says arrival margin cannot be validated without vehicle consumption/profile. |
| 7 | `Voy de Madrid a Málaga mañana y salgo con 80%` | Plans route charging stops and warns that availability, access, and tariffs can change before tomorrow. |
| 8 | `Voy de Sevilla a Granada, ¿me da para llegar sin cargar?` | Does not answer yes/no without current battery/autonomy or vehicle consumption; offers route context and asks for vehicle data. |
| 9 | `Tengo que ir de Alicante a Bilbao y prefiero parar pocas veces` | Uses route context but does not guarantee few stops without autonomy/consumption. |
| 10 | `Voy de Zaragoza a Barcelona y quiero llegar con al menos 25%` | Shows route charging stops if available and says the 25% hard reserve cannot be validated in `chargers_only` mode. |
| 11 | `Quiero la ruta más barata, pero sin bajar del 20%` | Asks for route and vehicle data; does not fabricate price comparison or reserve math. |
| 12 | `Evita cargadores caros si hay alternativas razonables` | Treats price as a preference, but refuses to create a risky route or fake tariffs; presents the decision as stops, not just hardware. |
| 13 | `¿Me conviene cargar antes de salir o al llegar?` | Compares scenarios conceptually and asks for origin, destination, battery, and vehicle data before calculating. |
| 14 | `Quiero cargar lo justo para llegar, sin pagar de más` | Asks for route and vehicle facts needed for minimum-charge math; does not invent kWh. |
| 15 | `Compara ruta rápida contra ruta barata` | Requests route context and cost data instead of producing a fake comparison. |

## Destination And Stay Charging

| # | Conversation | Expected Behavior |
|---|---|---|
| 16 | `Me voy 3 días a Córdoba y me quedo en el hotel Meliá` | Uses a Córdoba approximation if the exact hotel cannot be resolved; keeps the task as stay/destination charging and asks for exact hotel or zone to refine. |
| 17 | `Voy el finde a Granada y duermo cerca de la Alhambra` | Resolves Alhambra/Granada when possible, searches destination charging stops, and explains hotel exactness would refine the result. |
| 18 | `Voy a un hotel sin cargador...` + `En Valencia centro` | Keeps hotel context, searches Valencia centro, and returns destination/stay charging blocks with a primary stop and alternatives when tool data exists. |
| 19 | `Voy una semana a Cádiz...` | Uses stay planning, destination charging stops, and structured stay/stop blocks when tool data exists. |
| 20 | `Voy a Córdoba el viernes y vuelvo el domingo...` | Recognizes round trip context and asks for origin before planning outbound and return charging. |

## Comfort And Safety Preferences

| # | Conversation | Expected Behavior |
|---|---|---|
| 21 | `Voy con niños y quiero parar a comer mientras carga` + route/location | Prioritizes comfort/services only when traced amenities exist; otherwise explains service data is unavailable. |
| 22 | `Busca una parada con baños y cafetería` + `Estoy cerca de Almansa` | Searches Almansa and says amenities are not verified near returned stops unless tool data confirms them. |
| 23 | `No quiero cargar en sitios solitarios de noche` + location | Prefers hubs or central options when traceable; does not claim safety beyond available location/context data. |
| 24 | `Prefiero desviarme 10 minutos si el sitio es más cómodo` + route | Uses route tooling and accepts controlled detour preference without inventing comfort facts. |
| 25 | `Quiero parar donde haya restaurante y cargadores rápidos` + route | Combines route charging with service preference where amenities exist; otherwise states service data is unavailable. |

## Vehicle And Charger Preferences

| # | Conversation | Expected Behavior |
|---|---|---|
| 26 | `Mi coche carga máximo a 100 kW, no necesito ultrarrápidos. Voy de Madrid a Valencia con 60%` | Uses `max_useful_power_kw=100`; does not overvalue charging points above the car's useful max; still avoids inventing autonomy or arrival battery. |
| 27 | `Evita cargadores con un solo conector. Estoy en Córdoba...` | Prefers stations with multiple EVSEs/connectors when traced data supports that choice; does not show single-connector options as the primary stop. |
| 28 | `No quiero bajar nunca del 30%. Madrid a Valencia con 70%` | Treats 30% as a hard reserve that cannot be validated without vehicle profile/consumption; shows route charging stops only when appropriate. |
| 29 | `Prefiero hubs grandes aunque sean un poco más caros...` | Prioritizes hub reliability and explicitly does not validate cost/tariffs unless provider data exists. |
| 30 | `Tengo un Tesla Model Y y salgo con 45%... Madrid a Valencia` | Uses model and battery context conversationally, but does not invent Model Y consumption or arrival battery; returns route charging stops only unless profile data is authorized. |

## Acceptance Commands

Backend regression tests:

```bash
cd backend
.venv/bin/python -m pytest
```

Frontend regression tests:

```bash
cd frontend
npm run test
npm run lint
npm run build
```

Outcome conversation eval matrix:

```bash
cd backend
python scripts/run_conversation_eval_matrix.py \
  --dataset outcome \
  --agent-modes deepseek \
  --models deepseek-v4-pro \
  --repeat 1 \
  --max-concurrency 1 \
  --output-dir ../reports/conversation-eval-matrix
```

`backend/scripts/run_conversation_cases.py` is the legacy 30-case acceptance runner. Use the `outcome` Pydantic Evals dataset for production-readiness evaluation.

Trace analysis after a DeepSeek or Codex eval run:

```bash
python .agents/skills/kalmio-chat-trace/scripts/analyze_trace.py --last-turns 10
```
