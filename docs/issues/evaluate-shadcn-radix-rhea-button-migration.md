# Evaluate shadcn radix-rhea Button migration

## Context

During the shadcn chat components migration, the new chat primitives were available via explicit `radix-rhea` registry URLs, not via this project's current `new-york` simple-name registry path.

The `radix-rhea` chat components list `button` as a registry dependency. The dry-run showed that accepting the registry dependency would overwrite `frontend/src/components/ui/button.tsx`. We intentionally did not accept that overwrite in the chat migration because Kalmio's current `Button` is a global, product-styled primitive used across chat, A2UI cards, composer controls, sidebar, dialogs, and actions.

## Why this should be separate

The upstream `radix-rhea` button differs from Kalmio's current button in global visual and API behavior, including:

- shape: current `rounded-full` vs upstream `rounded-md` defaults,
- sizing: current `h-10`, `size-10` icon vs upstream `h-9`, `h-9 w-9`, plus `icon-sm` / `icon-xs`,
- token vocabulary: current Kalmio tokens such as `bg-surface`, `bg-error`, `border-border` vs upstream shadcn defaults such as `bg-secondary`, `bg-destructive`, `border-input`, `bg-accent`,
- variants: upstream adds/changes variants such as `link`, `destructive`, and smaller icon sizes,
- implementation: upstream uses `forwardRef` and exports `buttonVariants`.

This is a design-system migration, not a chat-only migration.

## Proposed work

- Compare current `frontend/src/components/ui/button.tsx` with the `radix-rhea` registry button using `npx shadcn@latest add <radix-rhea chat registry url> --diff src/components/ui/button.tsx` or the current shadcn registry workflow.
- Decide whether Kalmio should:
  - fully adopt the upstream `radix-rhea` button,
  - partially merge API improvements such as `forwardRef`, `buttonVariants` export, `link`, `icon-sm`, and `icon-xs`, while preserving Kalmio visuals,
  - or keep the current Kalmio button and maintain local adapters in chat primitives.
- If changing `Button`, audit every consumer:
  - chat composer and empty prompts,
  - A2UI action buttons,
  - station/detail cards,
  - dialogs/sheets,
  - sidebar/new-chat controls,
  - auth/history/settings surfaces if present.
- Preserve Agentic Signal tokens and Kalmio's mobile-first visual language unless a deliberate design-system update is made.

## Acceptance criteria

- `Button` API supports any sizes/variants required by installed shadcn chat primitives without ad hoc workarounds.
- Existing Kalmio screens do not visually regress or unexpectedly change density/shape.
- A2UI action buttons remain compact, readable, and accessible on mobile.
- Chat composer controls remain stable and do not shift on hover/focus/disabled states.
- Focus, disabled, hover, active, and loading compositions remain accessible.
- `npm run lint`, `npm run build`, and `npm test` pass.
- Manual/browser smoke check covers desktop and mobile chat, A2UI catalog review, station decision cards, and dialogs/sheets.

## Notes

The chat components migration added adapted local primitives for `MessageScroller`, `Message`, `Bubble`, `Marker`, and `Attachment` without overwriting `Button`. See `docs/shadcn-chat-components-migration-2026-06-27.md` for the migration notes.
