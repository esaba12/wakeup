# Task 06 — Audio

**Read:** `docs/04-audio-subsystem.md`, `docs/15-sound-library.md`

**Hardware:** your laptop's speakers

## Build

- `drivers/audio/base.py` — the `AudioSource` and `AudioOutput` Protocols from spec 04. Note `is_available()` must actually attempt to open the device, not just check that it's enumerated.
- `drivers/audio/mpv.py` — `MpvOutput`. Spawns mpv as a supervised child with `--idle --no-video --loop-file=inf --input-ipc-server=...`, controls it over the unix socket with JSON-RPC, and respawns within 5s if it dies.
- `drivers/audio/mock.py` — records play/stop/gain calls with fake-clock timestamps.
- Gain ramping in dB per spec 04, with the defaults table (alarm −45→−12 dB over 90s, wind-down fade-in, sleep-timer fade-out) and the `max_gain_db` ceiling the routine engine cannot exceed.
- Escalation: +6 dB once after `escalate_after`, then the fallback hook (stubbed until task 10).
- Device enumeration: list available ALSA/PulseAudio/CoreAudio sinks, plus `test_tone()`.
- `sounds/` — a `make sounds` target that generates `white.flac`, `pink.flac`, `brown.flac`, `fan.flac` with the ffmpeg `anoisesrc` one-liners in spec 15. Don't commit the audio binaries; commit the recipe. `sounds/manifest.yaml` and a `CREDITS.md` generated from it.

No synthesis at runtime. Files on disk, looped by mpv.

## Done when

- [ ] `make sounds` regenerates all four noise files from scratch on a clean machine
- [ ] Playback works on your laptop; you can hear a 20-second compressed alarm ramp and it feels gradual, not sudden
- [ ] Killing the mpv process mid-playback → respawned and playing again within 5s
- [ ] Unplugging/disabling the output device is detected within 10s and reported without crashing
- [ ] `max_gain_db` is enforced even when a routine asks for more
- [ ] CI fails if any manifest entry lacks a source URL and a CC0-or-generated license
