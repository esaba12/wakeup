# 10 — Reliability & Failure Handling

## Purpose
An alarm clock has one requirement a web app doesn't: **it must work at 6:40am even though something broke at 3am and nobody noticed.** This spec is the difference between this project and the dozen existing DIY sunrise clocks.

## Principle
Every path to waking the user must have a strictly simpler fallback beneath it. Degrade, never fail silently.

```
light + audio  →  audio only  →  buzzer  →  logged failure + morning-after notice
```

## Failure matrix

| Failure | Detection | Response |
|---|---|---|
| Bulb unreachable | Preflight T−5min; `is_reachable()` during ramp | Audio-only alarm at +6 dB; event logged; UI warns next morning |
| Audio device gone (USB pulled, BT unpaired) | Preflight T−5min opens the device | GPIO piezo buzzer fires at alarm time. A $1 part is what makes the device trustworthy. |
| Network sink unreachable (AirPlay/Cast/BT) | Preflight pre-connects | Fall back to local audio if configured, else buzzer |
| Wi-Fi down | Gateway ping every 60s | Scheduling and audio are local and unaffected; only light control degrades |
| Daemon crash | systemd `Restart=always`, `RestartSec=2` | State reconstructed from SQLite; ramp resumes at wall-clock position |
| mpv crash | IPC socket read fails | Respawn within 5s, resume playback at current gain |
| Host hang | Hardware watchdog: `dtparam=watchdog=on` + systemd `RuntimeWatchdogSec=15` | Reboot; catch-up window (spec 05) fires a recently-missed alarm |
| Power outage overnight | Boot detected, RTC supplies time | Boot <60s; if the alarm came due during boot and is <10min stale, fire immediately |
| SD card corruption | — | Read-only root + overlayfs; only `/var/lib/openrestore` writable (spec 12) |
| Clock never synced this boot | No NTP, no RTC | `UNSAFE_CLOCK`: refuse to fire, degrade health, shout in the UI. Firing on a bogus clock is worse than not firing. |
| Undervoltage (Pi) | `vcgencmd get_throttled` | Report in health; it manifests as mysterious 4am Wi-Fi drops |
| No alarm actually set | — | Home screen always shows next-alarm-or-none; absence must be visible |
| Bad routine config | Schema validation at load | Refuse to load, keep the previous routine, report the error with a line number |

## `/api/health`

Not boilerplate — it's the endpoint preflight hits and the thing that tells a user something is broken *before* it matters.

```jsonc
{
  "status": "ok",                       // ok | degraded | unsafe
  "checks": {
    "clock":  { "ok": true, "source": "ntp", "drift_s": 0.3 },
    "light":  { "ok": true, "id": "lifx-...", "last_seen_s": 4 },
    "audio":  { "ok": true, "output": "usb-cm108", "opened": true },
    "storage":{ "ok": true, "free_mb": 1840, "readonly_root": true },
    "power":  { "ok": true, "throttled": "0x0" },
    "puck":   { "ok": false, "last_seen_s": 9124 }
  },
  "next_alarm": "2026-09-03T06:40:00-04:00",
  "degraded_since": null
}
```

## Preflight (T−5 minutes)
1. Clock sane and synced
2. Light reachable (a real round-trip, not a cached flag)
3. Audio device openable + inaudible test tone
4. Fallback buzzer present (GPIO readable)
5. Free disk space

Result is persisted and emitted as `preflight.failed` with details. The routine engine arms the appropriate fallback tier *before* the alarm, not at it.

## Audit trail
Every alarm occurrence writes `{alarm_id, local_date, fired_at, outcome, path_used}` where `path_used ∈ {full, audio_only, buzzer, missed}`. Surface the last 7 days in the UI. "Did it actually fire?" must be answerable, and this table is where the real bugs show up.

## Morning-after notice
If any degradation occurred overnight, the Now screen shows a dismissible banner explaining what happened. Silent degradation trains users to distrust the device; explained degradation does the opposite.

## Acceptance criteria
- [ ] Chaos suite: kill the daemon, unplug the bulb, unplug the dongle, step the clock, cut power — at 10 points across a routine. Alarm still wakes the user in every case, or logs precisely why not.
- [ ] Buzzer fallback verified by physically unplugging audio 4 minutes before an alarm
- [ ] Read-only root survives 100 forced power cuts without filesystem corruption
- [ ] Watchdog verified with a deliberate hang
