# 08 — Web UI

## Purpose
A phone-sized control surface for setup and configuration. Explicitly *not* the primary runtime interface — the physical controls are (spec 09). If the UI is the only way to use the device, the project has failed its own premise.

## Stack
React + TypeScript + Vite, built to static assets served by the daemon. No SSR, no backend framework, no auth flow. Installable PWA (manifest + service worker) so it lives on the home screen without an app store.

State: one WebSocket connection feeding a small store. No polling. No client-side clock math beyond rendering server-provided values.

## Screens

**Now** — the default. Large current-state readout: what's running, progress ring, time until next alarm. Big Stop / Snooze buttons when a routine is active. Nightlight and Reading shortcuts. A persistent "Next alarm in 8h 12m" line: the *absence* of an alarm must be visible, not implicit — silently having no alarm set is the #1 real-world failure of every alarm clock.

**Alarms** — list, toggle, add/edit. Time picker, day-of-week chips, routine selector, pre-roll duration. Per-alarm "skip tomorrow" toggle prominently placed; it's the most-used control.

**Routines** — list of routines with a visual timeline of steps (a horizontal bar showing light curve + audio envelope over the routine duration). Edit as a form for simple cases, raw YAML editor with schema validation for the rest. Import/export as a file.

**Settings** — device bindings (which bulb, which audio output, with test buttons), timezone, max volume ceiling, fallback behavior, health panel, alarm history.

## Night theme
Default dark. A separate **night mode** that engages during WINDDOWN/ASLEEP/SUNRISE: near-black background, dim red-amber foreground, no white, no animation, reduced font weight. Someone opening this at 2am should not get a face full of light — and a UI that violates its own product thesis is a bad look.

## Accessibility & ergonomics
- Touch targets ≥48px; assume one thumb, in the dark, half asleep
- No destructive action without undo (deleting an alarm shows a 5s undo toast)
- Works offline as a shell; shows a clear "disconnected from device" banner rather than stale data pretending to be live
- Renders correctly on a 320px viewport

## Acceptance criteria
- [ ] Full alarm CRUD without touching a config file
- [ ] Live ramp progress updates smoothly over WebSocket
- [ ] Lighthouse PWA installable, works added-to-home-screen
- [ ] Night mode verified by looking at it in an actually dark room
