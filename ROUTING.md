# Routing

## Goal

Provide conservative, explainable EV trip planning using a real route provider and persisted authorized charger data. The planner must fail explicitly when it cannot produce a defensible answer.

## Route Provider

`OsrmRouteProvider` calls the configured OSRM-compatible HTTP endpoint from `KALMIO_OSRM_BASE_URL`. `KALMIO_ROUTING_PROVIDER` currently supports `osrm`.

Local development may use the public OSRM endpoint as a convenience fallback. Production must configure an explicit routing provider URL and fails startup if `KALMIO_OSRM_BASE_URL` is missing or points to that public development endpoint.

Provider failures and incomplete provider responses return structured `424` errors from `/api/conversation/route` and `/api/plans/route`; the planner does not substitute synthetic distance, duration, or geometry.

## Charger Data

Route planning queries `Station`, `EVSE`, `Connector`, `Tariff`, `AvailabilitySnapshot`, `DataSource`, and `ReliabilityScore` records imported through `python manage.py import_chargers <csv-or-json>`.

Selectors exclude sample records and unauthorized data sources. `/api/conversation/route` accepts route coordinates, explicit vehicle characteristics, and preferences for the current Django session and stores only the active conversation result. If vehicle characteristics are omitted, it returns `chargers_only`. `/api/plans/route` currently returns `chargers_only` for authenticated users without saving history because account vehicle profiles are disabled. If no authorized charger exists near the route corridor, the endpoint returns `422` instead of fabricating a stop.

## Plan Types

- `urgent`: low battery, nearby charge needed.
- `safe`: route with reserve margin.
- `cheap`: minimize estimated charging cost while respecting reserve.
- `fast`: reduce total travel and charge time.
- `comfortable`: prefer food, restrooms, and larger hubs.
- `stay_trip`: destination and multi-day stay charging.

## Energy Estimate

`energy_kwh = distance_km * consumption_kwh_per_100km / 100 * safety_factor`

Default safety factor: `1.12`.

## Scoring

Reward:

- recent availability backed by `AvailabilitySnapshot.observed_at`,
- several compatible connectors,
- compatible power,
- low detour,
- known price,
- nearby alternatives,
- useful services.

Penalize:

- stale or missing availability timestamps,
- single connector,
- unknown price,
- low availability,
- large detour,
- no alternatives,
- incompatible connector.

## Safety Rule

The planner must not silently recommend a route that violates reserve. If no safe option exists, the response must show a warning or return a structured planning error.

## External Navigation

Kalmio opens external navigation using coordinates or address. It does not implement turn-by-turn navigation.
