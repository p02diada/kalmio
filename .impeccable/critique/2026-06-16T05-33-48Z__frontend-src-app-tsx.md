---
target: frontend/src/App.tsx
total_score: 25
p0_count: 0
p1_count: 3
timestamp: 2026-06-16T05-33-48Z
slug: frontend-src-app-tsx
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Loading/progress exists, but skeletons are generic and do not explain backend/provider/data checks. |
| 2 | Match System / Real World | 3 | Copy is conservative and EV-specific, but UI still lacks driver-native artifacts: SOC, connector, route timeline, data freshness. |
| 3 | User Control and Freedom | 2 | Chat reset is easy to hit and account/history flows have limited recovery or continuation actions. |
| 4 | Consistency and Standards | 3 | Strong shadcn/Tailwind consistency; some card/button density choices get cramped in A2UI metric blocks. |
| 5 | Error Prevention | 2 | The home asks for useful facts, but does not help users provide battery/connector/location in structured, low-friction ways. |
| 6 | Recognition Rather Than Recall | 3 | Guided prompts and chips help; users still need to remember exact EV facts and phrasing. |
| 7 | Flexibility and Efficiency | 2 | Good fast path to chat; weak desktop adaptation and no vehicle/profile defaults yet. |
| 8 | Aesthetic and Minimalist Design | 3 | Clean, calm, not slop-heavy; currently too generic/sterile for the EV co-driver promise. |
| 9 | Error Recovery | 3 | Technical errors are translated and retry exists; provider/data-unavailable recovery needs richer next steps. |
| 10 | Help and Documentation | 2 | Trust copy exists, but no in-context explanation of data sources, freshness, privacy, or saved-plan value. |
| **Total** | | **25/40** | **Solid foundation, not yet a complete trusted EV assistant experience** |

## Anti-Patterns Verdict

**LLM assessment**: It does not look obviously AI-generated. The interface avoids gradient text, bloated card grids, decorative orbs, excessive shadows, and over-rounded surfaces. The main risk is the opposite: it feels like a precise generic chat tool with EV copy, not yet a driver-grade assistant. The visual language is too close to Vercel/product-neutral: black/white, Geist, tiny mono, thin borders. Calm is good; lack of EV-specific state is the gap.

**Deterministic scan**: `detect.mjs --json frontend/src` returned `[]`. No detector findings. Earlier targeted scans on `frontend/src/App.tsx` and `frontend/src/components/a2ui/a2ui-renderer.tsx` were also clean.

**Visual evidence**: Headless Chrome screenshots were captured for home mobile, home desktop, chat mobile, plans mobile, and account mobile/desktop. No user-visible overlay was produced because mutable browser overlay injection was not available in this environment without adding browser automation dependencies.

## Overall Impression

Kalmio already has the right restraint: it is calm, mobile-first, avoids fabricated certainty in copy, and respects the A2UI boundary. The biggest opportunity is to make the interface show its EV reasoning state instead of only describing it. Drivers should see what Kalmio knows, what is missing, what is provider-backed, what is uncertain, and what action is safest next.

## What's Working

1. **The entry point is focused.** The home asks for route or urgency immediately, with no marketing detour.
2. **The tone is product-correct.** “No inventa disponibilidad, precios ni estaciones” sets the right conservative expectation.
3. **The A2UI renderer has safety-minded fallbacks.** Unknown blocks render a contained fallback, long chips wrap, disabled actions explain why, and technical errors are not leaked directly.

## Priority Issues

**[P1] The UI does not yet expose enough EV decision state.**
Why it matters: the product promise is anxiety reduction, but the user cannot quickly inspect data freshness, connector match, battery margin, provider confidence, or why a stop won.
Fix: add a compact “decision state” layer to recommendation cards: known facts, missing facts, provider/data source, confidence reason, and “confirm before relying” warnings tied to the exact fact.
Suggested command: `$impeccable shape recommendation evidence layer`

**[P1] The first-run intake is too free-text for high-stakes missing data.**
Why it matters: chat-first is correct, but drivers under stress should not have to remember all required facts or phrase them well.
Fix: keep chat first, but add optional structured chips/controls for battery %, connector, current location, destination, urgency, and stop preference. Send them through the backend/agent boundary as context, not as a frontend intent parser.
Suggested command: `$impeccable onboard EV trip intake`

