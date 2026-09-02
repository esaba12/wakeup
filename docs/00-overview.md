# 00 — System Overview

**Project:** OpenRestore — an open-source bedside sleep clock built from a smart bulb in a lamp you already own, a speaker you already own, and a small Linux host.

**Reference host:** Raspberry Pi Zero 2 W. **Requirement:** nothing in the design may *depend* on it.

---

## Specs in this set

| # | Spec | Owns |
|---|---|---|
| 01 | Hardware platform | Host requirements, portability tiers, what runs where |
| 02 | Light driver | Bulb selection, `Light` interface, per-vendor drivers |
| 03 | Sunrise engine | Perceptual brightness/CCT curves, ramp execution |
| 04 | Audio subsystem | Output paths, player control, volume ramping |
| 05 | Scheduler | Alarms, recurrence, DST, persistence, drift |
| 06 | Routine engine | Step state machine, routine schema |
| 07 | API & state | REST, WebSocket, event bus, state shape |
| 08 | Web UI | PWA, screens, night theme |
| 09 | Physical controls | Encoder, button, display, RTC, ESP32 puck |
| 10 | Reliability | Health checks, fallbacks, watchdog, failure matrix |
| 11 | Config & onboarding | Config schema, discovery, first-run flow |
| 12 | Packaging & deployment | systemd, install, read-only root, portability matrix |
| 13 | BOM | Parts and costs per build tier |
| 14 | Roadmap | Milestones and acceptance gates |
| 15 | Sound library | Royalty-free audio sourcing, formats, loop prep |

Audio is file-based playback only — no runtime synthesis. White noise and soundscapes are ordinary files on disk (spec 15).

---

## Architecture

```
                    ┌──────────────────────────────┐
                    │  openrestore daemon (host)   │
   physical         │                              │        LAN
   controls  ──────▶│  input adapters              │
   (GPIO/MQTT)      │        │                     │
                    │        ▼                     │   ┌──────────────┐
                    │   ┌─────────┐   ┌──────────┐ │──▶│ smart bulb   │
                    │   │ routine │──▶│  light   │ │   └──────────────┘
   web PWA  ───────▶│   │ engine  │   │  driver  │ │
   (REST/WS)        │   └─────────┘   └──────────┘ │
                    │        │        ┌──────────┐ │   ┌──────────────┐
                    │        └───────▶│  audio   │ │──▶│ your speaker │
                    │                 │  driver  │ │   └──────────────┘
                    │   ┌─────────┐   └──────────┘ │
                    │   │scheduler│                │
                    │   └─────────┘   ┌──────────┐ │
                    │                 │  store   │ │
                    │                 │ (SQLite) │ │
                    └──────────────────────────────┘
```

Every arrow crossing the daemon boundary is an interface with at least two implementations. That is the portability guarantee.

## Core design rules

1. **Drivers are swappable.** Light, audio output, and physical input are all interfaces. Adding a bulb vendor is one file, no core changes.
2. **Wall clock is truth.** No component ever sleeps until an event. Everything recomputes position from `datetime.now(tz)`, so restarts, clock steps, and suspends are non-events.
3. **State is persisted, not held.** A crash mid-sunrise resumes at minute 17, not minute 0.
4. **Local only.** No account, no cloud dependency at runtime. LAN or nothing.
5. **The alarm is the product.** Any feature that can compromise alarm delivery must have a fallback path (spec 10).
6. **Config over code.** Routines, curves, and device bindings are data files a user can share.

## Language and runtime

Python 3.11+, asyncio, single process. Chosen because the device libraries (`lifxlan`, `pywizlight`, `zigpy`/MQTT, `aiohue`, `pyatv`) and the audio tooling live there. Frontend is React/TypeScript, built to static assets and served by the daemon.

Hard rule: no C extensions that don't ship arm64 wheels, so the whole thing installs on a Zero 2 W without a compiler.
