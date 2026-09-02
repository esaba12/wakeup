# 13 — Bill of Materials

Assumes you already own the lamp and the speaker.

## Tier 1 — Minimum viable (~$65)
Everything needed for a working sunrise alarm with a web UI. No physical controls.

| Item | Spec | ~Cost |
|---|---|---|
| Raspberry Pi Zero 2 W (with headers) | quad A53, 512MB | $18 |
| microSD 32GB | A2, high-endurance | $9 |
| Power supply | 5V ≥2.0A + micro-USB | $10 |
| USB audio adapter | CM108/CM6533 class | $8 |
| USB OTG adapter / hub | micro-USB → USB-A | $4 |
| **LIFX Color A19** | Wi-Fi, LAN protocol, 1500K min | $20 |
| 3.5mm cable | to your powered speaker | $4 |

## Tier 2 — Trustworthy (+$12)
Add these before you rely on it to wake you up. Cheapest reliability you will ever buy.

| Item | Why | ~Cost |
|---|---|---|
| DS3231 RTC + CR2032 | Alarm survives a boot with no internet (spec 05) | $5 |
| Piezo buzzer | Fallback when audio is gone (spec 10) | $1 |
| Jumper wires, headers | | $6 |

## Tier 3 — Phone-free device (+$35)
The physical controls. This is what makes it a Hatch rather than a web page (spec 09).

| Item | Notes | ~Cost |
|---|---|---|
| EC11 rotary encoder + knob | Volume / brightness | $3 |
| 16–22mm illuminated momentary button | The one big button | $5 |
| SSD1306 0.96" OLED | or GC9A01 round LCD $10, or 2.13" e-paper $18 | $4 |
| BH1750 lux sensor | Auto-dims the display | $3 |
| ADXL345 accelerometer | Tap-to-show-time, optional | $4 |
| Perfboard, standoffs, wire | | $8 |
| Enclosure | 3D printed or laser-cut; doesn't have to look nice | $0–15 |

## Tier 4 — Networked puck variant (+$5, replaces Tier 3 GPIO wiring)
Brain lives with the speaker; only the puck is on the nightstand.

| Item | ~Cost |
|---|---|
| ESP32-C3 SuperMini (ESPHome) | $5 |
| (reuse encoder / button / display from Tier 3) | — |

## Light alternatives

| Bulb | Cost | Trade |
|---|---|---|
| **LIFX Color A19** | $20 | **Recommended.** Open LAN protocol, bulb-side timed fades, 1500K min, no hub |
| LIFX Everyday (2-pack) | $25/pair | Cheaper; verify its dim floor before committing |
| Philips Hue White & Color Ambiance | $50 + $25 Zigbee dongle | Best low-end dimming (~0.2%) and least flicker; +$60 if you use a Hue Bridge instead |
| WiZ A19 | $12 | Cheapest; 10% dim floor and no native fades — needs the workaround in spec 02 |
| Hue **Essential** | $22 | Avoid for this project — 2% floor, not 0.2% |

## Audio alternatives

| Option | Cost | Trade |
|---|---|---|
| **USB audio dongle → 3.5mm** | $8 | Most reliable. Default. |
| MAX98357A I²S DAC+amp | $6 | For driving a bare speaker driver in an enclosure |
| Line-level I²S DAC HAT | $15–25 | Best quality into a powered speaker; frees the USB port |
| Network sink (AirPlay/Cast) | $0 | No hardware, but adds a network dependency to alarm delivery |
| USB Bluetooth dongle | $10 | Only if you must go wireless; never use the Pi's internal BT for audio |

## Totals
- **Minimum:** ~$65
- **Trustworthy:** ~$77
- **Full device:** ~$112
- Compare: Hatch Restore 3 at $169.99 + $59.99/year for the content library.
