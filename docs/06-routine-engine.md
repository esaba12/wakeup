# 06 — Routine Engine

## Purpose
Execute multi-step sequences that coordinate light and audio over time — wind-down, sleep, sunrise, alarm, snooze. This is the abstraction that makes the product a product rather than a script.

## State machine

```
        ┌──────┐
        │ IDLE │◀──────────────────────────────┐
        └──┬───┘                               │
    manual │  scheduler:ramp_start             │ complete / cancel
           ▼                                   │
      ┌──────────┐   auto    ┌────────┐        │
      │ WINDDOWN │──────────▶│ ASLEEP │        │
      └──────────┘           └───┬────┘        │
                                 │ ramp_start  │
                                 ▼             │
                           ┌──────────┐        │
                           │ SUNRISE  │        │
                           └────┬─────┘        │
                                │ alarm_fire   │
                                ▼              │
                          ┌───────────┐        │
                          │  ALARM    │────────┤ dismiss
                          └────┬──────┘        │
                        snooze │  ▲            │
                               ▼  │ re-fire    │
                          ┌───────────┐        │
                          │  SNOOZE   │────────┘
                          └───────────┘
```

Exactly one routine is active at a time. A new routine cancels the current one cleanly (each step gets an `on_cancel` that restores or releases devices). Transitions are persisted before side effects.

## Routine schema

Routines are **data**, shareable as files. This is the community surface of the project.

```yaml
version: 1
name: "Weekday wake"
id: weekday-wake
trigger: { type: alarm, ref: alarm_morning }
steps:
  - id: sunrise
    duration: 30m
    ends_at: trigger              # ramp completes AT the alarm, not starts
    light:
      curve: sunrise-classic
      to: { brightness: 0.9, cct: 4500 }
    on_cancel: { light: { "off": true } }   # quoted: bare `off` parses as YAML boolean False

  - id: chime
    at_offset: -3m                # relative to trigger
    audio:
      source: "file:chimes/windchime.flac"
      gain_db: -45
      ramp_to_db: -14
      over: 4m
    escalate_after: 60s

snooze:
  duration: 9m
  max: 3
  light: { hold: true }           # keep the light up during snooze
  audio: { stop: true }
```

```yaml
version: 1
name: "Wind-down"
id: winddown
trigger: { type: time, at: "22:30", days: [1,2,3,4,5] }
steps:
  - id: settle
    duration: 10m
    light: { brightness: 0.4, cct: 2400, transition: 2m }
    audio: { source: "file:rain.flac", gain_db: -28, fade_in: 30s }
  - id: dim
    duration: 20m
    light: { curve: reverse-sunrise, reverse: true, to: { brightness: 0.02, cct: 1800 } }
  - id: sleep
    duration: until_cancel
    light: { "off": true }
    audio: { continue: true, sleep_timer: 45m, fade_out: 5m }
```

### Schema rules
- Durations: `30m`, `90s`, `until_cancel`, `until_next_step`.
- Steps are either `duration`-based (sequential) or `at_offset`-based (anchored to the trigger, may overlap earlier steps — the chime overlaps the tail of the sunrise, which is the point).
- `light` and `audio` blocks are independent; a step may set one, both, or neither.
- A curve-based `light` block takes an optional `reverse: bool` (default `false`). docs/03-sunrise-engine.md's engine runs a curve with `t -> 1-t` for a wind-down; the routine schema needs to say which direction a given step wants, since the same curve file could in principle be run either way — `reverse` is that switch. `winddown`'s `dim` step sets it.
- Unknown keys are a hard validation error, not ignored — a typo in someone's shared routine should fail loudly at load, not silently at 6am.
- YAML gotcha: `off` (and `on`/`yes`/`no`) are bare-word booleans in default YAML 1.1 parsing, so a `light` block's `off` key must be quoted (`"off": true`) or it parses as the boolean key `False`, not the string `"off"`. Both examples above quote it.
- Schema is versioned (`version: 1`) with a migration path.

## Executor

```python
class RoutineRun:
    routine: Routine
    started_at: datetime
    trigger_at: datetime
    current_step: str
    state: RoutineState
    # persisted in full; reconstructible from (routine_id, started_at, trigger_at)
```

- **Position is recomputed from wall clock on every tick and on startup.** Restart at minute 17 of a 30-minute sunrise resumes at minute 17.
- Each step delegates to the light engine (spec 03) and audio output (spec 04); the executor owns only sequencing.
- Every transition emits an event on the bus (spec 07). The UI and the physical puck are pure subscribers.
- Cancellation is cooperative and always runs `on_cancel` for the active step.

## Snooze semantics
Snooze is a known source of bugs in this category. Rules:
- Snooze during `ALARM` stops audio, optionally holds light, and schedules a re-fire at `now + duration`.
- Snooze during `SUNRISE` (before alarm time) is treated as **dismiss for today**, not snooze. Snoozing something that hasn't fired yet is meaningless and produces the weird behavior widely reported in DIY sunrise implementations.
- `max` snoozes then force the alarm to full escalation and refuse further snoozes.

## Acceptance criteria
- [ ] Routine files validate against a published JSON Schema; invalid ones fail at load with a line number
- [ ] Kill -9 at any point during any routine, restart, and the run resumes at the correct position
- [ ] `until_cancel` steps survive indefinitely without leaking timers
- [ ] Starting routine B while A is running leaves no orphaned device state
- [ ] Full routine executes end-to-end against mocks in <2s of test wall time with an injected clock
