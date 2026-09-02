# 15 — Sound Library (royalty-free audio, no synthesis)

## Purpose
Ship a small set of sleep sounds — white/pink/brown noise, rain, fan — as ordinary audio files, sourced and licensed cleanly enough to live in a public repo.

No runtime synthesis. Files on disk, looped by the player (spec 04).

---

## Where the audio comes from

### 1. Generate the noise files once, with ffmpeg. **Recommended for the noise tracks.**
This is not runtime synthesis — it's a build step that produces an asset, the same way you'd bake a texture. It sidesteps licensing entirely, because nobody owns a noise file you generated.

```bash
# 10 minutes of white noise, 48kHz stereo, lossless
ffmpeg -f lavfi -i "anoisesrc=d=600:c=white:r=48000:a=0.5" -ac 2 -c:a flac white.flac

# pink and brown
ffmpeg -f lavfi -i "anoisesrc=d=600:c=pink:r=48000:a=0.5"  -ac 2 -c:a flac pink.flac
ffmpeg -f lavfi -i "anoisesrc=d=600:c=brown:r=48000:a=0.5" -ac 2 -c:a flac brown.flac

# "fan"/HVAC flavor: brown noise with a resonant low peak
ffmpeg -f lavfi -i "anoisesrc=d=600:c=brown:r=48000:a=0.6" \
  -af "equalizer=f=110:t=q:w=1.2:g=8,lowpass=f=6000" -ac 2 -c:a flac fan.flac
```

Noise loops seamlessly with no edit work — there's no transient to line up — so a 10-minute file on `--loop-file=inf` is indistinguishable from infinite noise.

**License:** none needed. Ship them, or ship the ffmpeg one-liners in a `make sounds` target and let the file be built at install time (keeps the repo small and makes the provenance self-evident).

### 2. Freesound, filtered to **CC0**. For anything you can't generate: rain, fire, birdsong, chimes.
Freesound uses CC0, CC-BY, and CC-BY-NC per upload. **Take CC0 only** — CC-BY means every downstream user of your repo inherits an attribution obligation, and CC-BY-NC is incompatible with an open-source project. Filter by license in the search sidebar, or query the REST API with `filter=license:"Creative Commons 0"`.

Caveat worth respecting: Freesound's own guidance is that CC0 uploads occasionally have bad provenance (someone re-uploading library or game audio). Favor contributors who describe how they recorded the sound, and skip anything that sounds like it came from a commercial library.

### 3. Wikimedia Commons — everything is CC-licensed or public domain, with the license stated per file, and provenance is better policed than most sources.

### 4. Internet Archive, filtered by license. Search with `licenseurl:*publicdomain*` to isolate CC0/PD items. Quality is uneven; check each item's rights field.

### Sources to be careful with
- **Pixabay** — often described as CC0, but since 2019 it uses its own **Pixabay Content License**, which permits commercial use without attribution *but restricts redistributing the files as-is on another platform*. Fine for your own device; legally murky to bundle into a public repo. Don't ship it.
- **Zapsplat, Mixkit, freesoundslibrary, wnoise.org** — "free" usually means free-for-personal-use or attribution-required, sometimes with explicit no-redistribution terms. Several white-noise download sites are personal-use only. Read the actual terms; none of these belong in a repo.
- **YouTube rips** — no.

---

## What ships

| File | Source | License |
|---|---|---|
| `white.flac` | ffmpeg `anoisesrc` | generated, unencumbered |
| `pink.flac` | ffmpeg `anoisesrc` | generated |
| `brown.flac` | ffmpeg `anoisesrc` | generated |
| `fan.flac` | ffmpeg, filtered brown | generated |
| `rain.flac` | Freesound CC0 | CC0 |
| `chime.flac` (alarm) | Freesound CC0 | CC0 |

Six files, ~50 MB at FLAC. Everything beyond that is user-supplied — drop files in `sounds/` and they appear in the picker.

---

## File format and preparation

**Use FLAC (or WAV). Avoid lossy codecs for noise.** Lossy encoders are built on psychoacoustic models that assume structured audio; broadband noise is the pathological worst case for them, and low-bitrate MP3/AAC on noise produces audible swirling and "pumping" as the encoder's bit allocation shifts. Noise also compresses poorly in the first place, so you don't save much. FLAC at 48 kHz costs ~35 MB per 10 minutes and has zero artifacts.

If you must save space, Opus at ≥128 kbps is the least-bad lossy option, but test it on the actual file before committing.

**Length:** 5–10 minutes minimum. Short loops of *textured* sound (rain, fire) develop audible periodicity — your brain finds the repeat within a few cycles and it becomes maddening at 3am. Pure noise is exempt from this.

**Loop points:** for recorded material, trim to zero crossings and apply a short (20–50 ms) equal-power crossfade between the tail and head so the seam is inaudible.

```bash
# normalize to a consistent loudness so switching sounds doesn't change perceived volume
ffmpeg -i in.wav -af loudnorm=I=-23:TP=-2:LRA=7 -c:a flac out.flac
```

Normalize everything to the same integrated loudness (−23 LUFS is a reasonable target). Otherwise the volume ramp in spec 04 means something different for every track.

**Sample rate:** 48 kHz, matching the output device, so ALSA doesn't resample. **Stereo**, even for noise — mono noise in both ears is subtly fatiguing; decorrelated L/R sounds more spacious. Generate the two channels separately if using `anoisesrc`.

---

## Manifest

Each sound is described in `sounds/manifest.yaml`, which drives the UI picker and the credits file:

```yaml
- id: white
  title: "White noise"
  file: white.flac
  category: noise
  source: "generated (ffmpeg anoisesrc)"
  license: none
- id: rain
  title: "Rain"
  file: rain.flac
  category: nature
  source: "https://freesound.org/s/XXXXXX/"
  author: "..."
  license: CC0
```

`sounds/CREDITS.md` is generated from the manifest at build time. Every file must have a source URL and a license, or CI fails. This is cheap insurance and it's the thing that makes the repo safe for other people to fork.

---

## Acceptance criteria
- [ ] `make sounds` regenerates the noise files from scratch on a clean machine
- [ ] Every non-generated file has a source URL and a CC0 (or public domain) license in the manifest; CI enforces it
- [ ] Two hours of continuous looping with no audible seam, click, or gap
- [ ] Switching between any two sounds produces no perceived loudness jump
- [ ] User-supplied files dropped in `sounds/` are picked up without a restart
