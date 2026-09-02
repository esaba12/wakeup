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

**Task 01 done.** Next up: **task 02 — light interface**.

| # | Task | Hardware needed | Status |
|---|---|---|---|
| 01 | Project scaffold, tooling, CI | none | done |
| 02 | Light interface, curves, MockLight | none | ⬅ next |
| 03 | Sunrise engine + tests | none | not started |
| 04 | Scheduler (alarms, DST) | none | not started |
| 05 | Routine engine | none | not started |
| 06 | Audio playback | laptop speakers | not started |
| 07 | REST + WebSocket API | none | not started |
| 08 | Web UI | none | not started |
| 09 | LIFX driver | the bulb | not started |
| 10 | Packaging + deploy | the Pi | not started |

## Notes / decisions log

Append anything a future session needs that isn't obvious from the code or specs (deviations from a task file, spec ambiguities resolved, hardware quirks hit during testing).

- (none yet)

## When to buy hardware

- **After task 03** — open `tools/sunrise-visualizer.html` in a browser, tune the curve.
- **Before task 09** — LIFX Color A19 (~$20). Run the bulb acceptance test in `docs/02-light-driver.md` first.
- **Before task 10** — Raspberry Pi (~$40).
