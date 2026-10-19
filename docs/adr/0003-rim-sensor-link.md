# 0003 — Rim sensor link: ESP-NOW with a USB gateway
status: accepted · date: 2026-10-19 (accepted by the owner)

## Context
FR-009 needs make events from a rim sensor to reach the PC, FR-015 needs the PC to notice an outage, and FR-003 needs a startup check (10 of 10 hand drops). The sensor microcontroller sits at the rim, 3.05 m up; where the PC stands relative to the rim is not fixed. The make-detection hardware itself (break-beam, accelerometer, piezo) is not decided here.

## Options considered
| Option | Pros | Cons | Fit to NFRs |
|---|---|---|---|
| L1. Direct USB serial cable from the rim ESP32 to the PC | Simplest; ordered and checked; the OS notices an unplug (helps FR-015) | Cable from the rim to the PC; about 5 m limit without powered hubs (secondary source); USB-serial bridge latency up to 16 ms on the FTDI default | Good when the PC is near the rim |
| L2. ESP-NOW from the rim ESP32 to a gateway ESP32 on the PC's USB; sequence numbers, repeats and an application-level acknowledgement | No router and no cable at the rim; about 2.4 ms mean in the only measurement (2 nodes, 2 m, preliminary) | A second ESP32; range and loss at court distance unmeasured; only MAC-level ACK in the protocol | Meets 50 ms with ADR 0002 |
| L3. Wi-Fi UDP through the phones' access point | Reuses the router | About 105 ms mean latency, 55–93 ms standard deviation, 1.4–2.8% loss in the only measurement; shares the channel with two video streams | Fails 50 ms unless the sensor stamps events |
| L4. BLE notifications to a PC adapter | Low power, no router | No primary latency data; Windows behaviour unverified | Low confidence |

## Decision
Decided (owner, 2026-10-19): **L2** as the default: the rim ESP32 sends over ESP-NOW to a gateway ESP32 on USB, which hands events to the PC through a new `EventSource` interface. If the PC stands within about 5 m of the rim, choose **L1** instead and drop the gateway. L3 and L4 are rejected for v1. The PC-to-rim distance is not given yet, so L2 is assumed until it is. A field test decides: a 30-minute soak with sequence-number gap counting, and a repeat count chosen from the measured loss.

## Consequences
- New Protocol `EventSource` in `services/edge/`, a new file `events.csv`, and outage events (FR-015): contract and `DECISIONS.md` first, per `CLAUDE.md` rule 2.
- Firmware for the two ESP32 boards lives in a new `firmware/` folder: a new dependency area the owner must approve (`CLAUDE.md` rule 8).
- No primary figure exists for any make-detection hardware's reliability. FR-009's 10 of 10 hand drops gives only about a 74% lower bound on the detection rate and says nothing about false triggers, so the sensor needs a dry run with rim hits, net sway and hands before it is trusted.

## Sources
- [Montiel Torres et al.: ESP-NOW vs Wi-Fi temporal determinism (JAIIO 2026)](https://55jaiio.sadio.org.ar/wp-content/uploads/2026/07/273.pdf) · tier A, conference paper · the only latency measurement found; preliminary
- [Espressif ESP-IDF documentation (ESP-NOW, system time, Wi-Fi power save)](https://docs.espressif.com/) · tier A, manufacturer
- Research note: `.suite/research/sensor-link-and-clock-model.md`
