# Kalmio Design Direction

## Design Source

The public Vercel design.md reference is used as inspiration for precision, high-contrast structure, restrained surfaces, and Geist-like typography. Kalmio adapts that foundation with more color, warmer state vocabulary, and EV-specific trust cues.

The supplied `[Image #1]` is the primary mobile composition reference: white mobile canvas, deep green brand/action color, compact header, large direct question, pill input with voice action, icon quick prompts, rich vehicle card, soft shadow cards, chat bubbles, route/map preview, and strong primary navigation actions.

The source design system in `/home/agent/Descargas/DESIGN-vercel.md` is saved in this project at `docs/DESIGN-vercel.md`. Kalmio adapts it directly: Vercel-like precision, tight radius, crisp borders, installed Geist typography, and high contrast, while replacing developer-platform starkness with EV trust states.

## Visual Positioning

Kalmio should feel calm, premium, reliable, and mobile-native. It is a product UI for stressful travel moments, so the interface must reduce scanning effort and make the next action obvious.

Scene sentence: a driver is parked or stopped before a trip, checking a phone in daylight or car-cabin light, trying to decide whether the next charge plan is safe enough.

## Color Strategy

Restrained product UI with a small but memorable palette:

- Ink: near-black neutral, never pure black.
- Paper: warm off-white, never pure white.
- Electric green: primary action and safe-state signal.
- Signal amber: warnings, risk, and reserve issues.
- Route blue: route and navigation context.
- Soft violet: AI assistant identity and selected suggestions.

Use OKLCH in CSS tokens where possible. Avoid generic blue-purple gradients and large decorative color fields.

## Typography

- Use the installed Geist Sans package, then Inter/system-ui only as fallback.
- Use one family across UI.
- Keep hierarchy tight and product-grade.
- Body copy should remain under 75ch.

## Layout

- Mobile-first app shell.
- Bottom navigation for primary mobile routes.
- Chat composer fixed near the bottom only when it does not hide content.
- Cards are reserved for A2UI response blocks and repeated data items.
- Avoid nested cards.
- Map preview is contextual and secondary.

## Components

Use shadcn/ui as a technical base, then adapt:

- Radius: 8px or less for cards and controls.
- Borders: crisp neutral borders, no thick side stripes.
- Buttons: primary, secondary, ghost, destructive, icon.
- Inputs: clear focus rings, large tap targets.
- Chips: compact quick intents and preferences.
- Skeletons over centered spinners.

## Motion

150 to 220 ms transitions for state changes. Motion should clarify loading, expansion, or selection. No decorative page choreography.

## A2UI Visual Rules

- Every A2UI block must show its purpose quickly: recommendation, alternative, risk, cost, route, question, or action.
- Risk and confidence must be visible without alarmist styling.
- Unknown blocks must render in a neutral fallback with the component type visible for debugging.
- Missing or stale provider data must be labeled where it affects user trust.
