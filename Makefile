# See docs/15-sound-library.md and tasks/06-audio.md. `make sounds`
# regenerates the shipped noise tracks with ffmpeg from scratch -- the
# generated .flac files are never committed (see .gitignore); only this
# recipe and sounds/manifest.yaml are.

SOUNDS_DIR := sounds
NOISE_DURATION_S := 600
SAMPLE_RATE := 48000
PYTHON := python3

NOISE_FILES := \
	$(SOUNDS_DIR)/white.flac \
	$(SOUNDS_DIR)/pink.flac \
	$(SOUNDS_DIR)/brown.flac \
	$(SOUNDS_DIR)/fan.flac

.PHONY: sounds sounds-clean credits

## Regenerate every noise track and the credits file.
sounds: $(NOISE_FILES) credits

$(SOUNDS_DIR)/white.flac:
	ffmpeg -y -f lavfi -i "anoisesrc=d=$(NOISE_DURATION_S):c=white:r=$(SAMPLE_RATE):a=0.5" \
		-ac 2 -c:a flac $@

$(SOUNDS_DIR)/pink.flac:
	ffmpeg -y -f lavfi -i "anoisesrc=d=$(NOISE_DURATION_S):c=pink:r=$(SAMPLE_RATE):a=0.5" \
		-ac 2 -c:a flac $@

$(SOUNDS_DIR)/brown.flac:
	ffmpeg -y -f lavfi -i "anoisesrc=d=$(NOISE_DURATION_S):c=brown:r=$(SAMPLE_RATE):a=0.5" \
		-ac 2 -c:a flac $@

## "Fan"/HVAC flavor: brown noise with a resonant low peak.
$(SOUNDS_DIR)/fan.flac:
	ffmpeg -y -f lavfi -i "anoisesrc=d=$(NOISE_DURATION_S):c=brown:r=$(SAMPLE_RATE):a=0.6" \
		-af "equalizer=f=110:t=q:w=1.2:g=8,lowpass=f=6000" -ac 2 -c:a flac $@

## Regenerate sounds/CREDITS.md from sounds/manifest.yaml.
credits: $(SOUNDS_DIR)/manifest.yaml
	$(PYTHON) tools/generate_credits.py

sounds-clean:
	rm -f $(NOISE_FILES)
