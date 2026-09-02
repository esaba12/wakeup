# 12 — Packaging & Deployment

## Purpose
Install in one command, survive power cuts, update without breaking, and run identically on hardware the author has never seen.

## Distribution channels

| Channel | Target | Notes |
|---|---|---|
| `install.sh` | Raspberry Pi OS Lite (primary) | apt deps + venv + systemd units + config scaffold |
| Docker image (multi-arch: arm64, armv7, amd64) | Tier 2 hosts, NAS, x86 | `--net=host` required for UDP broadcast discovery |
| pip package | Developers, Tier 4 | `pip install openrestore && openrestore --mock-light --mock-audio` |
| Prebuilt SD image | Later, if there's demand | Highest support burden; defer |

## systemd

```ini
# openrestore.service
[Unit]
Description=OpenRestore sleep clock
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/opt/openrestore/venv/bin/openrestore serve
Restart=always
RestartSec=2
WatchdogSec=30
User=openrestore
SupplementaryGroups=gpio i2c audio
StateDirectory=openrestore
RuntimeDirectory=openrestore
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/openrestore

[Install]
WantedBy=multi-user.target
```

`Type=notify` + `WatchdogSec` means a wedged event loop gets restarted, not just a crashed process. `mpv` runs as a supervised child, not a second unit.

Hardware watchdog on Pi: `dtparam=watchdog=on` in `config.txt` plus `RuntimeWatchdogSec=15` in `/etc/systemd/system.conf`.

## Read-only root

The leading cause of death for always-on Pis is SD corruption from unclean power loss. This is not optional.

- `overlayroot` (or `raspi-config` → Performance → Overlay FS) makes `/` read-only with a RAM overlay
- A separate small ext4 partition mounted at `/var/lib/openrestore`, `commit=30`, holding SQLite (WAL) + routines + curves + sounds
- Logs to journald with `Storage=volatile`, plus a rotating file on the writable partition for the last 7 days only
- Documented "make writable" / "make read-only" helper commands, because people will need to edit things

## Updates
`openrestore update` → git fetch a tagged release, verify, install into a *new* venv directory, symlink swap, restart. Previous venv retained for one generation so rollback is a symlink flip. Never update automatically at night; default the update window to 14:00 local and never while a routine is running.

## Portability matrix (CI must prove this)

| Host | Light | Audio | GPIO input | Status |
|---|---|---|---|---|
| Pi Zero 2 W | real | USB/I²S | yes | Reference; hardware smoke test |
| Pi 4/5 | real | USB/I²S/analog | yes | Supported |
| x86 Docker | real | ALSA/network | no (MQTT puck) | CI-tested |
| macOS dev | mock | mock/CoreAudio | no | CI-tested |
| NAS / VPS on LAN | real | network sink | no | Supported, documented |

## CI
- `pytest` with an injected fake clock; scheduler DST matrix; curve golden files; driver conformance suite against mocks
- `ruff` + `mypy --strict` on core
- Frontend build + typecheck
- Multi-arch Docker build
- Nightly hardware smoke test on a real Pi + real bulb, if you can keep one plugged in — this is what catches firmware changes on the bulb side

## Repo layout

```
openrestore/
├── src/openrestore/
│   ├── core/        scheduler, routines, state, store, curves
│   ├── drivers/     light/, audio/, input/
│   ├── api/         rest, ws, mqtt bridge
│   └── cli.py
├── web/             React PWA
├── hardware/        wiring diagrams, BOM, bulb-compatibility.md, puck ESPHome yaml
├── routines/        shipped + community routine files
├── curves/          sunrise-classic.yaml, reverse-sunrise.yaml, ...
├── deploy/          install.sh, systemd units, Dockerfile, overlayroot notes
└── docs/            these specs
```

## Licensing
- Software: **Apache-2.0** (patent grant; better than MIT for anything hardware-adjacent)
- Hardware files: **CERN-OHL-P** or CC-BY-SA 4.0
- Any bundled audio: per-file license record in `sounds/CREDITS.md`; CC0 only

## Acceptance criteria
- [ ] `install.sh` on a clean Pi OS Lite image → working daemon, no manual steps
- [ ] Docker image runs on amd64 and arm64 and discovers a real bulb with `--net=host`
- [ ] 100 forced power cuts, no corruption, alarm still fires
- [ ] Update + rollback both verified
