# shadcn Chat Components Migration Review

Date: 2026-06-27

## Summary

shadcn has announced chat-specific primitives for conversation UI: `MessageScroller`, `Message`, `Bubble`, `Attachment`, and `Marker`.

Kalmio migrated the chat shell to these primitives without changing the EV/A2UI domain cards. The current registry style used by this project (`new-york`) does not expose the new items by simple name:

```bash
cd frontend
npx shadcn@latest search @shadcn -q "message"
npx shadcn@latest docs message bubble attachment marker message-scroller
npx shadcn@latest add message-scroller message bubble attachment marker --dry-run
```

Observed result with `shadcn` CLI `4.12.0`: search/docs do not find the items and `add --dry-run` returns 404 for `https://ui.shadcn.com/r/styles/new-york/message-scroller.json`.

Updating the CLI does not currently unblock this. `npm view shadcn dist-tags --json` reports `latest: 4.12.0`; `canary: 4.2.0-canary.0` is older and returns the same registry 404 for these items.

The components are available through the `radix-rhea` registry URLs:

```bash
cd frontend
npx shadcn@latest add \
  https://ui.shadcn.com/r/styles/radix-rhea/message-scroller.json \
  https://ui.shadcn.com/r/styles/radix-rhea/message.json \
  https://ui.shadcn.com/r/styles/radix-rhea/bubble.json \
  https://ui.shadcn.com/r/styles/radix-rhea/attachment.json \
  https://ui.shadcn.com/r/styles/radix-rhea/marker.json \
  --dry-run
```

The dry-run works, but it would create five chat component files and overwrite `src/components/ui/button.tsx`. Kalmio did not accept that overwrite: the chat primitives were adapted to the existing product-styled button instead.

Do not copy component source manually from the rendered docs unless the CLI/registry path remains blocked and there is an explicit decision to vendor the code. Prefer registry URLs plus local adaptation.

## Fit For Kalmio

Implemented migration targets:

- `MessageScroller`: replace the custom `.chat-scroll` container in `frontend/src/App.tsx`.
- `Message` and `Bubble`: replace custom markup/classes for `UserMessage` and `AssistantMessage` rendering in `frontend/src/components/a2ui/a2ui-renderer.tsx`.
- `Marker`: installed as a UI primitive, but not currently used in chat runtime.
- `Attachment`: installed as a UI primitive, but not currently used until Kalmio adds image/file input, vehicle screenshots, charger receipts, or route exports.

Keep custom/Kalmio-owned:

- A2UI catalog components in `frontend/src/lib/a2ui/kalmio-catalog.json`.
- EV planning cards in `frontend/src/components/a2ui/a2ui-renderer.tsx`.
- Backend validation, protocol envelopes, data traceability, and action handling.
- Agent component choice rules: do not map natural-language intents directly to UI primitives in backend code.

## Implementation Notes

1. Used explicit registry URLs.
   `new-york` simple-name install is currently not enough. The implementation used the `radix-rhea` URLs above as the source.

2. Preserved Kalmio's global `Button`.
   The `radix-rhea` components assume button sizes such as `icon-sm` / `icon-xs`. Kalmio adapted the chat components to existing `Button` semantics instead of replacing the global button.

3. Added `@shadcn/react`.
   `MessageScroller` requires `@shadcn/react`. The dependency is now present in `frontend/package.json`.

4. Kept A2UI as the domain boundary.
   The frontend renders message shell primitives; factual EV content remains sourced from validated A2UI blocks and data models.

5. Kept renderer compatibility.
   `A2UIRenderer` can still render outside the chat scroller in tests and catalog review. It only uses `MessageScrollerItem` when the chat host passes `useMessageScrollerItems`.

6. Reused Kalmio tokens.
   Message and bubble styling uses existing Agentic Signal tokens and spacing. Missing `radix-rhea` utilities such as `scroll-fade-*`, `scrollbar-*`, and `shimmer` were not added unless needed by adapted components.

7. Verified behavior.
   `npm run lint`, `npm run build`, and `npm test` pass. A browser smoke check verified empty chat, mocked message bubbles, mobile/desktop layout, and clean console with mocked backend responses.

## Non-Goals

- Do not migrate Kalmio to a generic AI chat template.
- Do not let shadcn chat primitives become an external A2UI contract.
- Do not add attachment UX until the backend can validate and process attachments safely.
- Do not change agent/backend intent handling as part of this UI migration.
