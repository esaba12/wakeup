# Task 08 — Web UI

**Read:** `docs/08-web-ui.md`, `docs/07-api-and-state.md`

**Hardware:** none

## Build

React + TypeScript + Vite in `web/`, built to static assets served by the daemon. One WebSocket connection into a small store. No polling, no SSR, no auth flow.

Four screens:
- **Now** — current state, progress, big Stop/Snooze when a routine is active, nightlight/reading shortcuts, and a persistent "next alarm in 8h 12m" line. The absence of an alarm must be visible, not implicit.
- **Alarms** — list, toggle, add/edit. Time picker, day chips, routine selector, pre-roll. "Skip tomorrow" prominent; it's the most-used control.
- **Routines** — list with a timeline showing the light curve and audio envelope over the routine duration. Form editing for simple cases, YAML editor with schema validation for the rest. Import/export.
- **Settings** — device bindings with test buttons, timezone, max volume, health panel, alarm history.

Night mode engaging during WINDDOWN/ASLEEP/SUNRISE: near-black, dim red-amber, no white, no animation. A UI that lights up the room at 2am contradicts the product.

PWA manifest and service worker so it installs to a home screen. Touch targets ≥48px. Undo toast on alarm delete. A clear "disconnected" banner rather than stale data pretending to be live.

## Done when

- [ ] Full alarm CRUD without touching a config file
- [ ] Live ramp progress updates smoothly over WebSocket
- [ ] Installs to a phone home screen and works
- [ ] Renders correctly at a 320px viewport
- [ ] You look at night mode in an actually dark room and it doesn't hurt
