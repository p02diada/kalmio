---
target: home
total_score: 26
p0_count: 0
p1_count: 2
timestamp: 2026-06-14T21-27-45Z
slug: frontend-src-app-tsx-homepage
---
**Design Health Score**

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Empty-input disabled state is only a pale 32px arrow; starting chat gives no visible handoff promise from home. |
| 2 | Match System / Real World | 3 | EV planning language is direct, but "fuente fiable" is abstract for a stressed driver. |
| 3 | User Control and Freedom | 3 | Users can type or choose presets, but quick prompts send hidden text with no preview or edit step. |
| 4 | Consistency and Standards | 3 | Familiar shadcn/lucide controls; primary quick prompt competes with the composer as the main action. |
| 5 | Error Prevention | 3 | The no-invention promise is strong, but missing EV data is not operationalized as a visible intake scaffold. |
| 6 | Recognition Rather Than Recall | 2 | Users must remember battery, connector, location, destination, urgency, and stop preferences from sparse hints. |
| 7 | Flexibility and Efficiency | 3 | Quick starts help first use, but there is no recent route, vehicle profile, or saved-context shortcut. |
| 8 | Aesthetic and Minimalist Design | 3 | Calm and readable; desktop feels unfinished and the H1 is closer to landing-page scale than product-task scale. |
| 9 | Error Recovery | 2 | Home does not foreshadow provider unavailable, no authorized chargers, or failed chat handoff states. |
| 10 | Help and Documentation | 2 | Safety copy exists, but there is no compact "what Kalmio needs from you" guidance. |
| **Total** | | **26/40** | **Promising but still passive** |

**Anti-Patterns Verdict**

**LLM assessment**: The home screen does not read as blatant AI slop. It is restrained, legible, and avoids fake maps, fake station cards, and decorative gradients. The AI tells are subtler: a hero-sized operational heading, a generic icon/title/description quick-start trio, and a very sparse desktop layout that feels more like a generated starter shell than a worked EV-planning cockpit.

**Deterministic scan**: Source scan was clean. `node .agents/skills/impeccable/scripts/detect.mjs --json frontend/src/App.tsx` exited `0` with `[]`.

**Browser overlay**: Headless CDP injection succeeded, but no user-visible **[Human]** tab overlay is available in this session. The injected browser detector reported 4 findings: three `layout-transition` findings (`transition: width`, `transition: margin`) and one `overused-font` finding (`Primary font: geist (92% of text)`) paired with another `transition: width`. The font finding is a false positive for this product register because one tuned sans family is correct for product UI. The layout-transition findings are low-risk technical polish, likely from shell/sidebar motion rather than the home content itself.

**Overall Impression**

This is a solid first screen for a conservative EV assistant: quiet, trustworthy, and honest about not inventing data. The biggest opportunity is making the safety promise active. A user at 18% battery should immediately see what Kalmio will ask for, what it will verify, and what it will refuse to fake.

**What's Working**

- The product principle is visible: chat first, map second. There is no charger-map clone behavior and no invented station/price/availability content on the home screen.
- The visual vocabulary is calm and credible: Geist, restrained black/white tokens, simple borders, familiar shadcn controls, and lucide icons all support trust.
- The copy explicitly protects against hallucinated data: "No asumimos disponibilidad, precios ni estaciones" is exactly the right product stance.

**Priority Issues**

**[P1] Home does not reduce EV-specific recall burden**

Why it matters: A stressed EV driver may not know what to type. The current placeholder and quick prompt descriptions hint at required data, but still require the user to remember location, battery, connector, route, destination, and urgency.

Fix: Add a compact inline intake scaffold under or inside the composer: `Ubicacion`, `Bateria`, `Conector`, `Destino`, `Urgencia`. Keep it calm and non-card. If chips are interactive, they should prefill or guide the prompt rather than act as decoration.

Suggested command: `$impeccable clarify home`

**[P1] The urgent path is visually strong but not procedurally reassuring**

Why it matters: "Carga urgente" is correctly emphasized, but it jumps into chat through a hidden prompt. In a high-stakes moment, the user needs to know the next steps before committing.

Fix: Rework the urgent prompt copy into a short sequence: `Te pedire ubicacion y bateria`, `Verificare fuentes autorizadas`, `Si no hay datos fiables, no recomendare una estacion`. No fake live availability claims.

Suggested command: `$impeccable onboard home`

**[P2] Submit target and primary hierarchy are weaker than they look**

Why it matters: Browser evidence measured the visible submit button at `32x32`, below the common `44x44` touch target floor. The black "Carga urgente" tile also competes with the composer, so the primary action is not perfectly clear.

Fix: Increase the actual submit hit area or make the whole inline-end addon a clear 44px target. Keep the composer as the main path, and style quick prompts as presets with one urgent variant, not competing CTAs.

Suggested command: `$impeccable polish home`

**[P2] Desktop composition feels unfinished**

Why it matters: At `1280x900`, the content is readable but sits in a large sparse canvas. That makes the product feel less mature on desktop and wastes space that could reinforce trust.

Fix: Use desktop space for useful context, not decoration: a "Datos que comprobare" panel, recent/saved vehicle context, or account-aware recent route slot. Keep the map absent until it has provider-backed value.

Suggested command: `$impeccable layout home`

**[P3] Browser detector caught low-risk shell motion issues**

Why it matters: Layout transitions on width/margin can feel janky and are harder to keep accessible, especially around sidebars. This is not breaking the home screen, but it is worth cleaning up before the shell grows.

Fix: Prefer transform/opacity for shell motion where possible, and ensure reduced-motion behavior keeps navigation immediate.

Suggested command: `$impeccable audit home`

**Persona Red Flags**

**First-time EV driver under stress**: The user sees "Carga urgente", but not the exact next data needed. The placeholder says "Ruta, hotel, carga urgente..." when the urgent mental model is closer to "Donde estas + bateria + conector." Risk: vague input, slow first response, or abandonment.

**Family trip planner**: "Planificar ruta larga" is useful, but family constraints are missing from the first screen: stop duration, food/restroom needs, arrival buffer, overnight charging. Risk: Kalmio looks like a charger finder rather than a practical trip co-driver.

**Returning/power user**: There is no recent route, saved vehicle, connector default, or repeat-last-plan entry point. Risk: the product stays in first-run mode every time.

**Minor Observations**

- Mobile rendering is clean: no horizontal overflow at `390x844`, bottom nav is readable, and quick prompts stack without collision.
- Desktop rendering is technically clean: no runtime console errors, no overflow, sidebar state is clear.
- The mono claim line is tasteful but could carry slightly more product specificity.
- The copy "fuente fiable" should become more concrete: "datos autorizados" or "proveedor disponible" better matches the product rules.
- The H1 line breaks are acceptable on mobile, but the scale is more heroic than operational.

**Questions to Consider**

- What would the home screen show if its only job were to calm someone at 18% battery?
- Should "Carga urgente" launch a guided intake rather than sending a hidden prompt?
- Is the desktop empty space an intentional mobile-first constraint, or should it show saved vehicle/trip context?
- What is the minimum visible proof that Kalmio will refuse bad data before the user trusts it?