**[P1] Loading and unavailable-data states are too generic.**
Why it matters: a skeleton is not reassurance when a driver is waiting for routing/provider checks. It does not say whether Kalmio is loading a session, checking route data, waiting on Codex/provider, or blocked.
Fix: replace generic skeletons with state-specific copy and actions: “Cargando conversación”, “Comprobando proveedor”, “Datos de cargadores no disponibles”, retry, start new chat, and safe fallback guidance.
Suggested command: `$impeccable harden loading and unavailable data states`

**[P2] Desktop wastes the opportunity to be a planning workspace.**
Why it matters: mobile-first is correct, but desktop currently reads as a mobile app stretched into whitespace. Route planning benefits from a wider review mode.
Fix: keep the mobile chat as primary, but on desktop add a secondary pane for current facts, route/stop summary, map preview, saved-plan status, and unresolved questions.
Suggested command: `$impeccable adapt desktop planning view`

**[P2] Account and history do not yet explain value or create a saved-driver profile.**
Why it matters: “Cuenta” currently feels administrative. For EV planning, the account should reduce repeated typing and increase confidence.
Fix: add vehicle/profile settings: connector, usable battery, consumption, preferred reserve, usual providers, accessibility/comfort preferences, and clear saved-plan benefits.
Suggested command: `$impeccable onboard account and vehicle profile`

## Things Missing / Things I Would Add

- Vehicle profile: connector, usable battery, consumption, preferred reserve, charging speed ceiling, default passenger/rest preferences.
- Data status surface: authorized charger import freshness, routing provider status, unavailable provider states, and “not live availability” disclaimer where it matters.
- Recommendation evidence: why this stop, what facts are traced, what is estimated, what must be confirmed before departure.
- Trip timeline: origin, current SOC, recommended stop, arrival SOC, reserve buffer, risk band.
- Better urgent mode: large current battery/location confirmation, nearest safe option, “do not rely until confirmed” warning, direct action buttons.
- Saved plan detail view: not only list rows, but a readable plan recap with assumptions and stale-data warning.
- Offline/PWA states: explain when the app is offline, when cached plans are viewable, and when new recommendations cannot be trusted.
- Feedback loop: “Esta recomendación no encaja” with reasons such as connector, access, amenities, detour, stale data.
- Privacy copy for location sharing: what is sent, why, and how to continue manually.

## Persona Red Flags

**María, driver with 12% battery**: The home has “Carga urgente”, but the first visible interface still looks like a general chat. She needs a visibly urgent flow with battery/location/connector confirmation and a prominent status that Kalmio will not invent availability.

**Sergio, planner on desktop for a family trip**: Desktop gives him a narrow mobile-like column. He cannot compare route assumptions, comfort stops, alternatives, and warnings side by side. He will bounce between cards instead of reviewing a coherent plan.

**Lucía, first-time EV driver**: Copy says Kalmio asks what is missing, but the UI does not teach what “good enough” input looks like beyond one placeholder. She needs guided examples and structured optional fields so she does not fear entering the wrong thing.

## Minor Observations

- `Antes de recomendar` is useful trust copy, but it sits below the first mobile viewport; move a shorter trust/status cue closer to the input.
- The black active pill in the bottom nav is clear, but the product uses black for both primary action and navigation. Introduce restrained EV semantics for route/assistant/status roles.
- The reset chat icon is visually quiet for a destructive/restart action. Add confirmation or make it secondary behind a menu.
- Metric grids use three columns even on compact cards; long station names, coordinates, and confidence text can become hard to scan.
- The `MapPreviewCard` is a schematic, not map-like enough to support route trust. If factual map data is unavailable, label it explicitly as a preview/schematic.

## Questions to Consider

- What should the user trust at a glance: the stop, the route margin, the data source, or the next action?
- Should Kalmio feel like a chat app with route cards, or like a route plan whose primary control is chat?
- Which facts should persist between chats so the driver stops retyping the same vehicle data?
- What does the UI do when no authorized charger data is available: ask, explain, or stop?
