# Task 05 — Routine engine

**Read:** `docs/06-routine-engine.md`, `docs/03-sunrise-engine.md`

**Hardware:** none

## Build

- `core/routines.py` — the routine schema, loader, and executor.
  - Pydantic models for the YAML schema in spec 06, `version: 1`
  - Unknown keys are a hard validation error with a line number, not ignored
  - Duration parsing: `30m`, `90s`, `until_cancel`, `until_next_step`
  - Sequential `duration` steps and trigger-anchored `at_offset` steps, which may overlap
  - The state machine: `IDLE → WINDDOWN → ASLEEP → SUNRISE → ALARM → SNOOZE → AWAKE`
  - Exactly one active routine; starting another cancels the first and runs its `on_cancel`
  - `RoutineRun` position recomputed from wall clock on every tick and on startup
  - Every transition publishes to the event bus
- Snooze semantics from spec 06: snooze during `ALARM` re-fires; snooze during `SUNRISE` is dismiss-for-today, not snooze. `max` snoozes forces full escalation.
- Ship `routines/weekday-wake.yaml` and `routines/winddown.yaml` matching the spec examples.
- Publish the routine JSON Schema to `routines/schema.json`.

Audio blocks call an `AudioOutput` Protocol that doesn't exist yet — define the Protocol in `drivers/audio/base.py` now and use a mock. Task 06 implements it.

## Done when

- [ ] Both shipped routines validate; a routine with a typo'd key fails at load with a line number
- [ ] Kill the executor at 10 points in a routine, reconstruct, and it resumes at the correct step and position
- [ ] `until_cancel` steps run indefinitely without leaking timers
- [ ] Starting routine B while A runs leaves no orphaned device state (mock asserts final state)
- [ ] Full routine executes end-to-end in under 2 seconds of test wall time with a fake clock
- [ ] Snooze during SUNRISE dismisses rather than snoozing
