# Agentic EV Codex Iteration - 2026-06-15

Manual runs used `KALMIO_CONVERSATION_AGENT_MODE=codex` with the local Codex CLI and authorized charger data from the development SQLite database.

## Initial Findings

- A initially asked for location correctly, but sometimes rendered a generic `StationDetailCard` station name while text mentioned a real station.
- B initially failed the correction turn with a generic fallback instead of searching Valencia.
- C could answer the follow-up when prior Córdoba results were valid, but became unstable when the prior turn fell back.
- D initially fell into generic fallback for `Paseo de la Victoria de Córdoba`.
- F initially asked for the exact hotel too rigidly instead of offering a Valencia approximation.

Probable causes:

- Prompt lacked concrete correction/follow-up examples.
- Allowed tool failures were cut off by backend fallback before Codex could explain them.
- Location resolution did not normalize accents.
- Codex emitted station-name prop variants for `StationDetailCard`, but the normalizer did not consistently map them to the station identity expected by validation.
- Useful vehicle facts from earlier user text were not summarized compactly for Codex.

## Changes Made

- Updated Codex defaults to `gpt-5.4-mini` and timeout to 60 seconds.
- Added EV-specific prompt examples for urgent charging, corrections, POI approximations, routes without consumption, and hotel charging.
- Added compact history summary for explicit battery and connector facts.
- Let failed allowlisted tools return to Codex for a contextual final answer; unknown tools still use safe backend fallback.
- Normalized accented location queries in `resolve_location`.
- Normalized `StationDetailCard` variants: `name`, `stationName`, and `chargerName`.
- Added repair issue when `StationDetailCard.name`/`stationName` stays generic despite traced station results.

## Final Manual Transcripts

### A. Carga urgente con ubicación posterior

Usuario: `Necesito cargar ya`

Respuesta: pide solo ubicación actual, ciudad, zona o coordenadas. No pide destino.

Usuario: `En Córdoba`

Respuesta final: usa Córdoba como ubicación aproximada, muestra `StationDetailCard` con `BALLENOIL-ES336090-COLON` a 0.3 km y `RiskExplanationCard` sobre datos autorizados, acceso, tarifa y disponibilidad.

Evaluation: passes. Context and follow-up are understood; no destination requested; charger facts are tool-backed.

### B. Corrección de ubicación

Usuario: `Necesito cargar ya. Estoy en Córdoba con un 18% y CCS2`

Respuesta: busca Córdoba/CCS2 and returns nearby traced charger data.

Usuario: `Me equivoqué, estoy en Valencia centro`

Respuesta final: switches to Valencia, says `Con 18% y CCS2`, recommends `E-V-Valencia-091`, and does not keep Córdoba as current location.

Evaluation: passes. Correction is honored and prior battery/connector context is retained.

### C. Pregunta por fallo anterior

Usuario: `Necesito cargar ya`

Respuesta: asks for current city/zone/coordinates only.

Usuario: `En Córdoba`

Respuesta: returns Córdoba chargers including `BALLENOIL-ES336090-COLON`.

Usuario: `Por qué no encuentras nada en Córdoba? No hay cargadores?`

Respuesta final: says there are chargers in Córdoba and references previously shown authorized options; explains limits as validation, authorized coverage, or unconfirmed access/tariff/availability.

Evaluation: passes. No contradiction and no invented stations.

### D. Zona concreta

Usuario: `Necesito cargar ya`

Respuesta: asks for location only.

Usuario: `Y en el Paseo de la Victoria de Córdoba?`

Respuesta final: says it cannot locate the exact street and uses Córdoba as an approximation; shows traced nearby chargers and risk/confirmation text.

Evaluation: passes. It attempts the known city, explains the approximation, and does not invent street coordinates.

### E. Ruta sin datos completos

Usuario: `Planifica una ruta tranquila de Madrid a Valencia, no conozco el consumo exacto`

Respuesta final: shows route-level distance/duration and traced chargers in route, but says it cannot calculate arrival battery, energy, or optimal stops without consumption.

Evaluation: passes. It uses route tooling without inventing autonomy or arrival battery.

### F. Hotel/destino

Usuario: `Voy a dormir en Valencia, busca cargadores cerca del hotel`

Respuesta final: uses Valencia as an approximate hotel reference, lists nearby authorized chargers, and asks for hotel or exact zone to refine.

Evaluation: passes. It does not convert the request into a route and stays honest about approximation.

## Second Iteration: Expanded EV Matrix

Manual runs were continued in Codex mode after the first commit. The goal of this pass was not just to pass tests: the final responses had to sound useful for a real driver with low battery and avoid backend-authored intent routing.

