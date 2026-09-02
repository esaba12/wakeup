# 02 — Light Driver & Bulb Selection

## Purpose
Pick the bulb that works best *natively* — meaning controllable directly from the daemon over LAN, with no hub, no cloud, and no reverse-engineering — and define the driver interface everything else programs against.

---

## Part A — Bulb selection

### Selection criteria, weighted

| Criterion | Weight | Why it matters here |
|---|---|---|
| Open, documented local protocol | ★★★★★ | The daemon talks to the bulb directly. No cloud round-trip at 6:40am. |
| **Bulb-side timed fades** | ★★★★★ | "Go to this state over 30s" means the bulb interpolates. A dropped packet or a daemon restart doesn't freeze the sunrise mid-ramp. |
| Deep dimming floor | ★★★★★ | A sunrise starts below 1%. A bulb with a 10% floor cannot start a sunrise, only continue one. |
| Low minimum CCT | ★★★★☆ | Real dawn starts at candle temperatures. 1500–2000K matters more than max brightness. |
| No hub required | ★★★★☆ | Every hub is $25–60 and another failure domain. |
| Cost | ★★★☆☆ | This is a $60 project; a $50 bulb distorts it. |
| Flicker at low dim | ★★★★☆ | The first 10 minutes of a ramp live below 15%, exactly where cheap PWM shows. |

### Candidates

**LIFX Color A19 / LIFX Everyday (Wi-Fi, no hub)**
- Protocol: the **LIFX LAN Protocol** — publicly documented binary protocol over UDP:56700, broadcast discovery, no auth, no pairing. LIFX deliberately deprecated their own SDK gem in favor of documenting the wire protocol so third parties could build clients, and mature libraries exist in Python (`lifxlan`), Go, Node, and Rust.
- **`Light::SetColor` carries a `duration` field in milliseconds** — the bulb performs the fade itself. This is the single most valuable property for this project.
- Color model is HSBK with 16-bit brightness — 65,536 steps, not 100.
- Color bulbs reach **1500K**, well below the 2200–2700K floor typical of Hue white-ambiance bulbs. That's the deep amber you want at minute zero.
- No hub. ~$12–25/bulb. Bright (1100 lm on the color A19).
- Company status: LIFX assets were acquired by Feit Electric in 2022; the brand is actively shipping, with a 2026 roadmap adding Thread and a new budget "Everyday" line. Not abandonware.
- Caveats: dimming floor reports vary — the Everyday line is specced to 1%, while some testing reports color LIFX bulbs getting unstable or cutting out somewhere in the 5–10% range depending on model and firmware. **Test your specific unit.** Also, initial Wi-Fi onboarding goes through the LIFX app (a one-time cloud touch); after that, runtime is pure LAN.

**Philips Hue White & Color Ambiance (Zigbee)**
- Best low-end dimming in the category by a wide margin: regular Hue bulbs dim to roughly **0.2%** of maximum. (Note the cheaper Hue *Essential* line only reaches 2% — for this project, buy the regular one, not Essential.)
- Bulb-side fades via `transitiontime`. Excellent flicker behavior. High CRI.
- Requires either a Hue Bridge (~$60, local REST/SSE API) or a $25 Zigbee USB coordinator + zigbee2mqtt.
- ~$50/bulb. Total entry cost is 3–4× the LIFX path.

**WiZ (Philips-owned, Wi-Fi)**
- Protocol is trivial: JSON datagrams on UDP:38899, `setPilot`/`getPilot`. `pywizlight` is mature.
- **Hard `dimming` floor of 10** and **no native fade duration** — you push every step yourself. Both are disqualifying for a sunrise-first product.
- ~$10. Best cheap fallback, worst sunrise.

**Zigbee generics (IKEA, Sengled, Cree) via zigbee2mqtt**
- Good dimming and bulb-side `transition`, cheapest bulbs, but you're adding an MQTT broker + coordinator dongle before the first line of light code runs.

**Tasmota-flashed / WLED**
- Total control, best possible curve fidelity, but requires flashing or building a fixture. Reserve for a later "dedicated hardware" branch.

### Decision

> **Primary: LIFX Color A19** (or LIFX Everyday if budget-constrained and you verify its dim floor).
>
> It is the only widely available bulb that combines an openly documented local protocol, **bulb-side timed fades**, 16-bit brightness resolution, a 1500K minimum color temperature, and no hub — which is exactly the four-way intersection this project needs. Buy one, run the dim-floor acceptance test below before writing anything else.
>
> **Best-light alternative: Philips Hue White & Color Ambiance** + a $25 Zigbee coordinator running zigbee2mqtt, if 0.2% dimming and zero flicker matter more to you than $60 and a second daemon.
>
> **Budget fallback: WiZ**, with the 10%-floor workaround in Part C.

