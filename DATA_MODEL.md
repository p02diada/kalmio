# Data Model

## Accounts

- User: Django `auth.User`, using email as username through the account API.
- Session: Django session cookie for authenticated API access.
- AuthThrottle: SHA-256 key, attempts, window_started_at, updated_at. Used to throttle failed public auth attempts without storing raw email/IP pairs.

## Charging

- Operator: name, website, support_phone.
- Station: external_id, name, latitude, longitude, address, operator, data_source, amenities, is_sample_data.
- EVSE: station, evse_uid, max_power_kw, status.
- Connector: evse, connector_type, max_power_kw.
- Tariff: station or operator, price_per_kwh, session_fee, currency, updated_at, is_estimated.
- AvailabilitySnapshot: evse, status, observed_at, source.
- DataSource: name, kind, license, is_authorized, notes.
- ReliabilityScore: station, score, reasons, updated_at.

## Routing

- RoutePlan: public_id, user, origin/destination labels and coordinates, distance, duration, energy estimate, arrival battery, recommendation_station, recommendation_snapshot, alternatives_snapshot, warnings, request_payload, created_at.

## Feedback

- Feedback: user, route_plan, kind, comment, created_at.

## Data Rules

Production charger data must come from authorized imports through `import_chargers`. Records marked as sample, fixture, mock, or test data are rejected. Do not scrape REVE for production. `scrape_reve_dev` may create a temporary local REVE cache only for development tests and is blocked when `DEBUG=false` by default. Do not include API keys or unauthorized provider exports.

Manual charger records default to untrusted source authorization and unknown EVSE availability. Only the authorized importer marks data sources as authorized.

## Implementation Note

The backend stores station `latitude` and `longitude` as decimal columns to keep SQLite tests runnable on machines without GDAL. Production deployments still require a PostGIS database backend. The current nearby API uses a portable Haversine selector over authorized persisted stations; a future migration can introduce geospatial columns and database distance queries when that path is implemented end to end.
