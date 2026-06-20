---
version: alpha
name: Agentic Signal
register: product
description: Mobile-first product UI for Kalmio where the agent is visible enough to feel intelligent, but restrained enough to remain trustworthy for EV trip and charging decisions.

colors:
  background: "oklch(97.8% 0.009 235)"
  surface: "oklch(100% 0 0)"
  foreground: "oklch(18% 0.018 250)"
  body: "oklch(38% 0.025 245)"
  muted: "oklch(95.8% 0.017 240)"
  muted-strong: "oklch(92.2% 0.024 240)"
  muted-foreground: "oklch(45% 0.029 245)"
  border: "oklch(88.4% 0.023 240)"
  border-strong: "oklch(61% 0.038 245)"
  primary: "oklch(31% 0.09 250)"
  primary-foreground: "oklch(99% 0.003 250)"
  primary-soft: "oklch(92.2% 0.04 250)"
  link: "oklch(56% 0.19 240)"
  link-soft: "oklch(91% 0.055 240)"
  route: "oklch(57% 0.18 235)"
  route-soft: "oklch(90.5% 0.059 235)"
  assistant: "oklch(52% 0.22 315)"
  assistant-soft: "oklch(91% 0.062 315)"
  cyan: "oklch(76% 0.19 145)"
  warning: "oklch(72% 0.17 70)"
  warning-soft: "oklch(93.5% 0.061 76)"
  error: "oklch(58% 0.23 28)"
  error-soft: "oklch(91.5% 0.052 20)"

typography:
  sans: "Geist, Inter, ui-sans-serif, system-ui, sans-serif"
  mono: "Geist Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
  hero:
    fontSize: "2.55rem"
    lineHeight: "1"
    fontWeight: 600
    letterSpacing: "-0.035em"
  compact:
    fontSize: "0.875rem"
    lineHeight: "1.28rem"
  input:
    fontSize: "0.975rem"
    lineHeight: "1.3rem"
  caption:
    fontSize: "0.75rem"
    lineHeight: "1rem"

radius:
  sm: "0.625rem"
  md: "0.75rem"
  lg: "1rem"
  full: "9999px"

layout:
  app-width: "430px"
  app-height: "880px"
  hero-width: "13ch"
  chat-panel: "calc(100svh - 9rem)"
---

# Kalmio Design Direction

Kalmio uses **Agentic Signal** as its product visual system. The interface should make the assistant feel actively intelligent without becoming a generic AI demo. The user should read it as a calm EV co-driver: precise, conservative, and capable of reasoning through route, charging, uncertainty, and follow-up corrections.

The design is mobile-first. The primary surface is a compact app shell with chat, dynamic A2UI recommendations, route context, and clear actions. The map is contextual, not the home screen. Signal colors identify the agent, route, risk, and action states; they do not decorate arbitrary surfaces.

## Product Scene

A driver may be planning from a sofa, checking a route at a stop, or dealing with low battery in a car. The UI must remain readable in short sessions, small screens, imperfect light, and mild stress. This requires high contrast, familiar controls, compact hierarchy, and direct Spanish microcopy.

## Visual Principles

- **Agent visible, not theatrical.** The assistant color is allowed to be recognizable, especially in agent messages, clarification prompts, and reasoning states. Avoid glowing AI spectacle, gradients, arbitrary sparkles, and decorative effects.
- **Charging decisions first.** Route, battery, connector, reserve, confidence, and risk cues must be easier to scan than brand expression.
- **Conservative by design.** Warnings, unavailable data, provider failures, and uncertainty should feel first-class, not like edge-case errors.
- **Place-first, charger-backed.** UI should present useful stops and actions while keeping station facts traceable to backend/A2UI data.
- **No hidden confidence.** When a recommendation relies on stale, missing, estimated, or unavailable data, the visual hierarchy must expose that uncertainty.

## Color System

Agentic Signal is a restrained light system with a blue-violet primary and a stronger assistant accent.

