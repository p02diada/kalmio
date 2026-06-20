---
target: UrgentChargeCard UX
total_score: 27
p0_count: 0
p1_count: 2
timestamp: 2026-06-19T22-06-30Z
slug: components-a2ui-a2ui-renderer-tsx-urgentchargecard
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Battery, distance, risk and actions are visible, but the "what happens if I tap confirm" state is unclear. |
| 2 | Match System / Real World | 3 | "Dónde ir ahora" matches the urgent mental model, but "Confirmar esta parada" is softer than a driver expects when they need navigation. |
| 3 | User Control and Freedom | 3 | The user can request another nearby stop, but correcting location or connector is not attached to the result. |
| 4 | Consistency and Standards | 3 | Reuses Kalmio card vocabulary cleanly, but urgent recommendations look too similar to ordinary metric cards. |
| 5 | Error Prevention | 2 | Warnings exist, yet availability/access uncertainty is separated from the go/no-go action. |
| 6 | Recognition Rather Than Recall | 3 | Core fields are labeled, but the station/place distinction requires interpretation. |
| 7 | Flexibility and Efficiency | 2 | No direct navigation/open-map action inside the urgent decision card. |
| 8 | Aesthetic and Minimalist Design | 3 | Calm and readable, but the 3-column metric grid compresses the most important name. |
| 9 | Error Recovery | 3 | Alternative search exists, but there is no fast "wrong location" or "wrong connector" correction path near the result. |
| 10 | Help and Documentation | 2 | Risk language explains limitations, but not the next safest user action. |
| **Total** | | **27/40** | **Promising but underpowered for emergency UX** |

## Anti-Patterns Verdict

This does not look like generic AI slop. The component uses restrained product UI, familiar cards, compact metrics, clear Spanish microcopy, and no decorative gradient/glass/card theatrics. The failure mode is different: it is too calm and too generic for the "I need to charge now" moment.

The deterministic detector returned `[]` for `frontend/src/components/a2ui/a2ui-renderer.tsx`. It did not find known visual anti-patterns. Browser overlay injection was not available in this session, so the visual signal came from headless Chrome screenshots of `/a2ui` at mobile widths.

## Overall Impression

`UrgentChargeCard` is legible and safe, but it does not yet feel like the decisive emergency object in the chat. In the mobile flow, the decision is split across three surfaces: `UrgentChargeCard` says where, `RiskExplanationCard` says why to be careful, and `ActionButtons` says what to do. That fragmentation makes the driver assemble the answer under stress.

## What's Working

- The component is compact, mobile-safe, and uses only cataloged A2UI renderer primitives. It respects the agentic boundary: the renderer presents facts; it does not invent charger decisions.
- The copy "Dónde ir ahora" is the right conceptual promise for urgent charging. It is calmer and more useful than a generic "Recommendation" heading.
- The flow correctly exposes uncertainty: low battery, approximate location, and no confirmed availability/price are visible in the urgent scenario.

## Priority Issues

**[P1] The emergency decision is split across separate blocks**

Why it matters: A driver at 9% battery should not need to integrate the stop, risk, and primary action from three adjacent components. The card should answer "go here, with this margin, then do this" in one glance.

Fix: Promote the nearest stop/place name and distance into a stronger top section, keep risk as an inline decision constraint, and attach the primary action contract to the card through the existing `decisionProps.primaryAction` pattern or an adjacent action slot that visually belongs to the card.

Suggested command: `$impeccable shape UrgentChargeCard`

**[P1] The primary action is too generic for urgent charging**

Why it matters: "Confirmar esta parada" is an internal workflow action, not the action a stressed driver expects. The driver likely wants "Abrir ruta", "Ir a este punto", or "Confirmar y navegar" depending on available data. Confirmation alone creates ambiguity.

Fix: Make the action label reflect the real outcome. If coordinates or a safe provider URL are available, use navigation/open-route language. If not, state the limitation in the disabled action reason and keep "Buscar otra cercana" secondary.

Suggested command: `$impeccable clarify UrgentChargeCard`

**[P2] The 3-column metric grid compresses the most important value**

Why it matters: In the screenshot, `Demo Charge Urgente` wraps into a narrow center column while `Batería` and `Distancia` get equal weight. The stop name is the decision anchor and should not be the weakest part of the card.

Fix: Use a decision layout instead of a generic metric grid: full-width stop/place title, secondary station/access line, then compact battery and distance chips or a two-column metric row.

Suggested command: `$impeccable layout UrgentChargeCard`

**[P2] Risk copy is honest but not operational enough**

Why it matters: "Reduce velocidad y confirma que el punto sigue accesible" is useful, but the interface does not give a direct way to perform those confirmations or distinguish "data risk" from "driving margin risk."

Fix: Split risk into short labeled facts: "Margen: bajo", "Disponibilidad: no confirmada", "Acceso: confirmar". Keep the longer explanation in the risk card only when needed.

Suggested command: `$impeccable clarify UrgentChargeCard`

**[P2] Correction paths are not close enough to the result**

Why it matters: The scenario itself says the driver needs a safe way to correct location. Once the recommendation appears, correction lives implicitly in chat, not near the recommendation.

Fix: Add lightweight secondary actions or chips near the urgent result: "Cambiar ubicación", "Cambiar batería", "Cambiar conector". These should send A2UI events back to the backend, not become local frontend decision logic.

Suggested command: `$impeccable harden UrgentChargeCard`

## Persona Red Flags

**Low-battery driver in an unfamiliar city**: The flow is calm, but the recommendation does not dominate the screen. They must read the card, then the risk card, then the action buttons before knowing what to do next.

**First-time Kalmio user**: "Confirmar esta parada" may sound like saving a selection rather than getting help moving. They may not understand whether the app will navigate, ask another question, or simply mark the stop as chosen.

**Careful planner with trust concerns**: The uncertainty copy is present, but factual traceability is not visually structured. They can see "no confirma disponibilidad ni precio," but not which fields are known, estimated, or missing.

## Minor Observations

- The warning icon color is subtle on white; the urgent card relies more on text than on emergency hierarchy.
- The showcase copy lacks accents in several places (`ubicacion`, `decision`, `bateria`), which makes the demo feel less polished even if production agent copy may differ.
- The location request card is visually stronger than the final urgent recommendation, which inverts the importance of the flow after location is known.

## Questions to Consider

- Should `UrgentChargeCard` be a generic metric card, or a dedicated emergency decision card?
- What is the safest primary action when coordinates exist: confirm, navigate, call provider, or ask for another stop?
- Which risks should be visible in one glance before the driver taps the primary action?
