# 05 — Scheduler

## Purpose
Decide *when* things fire, correctly, forever, including across DST, reboots, power cuts, clock steps, and offline periods. This is the component most likely to embarrass the project.

## Model

```python
@dataclass
class Alarm:
    id: str
    enabled: bool
    time: time                  # local wall time, e.g. 06:40
    days: set[int]              # ISO weekday 1–7; empty = one-shot
    routine_id: str
    pre_roll_s: int             # ramp ENDS at `time`; starts at time - pre_roll
    skip_next: bool = False     # "not tomorrow"
    last_fired_at: datetime | None = None   # persisted
    timezone: str               # IANA, e.g. "America/Detroit"
```

## Rules

1. **Wall clock polling, never long sleeps.** Tick every 15 s. On each tick compute `next_fire` and fire if `now >= next_fire` and it hasn't fired for that occurrence. A `sleep(28800)` breaks across suspend, NTP steps, and DST.
2. **Timezone-aware local time, always.** `zoneinfo`, never a fixed UTC offset. Recompute `next_fire` on every tick — do not cache across a DST boundary.
3. **DST spring-forward:** an alarm at a time that does not exist that day (02:30 on a US spring-forward Sunday) fires at the first valid instant after it (03:00). Never skip it.
4. **DST fall-back:** an alarm at a time that occurs twice fires **once**, on the first occurrence. Deduplicate via `last_fired_at` compared against the local calendar date + alarm id.
5. **Pre-roll:** the sunrise ramp starts at `next_fire − pre_roll_s`. The scheduler therefore has two events per alarm: `ramp_start` and `alarm_fire`. Both are recomputed from wall clock; missing `ramp_start` (e.g. host was booting) means starting the ramp partway through, not skipping it.
6. **Catch-up window.** On startup, if an alarm was due within the last `catchup_s` (default 600) and did not fire, fire it now. Outside that window, mark it missed and log it. This is what makes a 4am power blip survivable.
7. **Idempotency.** `(alarm_id, local_date)` is the occurrence key. Written to SQLite before any side effect, so a crash mid-fire can't double-fire.
8. **Skip-next** is the most-used feature of any real alarm clock. It clears automatically after the skipped occurrence passes.

## Time source

```
boot → read RTC (if present) → set system clock
     → start NTP (chrony/systemd-timesyncd)
     → on NTP sync: write corrected time back to RTC
     → hourly: compare system vs RTC; drift > 30s ⇒ warn in /api/health
```

- **RTC:** DS3231, I²C, ±2 ppm (~1 min/year). Strongly recommended on any host without a battery-backed clock — which includes every Raspberry Pi. Without it, a boot with no internet has no idea what time it is and *will* fire an alarm at the wrong moment or not at all.
- If neither NTP nor RTC has ever provided a time this boot, the scheduler enters `UNSAFE_CLOCK`: it refuses to fire alarms, sets health to degraded, and the UI shows it loudly. Silently firing on a bogus clock is worse than not firing.

## Persistence
SQLite, WAL mode, `synchronous=FULL` for the alarms table. Tables: `alarms`, `occurrences(alarm_id, local_date, fired_at, outcome)`, `events`. `occurrences` is also the audit log that answers "did it actually go off?" — surface it in the UI.

## Interface

```python
class Scheduler:
    async def start(self) -> None
    async def next_events(self, limit: int = 5) -> list[ScheduledEvent]
    async def upsert(self, alarm: Alarm) -> Alarm
    async def delete(self, alarm_id: str) -> None
    async def skip_next(self, alarm_id: str) -> None
    def subscribe(self, handler: Callable[[SchedulerEvent], Awaitable[None]]) -> None
```

Emits: `ramp_start`, `alarm_fire`, `alarm_missed`, `clock_unsafe`, `preflight_failed`.

## Preflight
At **T−5 min** before every `alarm_fire`, run the health checks from specs 02 and 04 (light reachable, audio openable) and emit `preflight_failed` with details if anything is down, so the fallback chain (spec 10) can arm *before* it's needed rather than discovering the problem at fire time.

## Testing
All tests use an injected clock; no `sleep()` in tests.
- [ ] Spring-forward: 02:30 alarm fires once, at 03:00 local
- [ ] Fall-back: 01:30 alarm fires exactly once
- [ ] Timezone change (travel): alarm follows the configured IANA zone
- [ ] Restart 2 min before fire: fires on time
- [ ] Restart 3 min after fire time with catch-up enabled: fires immediately, once
- [ ] Restart 3 hours after: marks missed, does not fire
- [ ] Clock stepped backward 1 h mid-day: no double fire
- [ ] `UNSAFE_CLOCK` blocks firing and reports degraded health