- **Background**: `oklch(97.8% 0.009 235)` for the app frame.
- **Surface**: `oklch(100% 0 0)` for cards, controls, and message blocks.
- **Foreground**: `oklch(18% 0.018 250)` for primary text.
- **Body**: `oklch(38% 0.025 245)` for explanatory text.
- **Primary**: `oklch(31% 0.09 250)` for primary actions, active nav, and user message surfaces.
- **Route**: `oklch(57% 0.18 235)` for route/map/charger decision cues.
- **Assistant**: `oklch(52% 0.22 315)` for assistant identity and clarification/reasoning states.
- **Cyan**: `oklch(76% 0.19 145)` for positive electrical/availability accents when supported by data.
- **Warning**: `oklch(72% 0.17 70)` for reserve, medium confidence, caution, and degraded data.
- **Error**: `oklch(58% 0.23 28)` for failures, unavailable providers, invalid inputs, and unsafe assumptions.

Do not use the assistant accent as general decoration. It earns its place when the agent is asking, clarifying, repairing, or explaining reasoning boundaries.

## Typography

Use Geist as the single product type family, with Geist Mono only for compact technical labels, token previews, trace labels, and developer-facing surfaces.

- Product headings use weight 600 and tight but safe tracking.
- Body and microcopy use regular or medium weights.
- Avoid display typography in dense UI surfaces.
- Keep driver-facing labels plain: "puestos", "reserva", "confianza", "parada", "desvío", "potencia", "llegada estimada".
- Do not use "EVSE" in visible driver-facing UI. Use "puestos de carga" or compact ratios like `4/10`.
- Use "conectores" only for physical connector types such as CCS2 or Type2.

## Components

### App Shell

The shell is compact and mobile-first. Navigation should stay familiar: bottom nav on mobile, restrained side navigation on wider screens. The app should open into the task, not a marketing landing page.

### Chat

Chat is the primary interaction model. User messages use primary color. Assistant messages use surface cards with clear hierarchy. The composer stays compact, reachable, and visually stable.

Empty chat states should invite the driver to describe a route, urgency, battery, connector, or preference. They should not explain the full product.

### A2UI Cards

A2UI cards must stay inside the allowlisted catalog. The renderer controls styling; agent output provides component choices and supported semantic hints, not arbitrary presentation.

Recommended stop cards should show:

- stop/station name when traceable,
- distance or detour when traceable,
- available/total puestos when available,
- connector types,
- max power,
- estimated arrival battery when provider-backed,
- confidence,
- warnings or missing-data notes,
- one primary action and one secondary inspection action.

### Map

The map is an inspection surface. It should support the recommendation, not force the driver to inspect pins manually. If MapLibre or WebGL fails, fallback rendering must preserve route/station traceability from validated coordinates.

### Status And Risk

Risk states must be calm and explicit:

- Missing critical data: ask one clear question.
- Provider unavailable: explain that a reliable route/charging answer cannot be produced.
- Unknown live availability/pricing: do not imply freshness.
- Low reserve or uncertain arrival: use warning treatment early, before action buttons.

## Motion

Use motion for state feedback only: sending, loading, progress, map expansion, selected station, or action acknowledgement.

- Typical transitions: 150-250 ms.
- Avoid choreographed page-load sequences.
- Respect reduced motion.
- Skeletons are preferred over centered spinners inside content.

## Do

- Keep the interface calm, premium, compact, and practical.
- Use assistant color where the agent is actively participating.
- Keep charging recommendations fact-forward and traceable.
- Use semantic colors consistently for route, assistant, warning, and error states.
- Preserve stable dimensions for cards, buttons, map frames, and composer controls.
- Keep Spanish driver-facing copy direct and non-technical.

## Do Not

- Do not turn Kalmio into a generic AI chat landing page.
- Do not use decorative gradients, glow, glassmorphism, or arbitrary AI ornaments.
- Do not use the assistant color for unrelated decoration.
- Do not claim live availability, pricing, safety, or child suitability without provider-backed or traced data.
- Do not expose arbitrary UI outside the A2UI catalog.
- Do not label EVSE capacity as connectors.
- Do not make the frontend decide EV planning outcomes.

## Implementation Notes

The selected `Agentic Signal` token values are implemented in `frontend/src/index.css` as the global Tailwind/theme variables. The preview in `frontend/src/App.tsx` remains useful as a local comparison surface while the visual direction is being evaluated.

When token values change, update:

- `frontend/src/index.css` theme variables,
- shadcn token usage if needed,
- A2UI renderer state treatments,
- screenshots or visual regression references,
- this document if token values change.