### Mandatory acceptance test before committing to a bulb
1. Set it to its lowest non-zero brightness at its lowest CCT in a dark room. Is it a candle, or is it a reading lamp? If you can read by it, it can't start a sunrise.
2. Point a phone camera at it at 5%, 10%, 20%. Rolling-shutter banding = visible PWM = wrong bulb.
3. Send 200 state changes over 10 minutes. Count drops and check for audible/visible stutter.
4. Cut its power, restore it. Does it come back at last state, or at 100% white at 3am?

Record results in `hardware/bulb-compatibility.md` in the repo. That table is one of the most valuable artifacts the project can publish.

---

## Part B — The `Light` interface

Everything above the driver programs against this. No vendor concepts leak upward.

```python
@dataclass(frozen=True)
class LightState:
    on: bool
    brightness: float          # 0.0–1.0, PERCEPTUAL (see spec 03), not raw device units
    cct: int | None            # kelvin, None if in rgb mode
    rgb: tuple[int,int,int] | None

@dataclass(frozen=True)
class LightCapabilities:
    min_brightness: float      # lowest reliably-renderable perceptual brightness, 0.0–1.0
    cct_range: tuple[int,int]  # e.g. (1500, 9000)
    supports_rgb: bool
    supports_native_transition: bool
    max_transition_ms: int
    recommended_step_interval_ms: int

class Light(Protocol):
    id: str
    capabilities: LightCapabilities

    async def apply(self, state: LightState, transition_ms: int = 0) -> None: ...
    async def get(self) -> LightState: ...
    async def is_reachable(self) -> bool: ...
    async def close(self) -> None: ...

class LightDiscovery(Protocol):
    @staticmethod
    async def discover(timeout_s: float = 5.0) -> list[LightRef]: ...
```

Rules:
- `apply()` is **idempotent and absolute**, never relative. No `brighten_by()`.
- `apply()` must not raise on a transient network failure; it retries internally and raises only after exhausting its budget. Callers treat a raise as "the light is gone," which triggers the escalation path in spec 10.
- `capabilities.min_brightness` is what the sunrise engine clamps to. It is the driver's job to know its own floor, and to lie downward if it can fake a lower one (see WiZ, below).
- Drivers own retries, sockets, and rate limits. The engine owns curves and timing.

### Required implementations
| Driver | Transport | Native transition | Notes |
|---|---|---|---|
| `LifxLight` | UDP:56700 binary | Yes (`duration` ms) | Reference implementation |
| `HueLight` | Bridge REST v2 + SSE | Yes (`transitiontime`, ds) | Also gives you event push |
| `Zigbee2MqttLight` | MQTT JSON | Yes (`transition`, s) | |
| `WizLight` | UDP:38899 JSON | No — emulated | |
| `WledLight` | HTTP/JSON | Yes | For strip-based fixtures |
| `MockLight` | in-memory | Yes | CI, records a full state timeline for curve assertions |

---

## Part C — Driver implementation notes

### LIFX
- Discovery: broadcast `GetService` to 255.255.255.255:56700, collect `StateService` replies; cache MAC→IP with periodic re-discovery every 5 min (DHCP moves things).
- Set: `Light::SetColor` with HSBK + `duration_ms`. For white, use `saturation=0` and set `kelvin`. Brightness is uint16 — map perceptual 0.0–1.0 through the curve in spec 03 to `0..65535`.
- Use acknowledgement/response flags on important transitions (start, end of ramp) and fire-and-forget for intermediate steps.
- Send a step every 10–30s with `duration` equal to the interval. The bulb interpolates; a lost packet self-heals on the next one.
- Watch for the `Light::SetWaveform` message — it can do a bulb-side ramp with a shaped envelope, worth exploring as an optimization.

### Hue
- Prefer the Bridge's **v2 API with SSE** so you get state changes pushed rather than polled. `transitiontime` is in *deciseconds*; cap ~65535.
- Bridge requires a one-time link-button pairing to obtain an application key. Store it in config, never in the repo.

### WiZ (the emulation case)
- `dimming` is clamped to 10–100 by firmware. Report `min_brightness` as the *perceptual* equivalent you can actually achieve, which is lower than 10% because of the RGB trick below.
- Below the effective floor, switch to RGB mode with a deep amber at low channel values (e.g. `r:10,g:2,b:0`), which renders visibly dimmer than 10% white. Cross-fade into `temp` mode once the ramp exceeds the floor. This crossover must be smooth — pick the crossover point by eye, once, and hard-code it per model.
- No native transition: the driver emulates one by interpolating internally on a 2s tick, so the engine's contract is unchanged.
- Retransmit each datagram until a reply arrives (bounded), since UDP drops silently.

## Acceptance criteria
- [ ] Two real drivers + mock pass an identical conformance test suite
- [ ] A 30-minute ramp on the reference bulb sends <200 packets and shows no visible stepping
- [ ] Killing the daemon at t=12min and restarting resumes the ramp within 5s at the correct brightness
- [ ] Unplugging the bulb mid-ramp surfaces `is_reachable() == False` within 30s and does not crash the routine
