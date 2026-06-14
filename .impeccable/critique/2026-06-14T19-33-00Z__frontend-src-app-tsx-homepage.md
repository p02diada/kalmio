---
target: la home sin PRODUCT_UI.md
total_score: 28
p0_count: 0
p1_count: 2
timestamp: 2026-06-14T19-33-00Z
slug: frontend-src-app-tsx-homepage
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | The home explains the chat-first flow, but not what checks or data boundaries happen after submit. |
| 2 | Match System / Real World | 3 | The EV jobs are present in quick prompts, but the hero question is generic for a charging-planning assistant. |
| 3 | User Control and Freedom | 3 | Free text and quick starts are flexible; account affordance and mode choice remain unclear. |
| 4 | Consistency and Standards | 3 | Visual vocabulary is consistent, but the desktop shell clips the bottom nav. |
| 5 | Error Prevention | 2 | Empty or underspecified starts are possible in a workflow where missing data matters. |
| 6 | Recognition Rather Than Recall | 3 | Quick prompts reduce recall, but route/battery/connector facts are not progressively requested on the home. |
| 7 | Flexibility and Efficiency | 3 | Three entry jobs are useful; urgent charging and trip prep could be differentiated more sharply. |
| 8 | Aesthetic and Minimalist Design | 4 | Calm, premium, restrained, and mobile-first without obvious AI slop. |
| 9 | Error Recovery | 2 | Recovery is deferred to chat; the home itself has no failed-start or retained-draft feedback. |
| 10 | Help and Documentation | 2 | The trust rule is present, but appears too low and is not tied to the primary action. |
| **Total** | | **28/40** | **Strong visual base, needs stronger EV guardrails** |

## Anti-Patterns Verdict

This does not look obviously AI-generated. The surface is restrained, legible, and coherent: compact mobile shell, Geist typography, black primary action, light surfaces, and minimal decoration. The detector found no static anti-patterns in `frontend/src/App.tsx`.

The main weakness is no longer a mismatch with `frontend/PRODUCT_UI.md`; that file has been removed and is not part of this critique. The remaining issue is that the chat-first home is slightly too generic for a trusted EV charging assistant. It needs clearer safety boundaries, stronger EV-specific affordances, and better responsive polish.

## Overall Impression

The home is directionally good: calm, focused, and not map-first. It communicates "chat first, map later" without looking like a generic SaaS dashboard. The next quality step is to make the first interaction safer: prevent empty starts, expose the no-invention rule earlier, and make urgent charging feel operationally distinct from trip planning.

## What's Working

The first viewport is simple and quiet. There is one dominant question, one input, and three quick starts.

The product posture is correct: chat-first rather than map-first, and conservative language around reliable sources.

The quick prompts map to meaningful user intents: destination charging, route preparation, and urgent charging.

## Priority Issues

**[P1] Desktop/tablet shell clips the bottom navigation**

Why it matters: In the 1280x900 screenshot, the active bottom-nav pill is cut off. Even if Kalmio is mobile-first, a broken desktop frame undermines trust during development, demos, and tablet use.

Fix: At `md` and up, make the framed app shell reserve enough height for nav, or switch to a desktop-appropriate nav layout. Verify at 390x844, 768x1024, and 1280x900.

Suggested command: `$impeccable adapt la home`

**[P1] The primary input lacks high-stakes guardrails**

Why it matters: Kalmio must not invent route, charger, price, station, coordinate, or vehicle-state data. The home currently accepts any prompt and can navigate on an empty submit. For EV anxiety, the first action should make the "I will ask if data is missing" behavior explicit.

Fix: Disable empty submit, keep the draft on failed starts, and add compact helper copy under the input: "Si faltan batería, conector, origen o destino, te preguntaré antes de recomendar." Keep it short, but put it near the action.

Suggested command: `$impeccable harden la home`

**[P2] The hero is polished but too generic**

Why it matters: "¿Qué necesitas hacer ahora?" could belong to any assistant. Kalmio's differentiator is EV charging planning with conservative recommendations. The home should say that earlier without becoming a landing page.

Fix: Change the headline or supporting line to name the EV planning job directly. Example direction: "Planifica tu carga antes de salir" or "Dime tu ruta o tu urgencia de carga." Keep the tone calm and practical.

Suggested command: `$impeccable clarify la home`

**[P2] The trust promise is visually late**

Why it matters: The best line on the screen is in the lower card: if reliable data is missing, Kalmio will say so. On mobile it is partially pushed below the nav area, so the reassurance arrives after the action instead of before it.

Fix: Promote the reliable-source/no-guessing promise into a compact line near the composer, and let the card explain A2UI/rendering later if it still earns its space.

Suggested command: `$impeccable layout la home`

**[P3] Quick prompts should express mode differences**

Why it matters: "Necesito cargar ya" and "Preparar ruta" have different urgency, data needs, and expected follow-up. Equal chips make them feel like generic examples.

Fix: Treat the quick prompts as modes or grouped actions: urgent, route, destination. Urgent can mention location; route can mention battery/destination; destination can mention hotel/stay.

Suggested command: `$impeccable onboard la home`

## Persona Red Flags

**Jordan, stressed low-battery driver**: "Necesito cargar ya" is present, but there is no visible location cue or "we may ask for your location/connector" expectation before chat.

**Marta, family trip planner**: "Preparar ruta" helps, but the visible screen does not show that comfort constraints, stops, or charger preferences can be handled.

**Alex, returning user**: The top-right account icon looks tappable but is not a link or button, and the desktop nav clipping makes the shell feel less reliable.

## Minor Observations

- `html lang="en"` should be `es`.
- The top-right account icon is a `span`; either make it a real link/button or reduce its affordance.
- The H1 stack is visually strong, but its generic wording weakens product specificity.
- The detector returned `[]`; the problems are product UX and responsive behavior, not static slop patterns.

## Questions to Consider

- What should the first input promise: "tell me anything" or "tell me route/charging context and I will ask for missing facts"?
- Should urgent charging become a distinct first-class mode?
- Should the desktop surface be a framed mobile preview, or should it adapt into a real desktop/tablet layout?
