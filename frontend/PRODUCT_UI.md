# Product UI Context

## Primary Surface

The home screen is a structured route-planning surface. The user enters origin/destination coordinates or uses browser geolocation for origin, then receives a provider-backed route and charger recommendation. The map remains secondary and opens externally for the recommended charger.

## Required Routes

- `/`: route planner backed by `/api/conversation/route`.
- `/activity`: previous plans and feedback later.
- `/settings`: account session.

## User Expectations

- The app should feel fast and safe to use on a phone.
- The assistant should ask for missing data instead of guessing.
- Recommendations should clearly show primary option, alternatives, risks, and actions.
- The user should always understand when data is estimated, unavailable, or uncertain.

## UX Boundaries

- No booking flows.
- No payment UI.
- No arbitrary generated UI.
- No turn-by-turn navigation.
- No map-first browsing mode in the home.

## Empty And Error States

- Empty home shows route inputs, geolocation affordance, and preference controls.
- Backend error keeps the typed message and offers retry.
- Unknown A2UI block renders a neutral fallback.
