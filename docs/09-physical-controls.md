# 09 — Physical Controls

## Purpose
Make the device usable without a phone. This is the entire reason the product exists — a Hatch is a sound machine plus the fact that you never pick up your phone in bed. Skip this and you've built a web page that dims a lamp.

## Interaction model

One knob, one button. Everything else is a modifier.

| Input | Action |
|---|---|
| Big button, short press | Start default routine / dismiss alarm / stop what's running |
| Big button, long press (>800ms) | Snooze |
| Knob rotate | Volume during audio, brightness otherwise |
| Knob press | Cycle: nightlight → reading → off |
| Knob press + rotate | Cycle routines |
| Tap the enclosure (accelerometer) | Show the time for 5s |

Rules: every action must be discoverable by feel in the dark. No double-taps, no chords beyond press+rotate, no menus deeper than one level. If you need to look at the display to do the thing, the design failed.

## Two implementations

### A. Direct GPIO (Tier 1 hosts)
The daemon reads hardware directly.

| Part | Interface | Pins (Pi) | Notes |
|---|---|---|---|
| EC11 rotary encoder w/ push | GPIO ×3 | e.g. 17, 27, 22 | Internal pull-ups, edge callbacks, **never a polling loop** |
| 16–22mm illuminated momentary | GPIO ×2 | 23 (in), 24 (LED PWM) | LED is the "find me in the dark" affordance |
| SSD1306 0.96" OLED | I²C | 2/3 | $4, monochrome |
| DS3231 RTC | I²C | 2/3 | Spec 05 depends on it |
| BH1750 lux sensor | I²C | 2/3 | Auto-dims the display |
| Piezo buzzer | GPIO PWM | 18 | The fallback alarm (spec 10) |
| ADXL345 accelerometer (opt) | I²C | 2/3 | Tap-to-show-time |

Implementation notes: use `gpiozero` (`RotaryEncoder`, `Button`) over `lgpio`; debounce ~20ms in software; encoder events are coalesced (a fast spin should produce one volume change, not forty API calls). GPIO libraries are imported **lazily inside the adapter** so the daemon still starts on x86.

### B. Networked puck (Tier 2 hosts, and the better long-term design)
An ESP32-C3 running ESPHome holds the encoder, button, display, and sensors, and publishes to MQTT / WebSocket. The daemon subscribes.

Advantages: the brain can live in a closet with the speaker while only the puck sits on the nightstand; UI changes can't destabilize the alarm daemon; the puck is a cheap, independently buildable thing other people can replicate; and ESPHome gives you encoder, display, and touch components declaratively in YAML.

Prior art worth reading: `javiser/crescendo-clock` — ESP32-C3 alarm clock with rotary encoder, PCB, printed case, publishing `wake_up` / `alarm_off` over MQTT.

Both implementations satisfy the same interface:

```python
class InputAdapter(Protocol):
    def subscribe(self, handler: Callable[[InputEvent], Awaitable[None]]) -> None: ...
    async def set_indicator(self, brightness: float, color: str | None = None) -> None: ...

InputEvent = Literal["press","long_press","rotate_cw","rotate_ccw","knob_press","tap"]
```

## Display

**Requirement: the display must not be a light source at night.** A white OLED at full brightness on a nightstand defeats the entire product.

Rules:
- Brightness driven by the BH1750 lux reading, continuously
- Below a lux threshold: display fully off until a tap or button press, then on for 5s
- Amber/red rendering where the panel allows; never white on black at night
- Never animate; no transitions, no scrolling, no progress spinners
- Show: time (large), next alarm (small), current routine state. Nothing else.

Panel options: SSD1306 OLED ($4, simplest, true black), GC9A01 1.28" round LCD ($10, prettier, has a backlight that leaks), 2.13" e-paper (best at night — zero emission when static, holds the time at zero power — at the cost of slow, ugly refresh). E-paper is arguably the correct engineering answer here.

## Acceptance criteria
- [ ] Every action performable blind, verified by actually doing it in a dark room
- [ ] Encoder produces smooth volume changes with no missed detents at fast rotation
- [ ] Display is invisible in a dark room until touched
- [ ] GPIO adapter absent ⇒ daemon starts normally on a non-GPIO host
- [ ] Puck disconnect ⇒ daemon continues; UI shows the puck as offline
