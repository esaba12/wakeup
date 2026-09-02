# Task 04 — Scheduler

**Read:** `docs/05-scheduler.md`

**Hardware:** none

## Build

The component most likely to embarrass the project. Get it right with tests, not by running it overnight.

- `core/store.py` — SQLite via `aiosqlite`, WAL mode, `synchronous=FULL` on alarms. Tables: `alarms`, `occurrences`, `events`. Migrations as numbered SQL files.
- `core/scheduler.py` — the `Alarm` model and `Scheduler` interface from spec 05.
  - 15-second wall-clock tick, never a long sleep
  - timezone-aware local time via `zoneinfo`, `next_fire` recomputed every tick
  - DST: spring-forward fires at the first valid instant; fall-back fires exactly once
  - `pre_roll_s` produces two events per alarm, `ramp_start` and `alarm_fire`
  - startup catch-up window (default 600s), `alarm_missed` outside it
  - `(alarm_id, local_date)` occurrence key written before any side effect
  - `skip_next`, auto-clearing after the skipped occurrence passes
  - `UNSAFE_CLOCK` state that refuses to fire when no time source has ever synced this boot

Preflight hooks (T−5min) are stubs here; task 10 fills them in.

## Done when

Every test uses an injected clock; none call `sleep()`.

- [ ] Spring-forward: an alarm at 02:30 fires once, at 03:00 local
- [ ] Fall-back: an alarm at 01:30 fires exactly once
- [ ] Restart 2 min before fire → fires on time
- [ ] Restart 3 min after fire time → fires immediately, exactly once
- [ ] Restart 3 hours after → marks missed, does not fire
- [ ] Clock stepped backward 1 hour mid-day → no double fire
- [ ] `UNSAFE_CLOCK` blocks firing and reports degraded
- [ ] `skip_next` skips exactly one occurrence and clears itself