### Additional Findings

- Route answers with hard reserves sometimes showed route chargers while implying the reserve was satisfied. Cause: prompt did not make `planningLevel=chargers_only` limits strong enough.
- Hotel/stay follow-ups sometimes returned only text or a broad destination card even when traced chargers were available. Cause: prompt and prop normalizer did not encourage/extract structured destination/stay blocks.
- Comfort queries needed amenities, address and reliability in tool output; otherwise the agent could not explain why a stop was comfortable or admit missing service data.
- `Alhambra`, `Almansa`, `Málaga`, `Granada`, `Alicante`, `Bilbao`, `Zaragoza` and `Cádiz` were missing from the development resolver, so route-matrix tests hit avoidable tool failures.
- The "max 100 kW, no ultrarrápidos" case originally overvalued 240/400 kW chargers. Cause: the route tool had no safe structured preference for maximum useful charging power unless a complete vehicle profile existed.

### Additional Changes

- Expanded Codex prompt examples for low battery, plan B, corridor driving, future trips, cost limits, hard reserve constraints, stay planning, comfort/services and vehicle preferences.
- Added known development locations for the expanded matrix; this is still a bounded resolver, not arbitrary geocoding.
- Exposed traced charger facts from tools: amenities, address, reliability, connector/EVSE counts and scoring reasons.
- Added `preferences.max_useful_power_kw` to route planning. The agent can pass it when the driver states a maximum useful charge rate; backend scoring then avoids over-weighting power above that cap.
- Normalized safe A2UI prop variants for destination/stay blocks and extracted embedded stay stops into `StationDetailCard` / `StationList`.
- Added repair checks for missing explicit battery on `StationDetailCard` and vague `RiskExplanationCard` copy.

### Final A-F Rerun

- A: `Necesito cargar ya` -> asks only for current location. `En Córdoba` -> `StationDetailCard` for `BALLENOIL-ES336090-COLON`, alternatives and risk. Pass.
- B: `Necesito cargar ya. Estoy en Córdoba con un 18% y CCS2` -> Córdoba result with battery 18. `Me equivoqué, estoy en Valencia centro` -> switches to `E-V-Valencia-091`, keeps 18%/CCS2 and shows navigation actions. Pass.
- C: After Córdoba chargers, `Por qué no encuentras nada en Córdoba?` -> says there are chargers and explains authorized/imported coverage plus unconfirmed access/tariff/availability. Pass.
- D: `Y en el Paseo de la Victoria de Córdoba?` -> says it cannot locate the exact street and uses Córdoba as approximation with traced chargers. Pass.
- E: `Planifica una ruta tranquila de Madrid a Valencia, no conozco el consumo exacto` -> route summary and chargers only; explicitly does not validate arrival battery. Pass.
- F: `Voy a dormir en Valencia, busca cargadores cerca del hotel` -> uses Valencia as hotel approximation, returns `DestinationChargingCard`, recommended stop and alternatives. Pass.

### Expanded Matrix Transcripts

