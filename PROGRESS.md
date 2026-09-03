# Progress

Tracks where the build stands and what to do next. Read this file first in any new session.

## Workflow (per `START-HERE.md`)

One task per session, one commit per task:

1. Read this file to see the next unstarted task.
2. `Read tasks/NN-<name>.md and do it.`
3. Claude reads the task file and the specs it names, then builds.
4. Review the diff (`git diff`). Actually run the tests — don't take "tests pass" on faith.
5. Commit: `git commit -am "task NN: <what>"`
6. Update the table below: mark the task done, move the arrow to the next row.
7. `/clear` and start the next task in a fresh session.

If a task goes badly: `git reset --hard HEAD`, then re-run with a note about what went wrong appended to the prompt. Fixing a bad attempt in the same session usually costs more than starting clean.

**Do not run several tasks in one session.** Context fills with irrelevant detail from earlier tasks and quality drops.

## Status

**Task 03 done.** Next up: **task 04 — scheduler**.

Before task 04: open `tools/sunrise-visualizer.html` and tune the CCT keyframes in `curves/sunrise-classic.yaml` (per task 03's "Then, before task 04" note) — not yet done this session.

| # | Task | Hardware needed | Status |
|---|---|---|---|
| 01 | Project scaffold, tooling, CI | none | done |
| 02 | Light interface, curves, MockLight | none | done |
| 03 | Sunrise engine + tests | none | done |
| 04 | Scheduler (alarms, DST) | none | ⬅ next |
| 05 | Routine engine | none | not started |
| 06 | Audio playback | laptop speakers | not started |
| 07 | REST + WebSocket API | none | not started |
| 08 | Web UI | none | not started |
| 09 | LIFX driver | the bulb | not started |
| 10 | Packaging + deploy | the Pi | not started |

## Notes / decisions log

Append anything a future session needs that isn't obvious from the code or specs (deviations from a task file, spec ambiguities resolved, hardware quirks hit during testing).

- **Task 02:** `core/curves.py` deliberately does *not* implement `curve.color_at(t, b)` from spec 03's `run_ramp` pseudocode. The spec's `sunrise-classic.yaml` example has an isolated `rgb` keyframe at t=0 with no defined blend behavior into the surrounding CCT keyframes over a step interval — that's a real design decision, not a config-loading detail, so it's left for task 03 (`core/sunrise.py`) to make deliberately rather than guessed here. `Curve` currently exposes `.brightness(t)` and `.cct_at(t)` only; task 03 will need to add the brightness/CCT/RGB composition into a `LightState`.
- **Task 02:** Added `types-PyYAML` to the `dev` extras (needed for `mypy --strict` on `core/curves.py`; user approved).
- **Task 02:** `reverse-sunrise.yaml` is authored as a normal forward curve (t=0 → 1800K, t=1 → 2700K) on the assumption that task 03's engine applies spec 03's stated `t → 1-t` inversion when running a wind-down, per "Reverse ramp: the same engine with t → 1-t and different keyframes." If task 03 goes a different route, this file's keyframes will need to flip.
- **Task 03:** Confirmed the `t → 1-t` assumption above — `run_ramp(..., reverse=True)` inverts curve position, so `reverse-sunrise.yaml`'s keyframes didn't need to change.
- **Task 03:** `curve.color_at(t, b)` from spec 03's pseudocode ended up split: `Curve.rgb_at(t)` (holds the last-seen `rgb` keyframe forward, in `core/curves.py`) plus `core/sunrise.py`'s `color_at(curve, light, t, b)`, which decides RGB-vs-CCT by comparing the curve's interpolated CCT against `light.capabilities.cct_range[0]` — i.e. use RGB only when the light can't reach the target CCT, reverting to CCT mode once the ramp's target CCT rises back into range. No extra state needed; it falls out of comparing `cct_at(t)` to the light's floor each tick.
- **Task 03:** `run_ramp`'s final apply (after the loop) reuses the loop's own `curve.brightness(t) * target_brightness` clamp formula at `t=1` (forward) or `t=0` (reverse), rather than spec 03's literal `curve.color_at(1.0, target_brightness)`. They're identical for forward ramps (every brightness model hits exactly 1.0 at t=1), but the literal reading breaks a reverse ramp — it would jump the wind-down back up to its *starting* brightness instead of ending near the floor/off. Flagging this as a spec-03 pseudocode gap: the reverse-ramp case needs its own final-apply line, not literal reuse of the forward one.
- **Task 03:** Presets `nightlight_state`/`reading_state`/`off_state` live in `core/sunrise.py`. `nightlight` prefers pure red RGB over a light's lowest CCT whenever the light supports RGB — spec 03 lists both as options without a selection rule; red was chosen since it best preserves night vision, which is the preset's stated goal.

## When to buy hardware

- **After task 03** — open `tools/sunrise-visualizer.html` in a browser, tune the curve.
- **Before task 09** — LIFX Color A19 (~$20). Run the bulb acceptance test in `docs/02-light-driver.md` first.
- **Before task 10** — Raspberry Pi (~$40).
