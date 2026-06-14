# Frontend Design

## Direction

Kalmio uses a precise product UI inspired by the Vercel design.md reference: crisp structure, strong contrast, compact hierarchy, and Geist-like sans typography. It adds more color through intentional semantic accents for safety, route context, risk, and assistant state.

The supplied `[Image #1]` anchors the mobile composition: compact green brand header, direct greeting and question, pill-like text input, icon quick prompts, soft white cards, chat bubbles, route preview, and full-width green primary actions.

## Theme

Default to a light, near-white mobile UI because drivers will often use it in daylight or in a parked car before departure. Dark mode can come later, but the first production path should prove a readable, calm daylight experience.

## Tokens

Use OKLCH CSS variables when Tailwind is configured:

- `--background`: warm near-white.
- `--foreground`: soft black with a slight green tint.
- `--muted`: cool gray-green surface.
- `--primary`: electric green.
- `--warning`: amber.
- `--route`: clear blue.
- `--assistant`: violet.
- `--border`: low-chroma neutral.

Never use pure `#000` or `#fff`.

## App Shell

- Mobile-first.
- Top brand row with Kalmio and account affordance.
- Main content scroll area.
- Bottom navigation: Home, Activity, Settings.
- Route-planning input on home, sized for thumb use.

## Component Style

- Radius: 8px max for cards and controls.
- Border: 1px neutral, no thick side accents.
- Shadows: minimal, only to separate overlays or sticky composer.
- Cards: only for A2UI blocks, route status, and repeated records.
- Icons: lucide-react when available.

## Interaction States

Every interactive primitive needs default, hover, focus-visible, active, disabled, and loading states. Skeletons should represent loading content areas.

## Responsive Rules

Mobile is the primary surface. Desktop should look like a centered app workspace with useful side context, not a stretched phone.
