# 0002 — One PC clock domain, with measured per-camera latency
status: accepted · date: 2026-10-19 (accepted by the owner)

## Context
FR-005 needs every phone frame and every sensor event on one timeline (sensor to phone at most 50 ms, phone to phone at most 33 ms). The facts: every camera process runs on the **same PC**; `Frame.t_recv` is `time.perf_counter()` taken on that PC when the frame is read; phones give no timestamps (DroidCam, IP Webcam). So the unknowns are (a) each camera's latency between the phone capturing a frame and the PC reading it, and (b) the sensor's clock if it stamps events itself. The "clock between phones" problem of the first research note does not exist here.

## Options considered
| Option | Pros | Cons | Fit to NFRs |
|---|---|---|---|
| C1. Stamp everything on arrival at the PC, no sensor timestamp | No sync code | Bias equals link delay: acceptable only on a tuned USB link; unusable on Wi-Fi or BLE; camera latency ignored | Meets 50 ms only with USB |
| C2. Sensor stamps events with its own timer; offset to the PC clock estimated by ping-pong with a minimum-RTT filter and a drift fit every 10–30 s; per-camera latency measured with an LED test at session start and re-checked at the end | Works on every link; removes link jitter; the camera latency is measured, not assumed; the end check catches drift | A small protocol and a fit; needs an LED in view of both cameras | Sensor to phone about 10 ms at 1 sigma; phone to phone about 14.5 ms at 1 sigma, if stream jitter is 10 ms (unmeasured) |
| C3. C2 plus LED blinks during the session | Tracks drift live | More code and a visible LED; no evidence it is needed | Against "simplest thing" |
| C4. Hardware-grade sync (PTP, beacon schemes) | Microsecond accuracy on the microcontroller | Custom firmware; cannot be applied to the phones; the phone latency term is unchanged | Not needed |

## Decision
Decided (owner, 2026-10-19): **C2**. One `perf_counter` domain on the PC (documented as consistent across processes on Windows with Python 3.10 or later). The sensor offset is re-estimated every 10–30 s. Per-camera latency L_k is measured by the LED test (spec AC-005.2) and re-checked at session end; the run records median, 95th percentile and standard deviation of L_k per camera. Use C1 only if the sensor goes over a tuned USB cable and the bench shows the sensor timestamp is unnecessary.

## Consequences
- Spec changes (accepted by the owner as CR-2): FR-005 swaps the drift limit of 1.2 ms per minute (a phone figure) for "offset re-estimated every 10–30 s", and AC-005.2 adds the per-camera standard deviation.
- `run.json` gets a `clock` block (sensor offset estimates, L_k per camera, start and end values): contract change, bump from 0.10.0.
- **Risk:** per-frame stream jitter is the dominant term and has no primary figure for DroidCam or IP Webcam. If it exceeds about 10 ms per camera, the 33 ms phone-to-phone limit may fail; the fallbacks are USB capture, B4 of ADR 0001, or the custom phone app (Phase 13).

## Sources
- [Ansari et al.: sub-millisecond phone clock sync over Wi-Fi](https://arxiv.org/abs/1812.09366) · tier A, preprint
- [Smid and Matas: camera-to-camera sync by flash detection](https://arxiv.org/abs/1902.11084) · tier A, VISAPP 2017
- [Akhmetyanov et al.: phone clock drift across 47 Android models](https://arxiv.org/abs/2107.00987) · tier A, IEEE Sensors 2021
- [Bachhuber and Steinbach: LED-based glass-to-glass latency measurement](https://arxiv.org/abs/1510.01134) · tier A, ICIP 2016
- [Gundall et al.: ESP32 beacon-based sync, rejected as unnecessary](https://arxiv.org/abs/2511.14457) · tier A, preprint
- Research note: `.suite/research/sensor-link-and-clock-model.md`