| # | Conversation tested | Final behavior | Evaluation |
|---|---|---|---|
| 1 | `Necesito cargar ya, estoy al 12%` + location follow-up | Asks for location first; after city, returns urgent card with explicit battery, nearest traced charger, risk and navigation when coordinates exist. | Pass |
| 2 | `Estoy al 8% y no conozco la zona` + location follow-up | Reduces to one primary charger and few alternatives; explains high uncertainty/low-margin risk. | Pass |
| 3 | `El cargador al que iba está ocupado, dame un plan B` | Uses prior alternatives and does not repeat the occupied charger; explains availability can change. | Pass |
| 4 | `Estoy en carretera con 18%, no quiero desviarme mucho` | Asks for road, destination or coordinates instead of doing a random city search. | Pass |
| 5 | `Tengo poca batería y voy con niños` + location follow-up | Prioritizes low-complexity nearby options and explicitly names risk; does not invent child-friendly services. | Pass |
| 6 | `Voy de Córdoba a Valencia con 58%. No quiero llegar justo` | Plans route chargers but says it cannot validate arrival margin without vehicle consumption/profile. | Pass |
| 7 | `Voy de Madrid a Málaga mañana y salgo con 80%` | Plans route chargers and warns that availability, access and tariffs can change before tomorrow. | Pass |
| 8 | `Voy de Sevilla a Granada, ¿me da para llegar sin cargar?` | Does not answer yes/no without current battery/autonomy; offers route context and asks for vehicle data. | Pass |
| 9 | `Tengo que ir de Alicante a Bilbao y prefiero parar pocas veces` | Uses route context but does not guarantee few stops without autonomy/consumption. | Pass |
| 10 | `Voy de Zaragoza a Barcelona y quiero llegar con al menos 25%` | Shows chargers in route and says the 25% hard reserve cannot be validated with `chargers_only`. | Pass |
| 11 | `Quiero la ruta más barata, pero sin bajar del 20%` | Asks for route/vehicle data and does not fabricate price comparison. | Pass |
| 12 | `Evita cargadores caros si hay alternativas razonables` | Treats price as preference but refuses to create a risky route or fake tariffs. | Pass |
| 13 | `¿Me conviene cargar antes de salir o al llegar?` | Compares the scenarios conceptually and asks for origin/destination/battery to calculate. | Pass |
| 14 | `Quiero cargar lo justo para llegar, sin pagar de más` | Asks for route and vehicle facts needed for minimum-charge math; no invented kWh. | Pass |
| 15 | `Compara ruta rápida contra ruta barata` | Requests route context/cost data instead of producing a fake comparative UI. | Pass |
| 16 | `Me voy 3 días a Córdoba y me quedo en el hotel Meliá` | Uses Córdoba approximation, explains exact hotel needs better location data, and keeps the task as stay charging. | Pass with geocoder limitation |
| 17 | `Voy el finde a Granada y duermo cerca de la Alhambra` | Resolves Alhambra/Granada, searches destination chargers and explains hotel exactness would refine it. | Pass |
| 18 | `Voy a un hotel sin cargador...` + `En Valencia centro` | Keeps hotel context, searches Valencia centro and returns destination card, primary stop and alternatives. | Pass |
| 19 | `Voy una semana a Cádiz...` | Uses stay planning, destination chargers and structured stay/stop blocks when tool data exists. | Pass |
| 20 | `Voy a Córdoba el viernes y vuelvo el domingo...` | Recognizes round trip and asks for origin before planning ida/vuelta. | Pass |
| 21 | `Voy con niños y quiero parar a comer mientras carga` + route/location | Prioritizes comfort/services when traced amenities exist; otherwise explains missing service data. | Pass |
| 22 | `Busca una parada con baños y cafetería` + `Estoy cerca de Almansa` | Searches Almansa and says amenities are not verified near returned chargers; shows EV-traced options only. | Pass |
| 23 | `No quiero cargar en sitios solitarios de noche` + location | Prefers hubs/central options and does not claim safety beyond traced location context. | Pass |
| 24 | `Prefiero desviarme 10 minutos si el sitio es más cómodo` + route | Uses route tool and accepts controlled detour for a better stop without inventing comfort facts. | Pass |
| 25 | `Quiero parar donde haya restaurante y cargadores rápidos` + route | Combines route charging with service preference where amenities exist; otherwise states service data is unavailable. | Pass |
| 26 | `Mi coche carga máximo a 100 kW... Madrid a Valencia con 60%` | Uses `max_useful_power_kw=100`; recommends `Moya Hub Honrubia` for corridor/EVSE/connectors, explicitly says its 240 kW exceed what the car uses and are not the reason. | Pass |
| 27 | `Evita cargadores con un solo conector. Estoy en Córdoba...` | Chooses `Parking Paseo de la Victoria` with multiple EVSEs/connectors and does not show single-connector options as primary. | Pass |
| 28 | `No quiero bajar nunca del 30%. Madrid a Valencia con 70%` | Treats 30% as a hard reserve that cannot be validated without vehicle profile; shows route chargers only. | Pass |
| 29 | `Prefiero hubs grandes aunque sean un poco más caros...` | Prioritizes hub reliability and explicitly does not validate cost/tariffs. | Pass |
| 30 | `Tengo un Tesla Model Y y salgo con 45%... Madrid a Valencia` | Uses model/battery context conversationally but does not invent Model Y consumption or arrival battery; returns route chargers only. | Pass |

### Final Example: Max 100 kW Preference

Usuario: `Mi coche carga máximo a 100 kW, no necesito ultrarrápidos. Voy de Madrid a Valencia con 60%`

Respuesta final: `Con 60% y un máximo útil de 100 kW, la parada recomendada es Moya Hub Honrubia. La elijo por estar en el corredor, tener 9 EVSEs y 12 conectores; sus 240 kW superan lo que tu coche aprovechará, así que no la recomiendo por esa potencia extra. No puedo validar la autonomía exacta ni la batería de llegada con los datos disponibles.`

Structured blocks: `TripSummaryCard`, `RouteSummaryCard(planningLevel=chargers_only)`, `StationDetailCard`, `StationList`, `RiskExplanationCard`.
