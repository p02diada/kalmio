# Agentic EV Codex Iteration - 2026-06-15

Manual runs used `KALMIO_CONVERSATION_AGENT_MODE=codex` with the local Codex CLI and authorized charger data from the development SQLite database.

## Initial Findings

- A initially asked for location correctly, but sometimes rendered `UrgentChargeCard.nearest` as a generic placeholder while text mentioned a real station.
- B initially failed the correction turn with a generic fallback instead of searching Valencia.
- C could answer the follow-up when prior Córdoba results were valid, but became unstable when the prior turn fell back.
- D initially fell into generic fallback for `Paseo de la Victoria de Córdoba`.
- F initially asked for the exact hotel too rigidly instead of offering a Valencia approximation.

Probable causes:

- Prompt lacked concrete correction/follow-up examples.
- Allowed tool failures were cut off by backend fallback before Codex could explain them.
- Location resolution did not normalize accents.
- Codex emitted safe prop variants such as `name` and `stationName` for `UrgentChargeCard`, but the normalizer did not map them to `nearest`.
- Useful vehicle facts from earlier user text were not summarized compactly for Codex.

## Changes Made

- Updated Codex defaults to `gpt-5.4-mini` and timeout to 60 seconds.
- Added EV-specific prompt examples for urgent charging, corrections, POI approximations, routes without consumption, and hotel charging.
- Added compact history summary for explicit battery and connector facts.
- Let failed allowlisted tools return to Codex for a contextual final answer; unknown tools still use safe backend fallback.
- Normalized accented location queries in `resolve_location`.
- Normalized `UrgentChargeCard` variants: `name`, `stationName`, and `chargerName`.
- Added repair issue when `UrgentChargeCard.nearest` stays generic despite traced station results.

## Final Manual Transcripts

### A. Carga urgente con ubicación posterior

Usuario: `Necesito cargar ya`

Respuesta: pide solo ubicación actual, ciudad, zona o coordenadas. No pide destino.

Usuario: `En Córdoba`

Respuesta final: usa Córdoba como ubicación aproximada, muestra `UrgentChargeCard` con `BALLENOIL-ES336090-COLON` a 0.3 km y `RiskExplanationCard` sobre datos autorizados, acceso, tarifa y disponibilidad.

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
