# HFabric Theme QA

Use this checklist whenever shared UI tokens, controls, or theme colors change.

## Required Views

- Images: composer, result stage, queue, empty no-model state, thumbnail rail.
- History: filters, active chips, selection mode, favorite marker, detail modal.
- LLM: empty state, long answer, code block, user bubble, attachments, model settings.
- Voice: live console, sliders, status tiles, disabled/off states, warning panels.
- System: memory timeline, queue plan, learned profiles table, diagnostics card.
- Models: curated downloads, Hugging Face browser, installed model manager.
- Overlays: Command Palette, Welcome, Auth token lock, Prompt Library, image lightbox.

## Desktop

- 2560x1440: dense layout should feel intentional; no text clipped in fixed toolbars.
- 1920x1080: panels remain usable; action rows wrap without overlapping.
- 1366x768: main workspaces still scroll predictably.

## Mobile / Narrow

- 860px and below: stacked panels must keep stable heights and readable controls.
- 390px: no button label should overflow its rounded container.

## Theme Checks

- Dark: media canvases remain deep; subtle text is visible but quiet.
- Dim: accent color differs from dark and still passes for small labels.
- Light: app chrome is paper/graphite, not an inverted dark theme.
- Light: `text-white/*`, `bg-black/*`, and `border-white/*` are acceptable only when
  remapped by tokens or used intentionally for true media overlays/lightboxes.
- Light: primary buttons use a full accent fill with white/inverse text.
- Light: tinted badges and notices use dark semantic text, not pale dark-mode text.
- Light: generated images sit on a neutral/dark inspection stage, not a pure white card.

## Interaction Checks

- Keyboard focus ring is visible on all controls.
- Hover states are visible but do not resize controls.
- Disabled states are obvious and still readable.
- Popovers and select menus match the active theme.
- Destructive actions are red/error toned in both themes.
