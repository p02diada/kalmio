---
target: la home
total_score: 25
p0_count: 0
p1_count: 2
timestamp: 2026-06-14T19-26-10Z
slug: frontend-src-app-tsx-homepage
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | The home explains intent, but gives no visible status for provider-backed routing, data readiness, or what will happen after submit. |
| 2 | Match System / Real World | 3 | Spanish EV language is clear, but the primary action is framed as generic intent instead of the real trip-planning data users expect. |
| 3 | User Control and Freedom | 3 | Free text and quick prompts are easy to use, but the header account affordance is not actionable and the user cannot choose a structured route path. |
| 4 | Consistency and Standards | 3 | The component vocabulary is consistent and restrained; the desktop shell breaks expectations by clipping the bottom nav. |
| 5 | Error Prevention | 2 | Empty submit can navigate to chat, and the home does not prevent missing critical route data before sending the user onward. |
| 6 | Recognition Rather Than Recall | 2 | Quick prompts help, but route planning still depends on users remembering battery, connector, consumption, destination, and constraints. |
| 7 | Flexibility and Efficiency | 2 | The surface supports quick starts, but lacks geolocation, saved-plan shortcuts, structured preferences, and a route-first fast path. |
| 8 | Aesthetic and Minimalist Design | 3 | Clean, premium, and calm; slightly too sparse for a high-stakes EV planning workflow. |
| 9 | Error Recovery | 1 | The home has no visible retry, retained failed request, or provider-unavailable state; recovery is deferred to chat. |
| 10 | Help and Documentation | 2 | "Chat primero, mapa despues" is useful, but the trust rules are below the fold and not tied to action. |
| **Total** | | **25/40** | **Promising shell, underpowered primary workflow** |

## Anti-Patterns Verdict

This does not look obviously AI-generated. The strongest visual impression is a restrained, Vercel-adjacent mobile product shell: black ink, Geist, compact cards, small mono caption, and minimal chrome. That restraint mostly works for Kalmio's calm/premium goal.

The bigger issue is not visual slop; it is product slop. The home says "tell me the intent" when the product contract says the home is a structured route-planning surface. For EV trip planning, that mismatch matters more than ornamentation.

Deterministic scan: `detect.mjs --json frontend/src/App.tsx` returned `[]`. No static anti-patterns were detected in the target file.

URL detector scan: attempted against `http://127.0.0.1:5173/`; the script reported that Puppeteer is required for URL scanning, then returned `[]`. Treat this as a browser-detector limitation, not a clean rendered-page pass.

Visual overlay: no reliable user-visible detector overlay is available in this session because the Codex Browser mutation/injection surface is unavailable and Puppeteer is not installed. Chrome headless screenshots were used as the fallback visual evidence.

## Overall Impression

The home has a strong base: it is quiet, legible, and mobile-first. But it currently feels like a generic assistant launcher, not the first screen of an EV planning product. The single biggest opportunity is to make the first screen collect and reassure around the minimum viable trip context instead of punting the hard parts to chat.

## What's Working

The visual density is good for mobile. The user sees one headline, one input, quick prompts, and one trust card. There is no dashboard clutter or map-first pressure.

The copy is cautious in the right places. "Si falta una fuente fiable, Kalmio lo dira" supports the no-invention rule and matches the product's conservative posture.

The quick prompts map to three real jobs: destination charging, route prep, and urgent charging. Those are useful entry points even if they need stronger structure.

## Priority Issues

**[P1] The home does not match the documented primary route-planning surface**

Why it matters: `frontend/PRODUCT_UI.md` says `/` should expose route inputs, geolocation, and preference controls backed by `/api/conversation/route`. The current home only stores a prompt and navigates to `/chat`. For an anxious EV driver, this hides the actual data contract and makes the product feel less trustworthy.

Fix: Reshape the home around three explicit jobs: route planning, charge-now, and destination charging. For route planning, show origin/destination, battery/vehicle basics, connector/power preferences, and a clear provider-backed submit path. Keep chat as the assistant layer, not the only doorway.

Suggested command: `$impeccable shape la home como planificador EV`

**[P1] Desktop/tablet shell clips the bottom navigation**

Why it matters: In the 1280x900 screenshot, only the top of the active bottom-nav pill is visible. That makes the app feel broken outside the narrow mobile viewport and harms basic navigation confidence.

Fix: Rework the app shell at `md` and up: either keep the bottom nav fully inside the framed phone shell, move navigation to a visible side/top rail, or remove the fixed mobile nav treatment for desktop. Verify at 390x844, 768x1024, and 1280x900.

Suggested command: `$impeccable adapt la home`

**[P2] The trust/reassurance message appears too late**

Why it matters: The most important product promise is not decoration; it is safety: no invented availability, prices, coordinates, or battery state. On mobile, the card carrying this promise is partially pushed under the bottom nav in the first viewport.

Fix: Move the trust rule closer to the input as a compact inline status or two-line assurance, such as "Usare solo datos autorizados. Si falta algo, te preguntare." Keep the card if needed, but do not make it the first place where the safety promise appears.

Suggested command: `$impeccable clarify la home`

**[P2] The primary input allows an unhelpful empty or underspecified start**

Why it matters: Error prevention is central here. Users can submit an empty input and land in chat with no pending prompt. The placeholder also lists categories, not the minimum information needed for a safe recommendation.

Fix: Disable submit until there is text, preserve draft on failure, and add lightweight structure around missing data. If the user selects "Preparar ruta", prompt for origin, destination, battery, useful capacity, consumption, connector, and desired charger power.

Suggested command: `$impeccable harden la home`

**[P3] Quick prompts are useful but under-organized**

Why it matters: "Cargar cerca de un hotel", "Preparar ruta", and "Necesito cargar ya" are strong use cases, but visually they read as equal chips with no sense of urgency or required data. The urgent case should feel faster and more location-aware than the planning case.

Fix: Group quick starts by job mode or make them segmented actions: "Ruta", "Cargar ahora", "Destino". Give "Cargar ahora" a geolocation affordance and a visible caveat when location is unavailable.

Suggested command: `$impeccable onboard la home`

## Persona Red Flags

**Jordan, first-time EV driver with low battery**: Taps "Necesito cargar ya" but sees no immediate location permission, radius, connector, or "we may need your location" cue on the home. The flow depends on chat interpreting urgency correctly, which is risky in a stress moment.

**Marta, family trip planner**: Wants to plan Cordoba to Valencia with food/restroom comfort and a safe battery buffer. The home gives no visible way to enter preferences or constraints; she has to know how to phrase them in natural language.

**Alex, returning power user**: Wants to repeat or inspect a previous plan. The home does not surface recent plans or a saved route shortcut, and the desktop nav clipping makes the shell feel less reliable.

## Minor Observations

- The document language renders as `html lang="en"` while the interface is Spanish. Set it to `es` for screen readers and browser language behavior.
- The header account icon is a non-interactive `span`, but visually reads like a tappable account control.
- The h1 is bold and memorable, but `max-w-hero-width: 11ch` forces a dramatic stack. It works visually, but it may be too marketing-like for a task surface.
- The "Chat primero, mapa despues" card has good content but competes with the actual next action because it looks like a promotional callout.
- The desktop framed-phone presentation is coherent for mobile-first review, but it should not break core navigation.

## Questions to Consider

- What if the first screen asked for the minimum safe route facts before opening chat?
- What promise must be visible before a stressed driver trusts the assistant?
- Should the home optimize first for "plan a trip" or "I need charge now", or should those be explicit modes?
