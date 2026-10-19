# Sensor link and clock model for Pointr Vision

Date of research: 2026-10-19. Protocol: `research-sources` (tiers A/B/C, evidence type, cross-check, date check, verification pass). Time-box: about 30 searches or fetches (used about 33, including 8 that returned nothing usable).
Source policy: **primary and academic only** (papers, standards, manufacturer datasheets, official documentation). Patents, forum posts, vendor blogs and student projects were **not** used as evidence. Where they were the only thing found they are listed as "excluded" so the gap is visible.
Companion note (not repeated): `.suite/research/timing-and-make-window.md`. Facts that note verified (Ansari 2019, Akhmetyanov 2021, Smid and Matas 2017, RFC 5905, AOSP Camera2 timestamps, Gundall 2025) are cited here as `[V-bib]` because they were **not re-opened this session**; their verification status in that note is `[V]`.

Verification legend:
- `[V]` the source text was opened and read this session (HTML fetched, or PDF decoded and searched).
- `[V-bib]` only a bibliographic record, abstract, search snippet, or a verification done in the earlier note. The source itself was not opened this session.
- `[UNVERIFIED]` recalled or inferred; not checked.
- `DERIVED` = my arithmetic on stated inputs. A calculation, not a measurement and not a published number.

Decisions framed (two ADR questions):
1. *Which link should carry the rim "make" event from the microcontroller to the PC?*
2. *Is "one PC clock domain plus a per-camera latency offset" a sound clock model, and how should the sensor event be stamped?*

Recommendation: (1) **ESP-NOW from the rim ESP32 to a second ESP32 on a USB cable at the PC, with USB serial as the last hop**, each event carrying a sequence number and a sensor-side timestamp, repeated and acknowledged at the application level; keep a **USB serial cable direct to the PC** as the fallback and as the first thing to try if the rim is within cable reach. (2) **Sensor-side timestamps mapped to the PC `perf_counter` clock by ping-pong offset estimation with a minimum-RTT filter and a linear drift fit, plus a per-camera latency offset measured by the LED test each session and re-checked at session end.** The single-PC-clock structure is sound; the "constant per-camera latency" assumption is the weak part and is unmeasured for DroidCam and IP Webcam. Confidence: **medium** for the link and the structure, **low** for the absolute milliseconds.

---

## 1. Sensor link options (Q1)

### 1.1 Evidence

| Option / claim | Evidence (citation, type, tier) | Strength | Mechanism and conditions | Status |
|---|---|---|---|---|
| **ESP-NOW one-way latency about 2.4 ms, jitter (std) 1.1 to 1.5 ms, 0% loss** at 10, 50 and 100 Hz | Montiel Torres, Balich, Balich, "ESP-NOW vs. WiFi: an analysis of temporal determinism in high-frequency industrial telemetry", JAIIO 2026 (Universidad Abierta Interamericana, Buenos Aires), conference paper, tier B (peer venue unclear, authors call results "preliminary") | Weak to moderate: 2 ESP32-WROOM-32D nodes, 2 m line of sight, 500 samples per rate, 32-byte packets, latency = RTT/2 so it assumes symmetric paths | Connectionless peer-to-peer, no AP, no TCP/IP stack | [V] (PDF decoded and read) |
| **Wi-Fi UDP through an AP on the same ESP32 pair: mean 105 to 113 ms, std 55 to 93 ms, loss 1.4 to 2.8%** | same paper, Table 1 | Weak to moderate (same limits). Power-save mode and AP are not stated in the paper, so the cause is not isolated | AP hop, CSMA/CA, TCP/IP stack; ESP-IDF default is modem sleep (see next row) | [V] |
| **Wi-Fi modem sleep adds receive delay up to one DTIM cycle (minimum mode, the default) or one listen interval (maximum mode)**; `WIFI_PS_NONE` "minimizes receive delay" | Espressif, ESP-IDF "Wi-Fi Performance and Power Save", docs.espressif.com (current docs), vendor documentation, tier A | Strong for the mechanism; **no latency figure given** | Station sleeps between beacons; broadcast data may be lost in maximum mode | [V] |
| ESP-NOW max payload 250 bytes (v1.0) or 1470 bytes (v2.0); send callback only confirms MAC-layer receipt; "not guaranteed that application layer can receive the data"; Espressif tells applications to add application-level ACK, retransmission and sequence numbers; peers must be on the same channel; default rate 1 Mbps; **no latency, throughput or range figures given** | Espressif, ESP-IDF "ESP-NOW" API reference, tier A | Strong | Link-layer vendor-specific action frames | [V] |
| ESP-NOW reliability depends on walls and open space; in an 8-node building test (4 packets per second, 30 s windows) the author concludes "about 50% of nodes are reliable"; per-node numbers only in figures; no latency reported | Kubascik, Espressif Developer Portal blog, 2024-12-19 (Univ. of Zilina), practitioner report, tier B (vendor-hosted) | Weak: one building, figures not readable as text | Wall attenuation and node placement | [V] (text); figures not read |
| ESP-NOW range "up to 200 m" | quoted inside the Kubascik post as a general statement, not measured | None | - | [UNVERIFIED] |
| ESP-NOW PDR above 92 to 98% and latency below 20 to 40 ms in an indoor swarm test with 3 to 7 robots; indoor range about 8 to 10 m from RSSI | IIETA journal paper on swarm-robot ESP-NOW mesh (seen only in a search result) | Weak (mesh with multi-hop, different setup) | - | [V-bib] |
| ESP-NOW PDR and latency across many placements; "maximum loss 8.6%" | Eridani, Rochim, Cesara, iSemantic 2021 (Diponegoro Univ.), pp. 322 to 328, DOI 10.1109/iSemantic52711.2021.9573246, conference paper, tier B | Moderate as a study, but numbers not read | Compares ESP-NOW, Wi-Fi, Bluetooth on range, speed, latency, energy, barriers | [V-bib] (PDF link returned 404; snippet only) |
| **USB serial bridge chips buffer bytes until the buffer fills or a latency timer expires; FTDI default 16 ms, configurable 0 to 255 ms (1 to 2 ms practical)**; one character can wait about 16 ms | FTDI, AN232B-04 "Data Throughput, Latency and Handshaking", v1.2 2024-03-18, manufacturer application note, tier A | Strong for FT232R/FT-X class; says nothing about CP210x or CH340 | Bridge sends a USB packet only on full buffer or timer expiry | [V-bib] (search excerpt of the note; PDF not opened) |
| CP2102N: USB 2.0 full-speed, up to 3 Mbaud, 512-byte RX and TX buffers | Silicon Labs CP2102N datasheet (silabs.com), manufacturer datasheet, tier A | Strong for the specs; **no latency figure** | - | [V-bib] (search excerpt) |
| ESP32 USB Serial/JTAG controller latency | not found | none | - | [UNVERIFIED] |
| USB 2.0 cable length 5 m for full/high speed; up to 5 hubs in series with 5 m cables gives about 30 m ("active repeater" behaviour); 3 m for low speed | secondary web pages only (cable vendors, a mailing-list post); the USB 2.0 specification was **not** opened | Weak | Round-trip turnaround-delay budget of the bus | [UNVERIFIED] (secondary only; verify in the USB 2.0 spec section 7.1.19) |
| BLE connection interval is set by the central between 7.5 ms and 4 s; a packet waits between 0 and one connection interval for the next connection event | Bluetooth Core Specification Vol 6 (not opened); numbers seen in a patent and a Nordic engineer's forum answer | Weak (no primary text) | Connection events are scheduled; the peripheral may skip events with slave latency | [V-bib] / [UNVERIFIED] |
| BLE measured one-way latency 5 to 65 ms at 7.5 ms interval | one Nordic forum thread (practitioner, tier C) | Excluded as evidence | - | [UNVERIFIED] |
| Windows `perf_counter` and PC-side reading of a USB serial port: OS and driver read latency | not found in a primary source | none | - | [UNVERIFIED] |

### 1.2 Option summary

| Option | Typical latency / jitter (evidence) | Range and cable limit | Delivery reliability | Needs on the court | Mechanism of the main risk |
|---|---|---|---|---|---|
| A. USB serial, ESP32 directly on a PC cable | Bridge latency timer up to 16 ms on FTDI-class chips (V-bib, tier A); 1 to 2 ms if tuned; native-USB chips and CP210x/CH340 not documented [UNVERIFIED]. Bytes are ordered and checksummed by USB | 5 m per cable, longer only with powered hubs in series (secondary, UNVERIFIED) | Highest: wired, retransmitted by USB at the transfer level; unplugging is visible to the OS (supports FR-015) | A cable from the rim to the PC | Cable length from the rim (3.05 m high) to the PC; trip hazard; bridge buffering |
| B. ESP-NOW rim ESP32 to a gateway ESP32 on USB | about 2.4 ms mean, 1.1 to 1.5 ms std at 2 m line of sight (Montiel Torres 2026, weak); plus the USB hop of option A | Not measured with primary evidence at court distances; walls reduce reliability (Kubascik 2024) | MAC-level ack only; the application must add sequence numbers, repeat and ACK (Espressif, tier A) | A second ESP32 and a short USB cable at the PC; no router | Packet loss at distance or with interference; channel must match the gateway's Wi-Fi channel if the gateway also uses Wi-Fi |
| C. Wi-Fi UDP or TCP via the same AP as the phones | 105 to 113 ms mean, 55 to 93 ms std, 1.4 to 2.8% loss in the only measurement found (weak, power-save state unknown); modem sleep can add up to a DTIM cycle (Espressif, tier A) | AP range; shares the channel with two phone video streams | UDP loses packets; TCP retransmits but adds head-of-line delay | The router already needed for the phones | Latency and jitter large and variable; competes with video traffic. Acceptable only if the event carries a sensor timestamp and the offset is estimated (section 2) |
| D. BLE notification to a PC BLE adapter | 7.5 ms minimum connection interval (V-bib); real latency not available from a primary source; Windows negotiation of the interval not verified [UNVERIFIED] | about 10 m class; no primary figure | link-layer retransmit, ordered | A BLE adapter on the PC | Unmeasured; interval chosen by the PC OS, not by the ESP32 |

Dissent and caveats for section 1:
- The only latency measurements for ESP-NOW and Wi-Fi UDP on an ESP32 pair come from one 2026 conference paper that calls itself preliminary and uses RTT/2. Treat 2.4 ms and 105 ms as orders of magnitude, not parameters.
- The 105 ms Wi-Fi figure is probably dominated by default modem sleep, but the paper does not say so; this is my inference from the Espressif mechanism, not a finding.
- No primary evidence was found for reliability of any link at basketball-court distances (rim to PC across an indoor court, roughly 10 to 30 m). It must be measured on the rig (the AC-009.1 and AC-015.1 tests already do part of that).

---

## 2. PC-side vs sensor-side timestamping, and clock offset estimation (Q2)

### 2.1 Evidence

| Claim | Evidence | Strength | Mechanism and conditions | Status |
|---|---|---|---|---|
| `time.perf_counter()` on Windows is backed by `QueryPerformanceCounter`; "the clock is the same for all processes" (Windows change in Python 3.10); the reference point is undefined, so only differences are meaningful | Python Software Foundation, docs.python.org `time` module, official documentation, tier A | Strong; **requires Python 3.10 or later on Windows** | One OS counter shared by all camera processes | [V] |
| QPC results are consistent across processors, threads and processes (±1 tick ordering ambiguity between threads); monotonic; independent of system-time changes; resolution of about 100 ns to 1 microsecond; not synchronised to any external reference | Microsoft Learn, "Acquiring high-resolution time stamps", updated 2025-12, official documentation, tier A | Strong | Invariant TSC or platform timer, selected by Windows | [V] |
| PC oscillators are typically ±30 to 50 ppm (rarely up to 500 ppm); Windows calibrates the offset at start-up on recent versions; ±10 ppm gives ±60 microseconds per minute | same Microsoft page | Strong (vendor documentation) | Crystal tolerance; stable over temperature | [V] |
| ESP32 high-resolution timer: 1 microsecond resolution, driven by APB_CLK with "less than ±10 ppm deviation"; not kept in sleep modes or across resets | Espressif, ESP-IDF "System Time", tier A | Strong for the stated spec | Reset the offset after every reboot | [V] |
| ESP-IDF SNTP: default update every 1 hour; minimum interval 15 s (RFC 4330); immediate or smooth mode; **no accuracy figure** in the documentation | Espressif, ESP-IDF "System Time", tier A | Strong for behaviour; none for accuracy | SNTP is for wall clock, not for sub-10-ms event stamps | [V] |
| NTP-class accuracy: LAN clients within a few hundred microseconds in good conditions, tens of ms in the worst case; limited by path asymmetry | Mills et al., RFC 5905 (NTPv4), IETF, 2010, standard, tier A | Strong as a standard; nothing about Wi-Fi microcontrollers | 4-timestamp exchange; offset = ((t2 - t1) + (t3 - t4)) / 2; error bounded by half the path asymmetry, so at most half the round-trip delay | [V-bib] (verified in the earlier note) |
| Wi-Fi phone NTP-variant: min-filter over 300 samples gives clock error under about 1 ms; asymmetric one-way latency (about 0.5 to 1 ms) is the dominant error | Ansari, Wadhwa, Garg, Chen, ICCP 2019 (arXiv:1812.09366), peer-reviewed, tier A | Moderate to strong (Pixel phones, custom app, own reference) | Choose the sample with the lowest round trip; its asymmetry is smallest | [V-bib] (verified in the earlier note) |
| Reference Broadcast Synchronization: 1.85 ± 1.28 microseconds on commodity 802.11 hardware (Berkeley-style motes with Wi-Fi cards); removes the sender's nondeterminism from the critical path; claims a clear improvement over NTP | Elson, Girod, Estrin, "Fine-Grained Network Time Synchronization using Reference Broadcasts", OSDI 2002, peer-reviewed, tier A | Strong for the method; hardware is 2002 | Receivers timestamp the same broadcast and compare with each other | [V-bib] (abstract and search snippets) |
| ESP32 RBIS (Wi-Fi beacon as reference): ±30 microseconds | Gundall et al., arXiv:2511.14457 (2025), preprint | Moderate (abstract only) | Needs a custom stack, not available on Android phones | [V-bib] (earlier note) |
| TSF-beacon schemes to fix Wi-Fi NTP asymmetry exist only as patents; no measured paper found | search results were patents | Excluded | - | [UNVERIFIED] |
| Android: camera frame timestamps are not comparable across devices; UNKNOWN source is monotonic with "loose accuracy guarantees" | AOSP Camera2 documentation (`SENSOR_INFO_TIMESTAMP_SOURCE`), tier A | Strong for the API contract; **irrelevant here**, because DroidCam and IP Webcam expose no phone-side timestamps and the project stamps frames at the PC | - | [V-bib] (earlier note) |
| PTP (IEEE 1588) reaches sub-microsecond only with hardware timestamping; not available on consumer phones or ESP32 over Wi-Fi | cited in Ansari 2019; IEEE 1588 not opened | - | - | [V-bib] |

### 2.2 Which gives lower error for a make event?

| Approach | Error source | Size | Evidence |
|---|---|---|---|
| **PC-side stamp at arrival** (no sensor timestamp) | the whole link delay and its jitter | USB tuned: 1 to 2 ms; USB FTDI default: up to 16 ms; ESP-NOW plus USB: about 2.4 ± 1.5 ms plus USB; Wi-Fi UDP: about 105 ms ± 55 to 93 ms | sections 1.1, FTDI note, Montiel Torres 2026. It is a one-sided bias (arrival is always after the event); the median delay can be subtracted, the jitter cannot |
| **Sensor-side stamp**, offset estimated by ping-pong with a minimum-RTT filter | offset estimation error, bounded by half the minimum round trip, plus drift between re-estimations | RTT of 5 ms gives at most 2.5 ms bound `DERIVED` (the bound is a standard property of the 4-timestamp method, RFC 5905 class); Ansari 2019 reached under 1 ms on Wi-Fi with 300 samples | RFC 5905, Ansari 2019 `[V-bib]` |
| Drift between the ESP32 and the PC | relative crystal error | up to 10 ppm (ESP32 spec) plus 30 to 50 ppm (PC typical) gives up to about 60 ppm, i.e. up to 3.6 ms per minute worst case `DERIVED`; with a re-estimate every 10 s that is under 0.6 ms | Microsoft and Espressif docs `[V]`. Note: the spec's 1.2 ms per minute (20 ppm) was derived for phones; it may be too tight a limit to promise for a PC and an ESP32 without a drift fit |

Conclusion for Q2: **sensor-side timestamps give lower and, importantly, jitter-free error on any link whose delay jitter is more than a few ms (Wi-Fi, BLE)**. On a wired USB link with a tuned latency timer, PC-side stamping is already within 1 to 2 ms and is simpler; the choice only matters for wireless links. A sensor-side stamp also keeps the event usable if the PC reads the serial port late (buffering).

Mechanism of ping-pong estimation (standard, `[V-bib]`): PC sends a probe with `t1`; ESP32 records `t2` on receipt and `t3` on reply; PC records `t4` on receipt. `offset = ((t2 - t1) + (t3 - t4)) / 2`, `RTT = (t4 - t1) - (t3 - t2)`. Keep the sample with the smallest RTT in a sliding window (Ansari 2019 min filter), and fit offset against time to estimate drift.

Dissent and caveats for section 2:
- No primary measurement of ping-pong accuracy between a PC and an ESP32 over ESP-NOW, USB or Wi-Fi was found. The 2.5 ms bound and the sub-millisecond expectation are derived or borrowed from phone-to-phone work. **Measure it on the rig**: log the offset residuals during the AC-005.2 LED test.
- On USB, the host-to-device and device-to-host paths have different buffering (FTDI latency timer is one direction only), so the half-RTT assumption is biased by up to about half the timer value if the timer is not tuned. This is my inference [UNVERIFIED]; setting the timer to 1 to 2 ms removes the issue.
- Gundall 2025 (RBIS) and Elson 2002 (RBS) show better accuracy is possible, but neither applies to the phones, which expose no hooks; both would need custom firmware beyond the project's "simplest thing" rule.

---

## 3. Per-camera latency estimation (Q3)

### 3.1 Evidence

| Claim | Evidence | Strength | Mechanism and conditions | Status |
|---|---|---|---|---|
| **LED-to-sensor method** for end-to-end ("glass-to-glass") delay: an LED in the camera view, a phototransistor on the display; 0.5 ms precision at 2 kHz sampling; random intervals between measurements decorrelate samples from the frame phase | Bachhuber and Steinbach (TU Munich), ICIP 2016, DOI 10.1109/ICIP.2016.7532735, arXiv:1510.01134, peer-reviewed, tier A | Strong for the method; measurements are for a wired 50 Hz test camera, not a phone stream | Arduino + LED + phototransistor; two-step edge detection | [V] (ar5iv text read) |
| In that test the delay distribution is about one frame period wide: 50 Hz camera min 19.1, mean about 33, max 52.4 ms, std 6.9 ms (250 samples); 25 Hz camera 24.8 / 50.4 / 78.7 ms; 300 Hz camera 8.1 / 15.5 / 23 ms | same paper | Moderate | The LED turns on at a random phase of the frame period, so a uniform spread of about one period is **expected from the method itself**, independent of network jitter | [V] |
| A 2026 open-source framework (photodiode + microcontroller + calibration) for glass-to-glass latency across devices, comparing H.264 and Motion JPEG | Semeraro, Grazia, Bedogni (Univ. Modena and Reggio Emilia), IEEE CCNC 2026, conference paper, tier A/B | Moderate; abstract only | Same principle as Bachhuber on cheap hardware | [V-bib] (abstract seen via search result; full text not opened) |
| Measuring camera latency by embedding timestamps in the stream (GStreamer), validated with a stopwatch; wired links lower latency than Wi-Fi; the tool flags spikes but hardware delays outside the software limit its precision | Oberndorfer, Master's thesis, FH Upper Austria, 2025, tier B (student thesis, university-hosted) | Weak to moderate; no numbers read | Timestamp embedded into frames, read at the display end | [V] (abstract page) |
| Sub-millisecond camera-to-camera sync by flash detection with rolling shutter (std 0.3 to 0.5 ms) | Smid and Matas, VISAPP 2017 (arXiv:1902.11084) | Moderate | Flash seen row by row; affine time map includes drift | [V-bib] (earlier note) |
| Phone clock drift below 1.2 ms per minute on most of 47 Android models; frame drops produce clustered timestamp differences | Akhmetyanov et al., IEEE Sensors 2021 (arXiv:2107.00987) | Moderate | Camera clock vs system clock on the phone, not the network path | [V-bib] (earlier note) |
| DroidCam: vendor documentation says it uses "very low latency expecting minimal interference"; recommends USB over Wi-Fi when video lags or drops; recommends at least 100 ms of audio sync offset in OBS; **no latency or timestamp figures**; Wi-Fi advice: target 30 fps, 720p default | DroidCam official help page, droidcam.app/help, vendor documentation, tier A for what the vendor says | Weak for latency (no number) | Wi-Fi interference raises delay; USB avoids it | [V] |
| DroidCam developer statements on forum: mobile network adds "1 to 10 seconds" (his guess); USB and hotspot are direct P2P | OBS forum posts by the developer | Excluded (forum, estimate) | - | [UNVERIFIED] |
| IP Webcam (Android) latency | no study, datasheet or official figure found | none | - | [UNVERIFIED] |
| Typical latency and jitter of DroidCam or IP Webcam in ms | not found in any primary source | none | - | [UNVERIFIED] |
| MJPEG over HTTP shows about 1 s lag when the reader does not drain the stream (buffering) | OpenCV Q and A forum (practitioner, tier C) | Excluded as evidence; shown only as a mechanism hint | A slow reader makes a queue; delay grows until the buffer fills | [UNVERIFIED] |
| Wi-Fi link choice affects latency: Ethernet lower than Wi-Fi in the IP-camera thesis | Oberndorfer 2025 | Weak | - | [V] (abstract) |

### 3.2 How to estimate a phone's capture-to-arrival latency (method, synthesised)

| Step | What is measured | Note |
|---|---|---|
| 1. The rim MCU flashes an LED in view of each phone at random intervals (at least 40 flashes, 1 to 5 s apart) and logs each flash time in its own clock | `T_k` on the MCU clock | Same rig as AC-005.2; method pedigree Bachhuber 2016, Smid and Matas 2017, Ansari 2019 |
| 2. The MCU time is mapped to the PC `perf_counter` clock using the ping-pong offset (section 2) | `T_k` on the PC clock | Error budget in section 5 |
| 3. Each camera process finds the first frame in which the LED is lit and takes its `t_recv` | `t_recv,k` | Detection threshold must be fixed in advance |
| 4. `L_k = t_recv,k - T_k`; report median, P95, std, and slope against time | capture-to-arrival latency plus exposure and phase | The random phase makes `L_k` spread over about one frame period even if the real latency is constant (Bachhuber result above). The median over N flashes estimates `L + T_frame/2` with standard error about `T_frame / sqrt(12 N)` `DERIVED` |
| 5. Use `L_cam = median(L_k) - T_frame / 2` for the offset applied to every frame of that camera | per-camera offset | The `T_frame / 2` term is the average wait for the next frame; state the convention in `DATA_CONTRACTS` |

### 3.3 Stability: calibrate once per session, or drift?

- **No primary evidence** for DroidCam or IP Webcam stability over minutes. What the primary sources support: (a) the LED delay spread is about one frame period from phase alone (Bachhuber), so apparent variation is partly method noise; (b) phone clock drift against the system clock is small (under 1.2 ms per minute, Akhmetyanov) but that is the phone's own clock and is not what a PC-side stamp uses; (c) the IP-camera thesis says spikes and elevated latency conditions occur and that Wi-Fi is worse than Ethernet.
- Mechanisms that can move the latency within a session (all `[UNVERIFIED]` for these two apps): reader falls behind and a buffer builds (the project's per-camera process reads frames, so it must drain the stream and drop old frames); Wi-Fi congestion or phone thermal throttling lowers the frame rate or adds encode time; auto-exposure raises exposure time in low light; the app may change bitrate.
- Recommendation: **calibrate at session start (FR-005's startup check) and again at the end, and flag the session if the two medians differ by more than a set amount.** A blinking sensor LED during the session would give a free continuous check, but it needs the LED in both cameras' view and is an option, not a finding.

Dissent and caveats for section 3:
- Every LED method above measures the latency of a particular pipeline. None used DroidCam or IP Webcam. Their latency and its jitter are the largest unmeasured term in the error budget.
- The vendor statement "very low latency" and the 100 ms audio offset advice are weak hints, not figures. Do not quote 100 ms as the DroidCam latency.

---

## 4. Make-detection hardware (Q4)

### 4.1 Evidence found

| Option | Primary or academic evidence | Strength | Mechanism and typical false-positive causes | Status |
|---|---|---|---|---|
| IR break-beam under the net (emitter and receiver across the hoop) | Vishay TSSP58038 datasheet (Rev 1.5, 2018 copy seen): 38 kHz modulated receiver, presence-sensing up to 2 m, detection level independent of ambient light, visible light suppressed by filter. Burst and response-time values **could not be read** (PDF streams not extractable in the session) | Weak: component description only, no basketball data | Modulated IR + receiver gives immunity to sunlight and lamps; the beam is broken by any object, not only a ball; the receiver needs a train of bursts, so response time is of the order of several carrier cycles to a few ms [UNVERIFIED] | [V-bib] (search excerpt of the datasheet) |
| Same, as a built hoop | Spanish-language university thesis (Universitat de Vic - UCC repository), two IR receivers + two LEDs, first sensor for entry and second to confirm passage through the net | Weak (student thesis; page blocked by bot protection; abstract via search only) | Two-stage logic reduces false triggers from hands and net sway [UNVERIFIED]; no false-positive numbers seen | [V-bib] |
| Accelerometer or vibration on the rim (for example ADXL345 with tap or shock detection) | Analog Devices ADXL345 datasheet fetch timed out. Capabilities (output data rate up to 3200 Hz, tap detection with latency and window registers) are recalled, not read | None this session | Detects any impact: a ball hitting the rim, backboard, a hand hanging on the rim, a dunk; a swish that touches nothing produces no impulse | [UNVERIFIED] |
| Piezo film or disc on the rim or net | no datasheet or paper on basketball use opened | None | Same impact ambiguity as an accelerometer; high sensitivity, needs a charge or high-impedance amplifier [UNVERIFIED] | [UNVERIFIED] |
| Stretch or tension sensor in the net | a 2016 West Virginia University student thesis (conductive rubber cord laced round the net); abstract via search only | Weak | Stretches when a ball pulls the net; net sway and wind are likely false-trigger causes [UNVERIFIED] | [V-bib] |
| Microphone on the hoop (sound of ball through net) | patent only | Excluded | - | [UNVERIFIED] |
| Other: camera-only (the project's video call as fallback), load cell on the rim, capacitive or ultrasonic sensing | not researched in primary sources | None | - | [UNVERIFIED] |

**Excluded patent claims** (listed so the gap is explicit, not used as evidence): patents US 6,389,368 and others state that accelerometer devices "could be fooled by a ball bouncing on the rim" and miss shots that touch nothing, and that laser or beam-curtain systems "develop false statistics" when non-ball objects break the beam. They are claims in the prior-art sections of patent filings (marketing-adjacent, no data), so they only mark what to test, not what is true.

**No published reliability figure (percent of makes detected, percent of false positives) for any of the five hardware options was found in a primary source.** The spec's own test (AC-009.1: 10 of 10 hand drops register) is therefore the only available acceptance evidence, and it is small: 10 of 10 gives a 95% lower confidence bound on the detection rate of about 74% (rule of three style bound, `DERIVED`: 0.05^(1/10) = 0.741). It cannot demonstrate a false-positive rate at all. Add a dry-run that records sensor events for several minutes of play with no counted makes (rim hits, net sway, hands) to estimate false positives; this is a test design suggestion, not a source claim.

Dissent and caveats for section 4:
- The break-beam versus impact-sensor trade-off (break-beam sees a clean pass but also anything else crossing; impact sensors miss clean swishes and fire on rim hits) is stated by patents and follows from physics, but has no primary data here.
- Net sway is plausible as a break-beam false trigger only when the net or its shadow crosses the beam; I found no source quantifying it.

---

## 5. Is "one PC clock domain plus a per-camera latency offset" sound? (Q5)

### 5.1 Structure

- **Single clock domain: sound.** All camera processes and the sensor-receiving process run on one Windows PC and stamp with `time.perf_counter()`. Microsoft documents QPC as consistent across processors, threads and processes, and Python docs state the clock is the same for all processes (Windows, Python 3.10 or later) `[V]`. No phone clock is used, which removes the unsynchronisable phone-clock problem (AOSP: not comparable across devices). **Condition:** require Python 3.10 or later and log `time.get_clock_info('perf_counter')` in `run.json`.
- **Per-camera latency offset: sound only as a measured, session-scoped, re-checked value.** The model assumes the capture-to-arrival latency `L_i` of camera `i` is a constant plus small jitter. This is the one assumption with no primary support for DroidCam or IP Webcam.

### 5.2 Error budget (DERIVED; terms marked [A] are assumptions to be replaced by the rig measurement)

Frame rate for the sync test: 30 fps camera period `T = 33.3 ms`, even if the processing rate is lower (10 fps). Terms are 1-sigma unless stated.

| Term | Sensor to phone | Phone to phone | Basis |
|---|---|---|---|
| e1: MCU-to-PC offset estimate (ping-pong, min-RTT, drift fit every 10 to 30 s) | 1 to 3 ms (bound RTT_min/2 with RTT about 5 ms) | cancels (same offset applied to both cameras in the LED test) | `DERIVED` from RFC 5905 class; Ansari 2019 under 1 ms on Wi-Fi |
| e2: sensor trigger physics (beam break or impact to MCU timestamp) | 1 ms [A] | 0 | MCU interrupt latency; [A] |
| e3: latency calibration residual: median of N = 40 flashes, phase uniform over `T` | `T/sqrt(12 N)` = 1.5 ms | 1.5 ms each, so 2.1 ms combined | `DERIVED` |
| e4: **per-frame latency jitter of the stream** (network, encode, decode, buffering) | `[A]` 10 ms (unknown) | `[A]` 10 ms per camera, 14 ms combined | **No primary figure**; sets whether the limits are met |
| e5: rolling-shutter skew inside a frame | 3.3 ms measured on a small LED region; up to one frame period across full height | same, partly cancels if both phones are mounted alike | Akhmetyanov and Ansari `[V-bib]` |
| e6: drift between calibration and use | 0.6 ms (10 s re-estimate); latency drift unknown | latency drift unknown | `DERIVED` |
| **Root-sum-square (e1 to e4, e6)** | about 10.5 ms (1-sigma); about 21 ms (2-sigma, about 95%) | about 14.5 ms (1-sigma); about 29 ms (2-sigma) | `DERIVED` |
| Spec limit | 50 ms (target 20) | 33 ms (target 15) | FR-005 |
| Verdict at the assumed e4 | meets 50 ms; borderline for the 20 ms target at 2-sigma | meets 33 ms only marginally at 2-sigma; **misses the 15 ms target** | **Conditional on e4 = 10 ms, which is unmeasured** |

Reading: the clock model's own error (e1, e2, e3, e6, a few ms) is small against the limits. **The limits are decided by e4, the per-frame latency jitter of the phone streams.** If e4 is 5 ms per camera, phone to phone becomes about 8 ms (2-sigma about 16 ms) and the 15 ms target is nearly met; if e4 is 20 ms (plausible over Wi-Fi with buffering `[UNVERIFIED]`), phone to phone is about 29 ms at 1-sigma and fails the 33 ms limit at 2-sigma. The AC-005.2 LED test must therefore report the **std of `L_k` per camera**, not only median and P95, and must separate method noise (about `T/sqrt(12)` = 9.6 ms at 30 fps from the random phase) from stream jitter.

Possible mitigations if e4 is large (not evidence-backed here, options only): prefer USB for DroidCam (vendor advice, tier A for the statement, no number); drain the stream in the camera process and always take the newest frame; smooth `t_recv` against frame index for constant-rate streams (affine time map, the approach in Smid and Matas 2017); lower the resolution or bitrate.

### 5.3 What the processing frame rate does (reminder from the earlier note)

At 10 fps the make-window margin `a` (160 ms) is dominated by `T_frame` (100 ms), not by the clock terms above. The clock model only needs to be good to a few tens of ms for the sensor-to-phone association; it needs to be good to about 15 to 33 ms only if the two cameras' tracks are interpolated to a common instant before fusion (earlier note, section 4).

---

## Dissent / caveats (overall)

- Two key evidence gaps remain: **(1)** latency and jitter of DroidCam and IP Webcam streams (no primary source), **(2)** reliability of the make-detection hardware (no primary source, patents excluded).
- The ESP-NOW and Wi-Fi UDP latency numbers come from one preliminary conference paper (2 nodes, 2 m, RTT/2). The Espressif documentation itself gives no latency or range number for ESP-NOW.
- The USB 2.0 cable limit (5 m, hubs for more) is from secondary pages only; the standard was not opened. Windows serial read latency and the latency of CP210x, CH340 and the ESP32 native USB were not found.
- The Python 3.10 requirement for a cross-process `perf_counter` is documented; the project should assert it at start-up.
- Date check: Espressif, Microsoft and Python docs were read on 2026-10-19 (current). Papers on phone sync are 2017 to 2021 and the ESP-NOW paper is 2026-06/07; the ESP-NOW paper is within 18 months, the others are not fast-moving areas but phone camera stacks change with each Android release, so re-measure.

## Open questions

1. What is the distance from the rim to the PC at the target courts, and can a USB cable (with a powered hub if over 5 m) reach it? This decides option A versus B.
2. Per-frame latency std of DroidCam (USB) and IP Webcam (Wi-Fi) on the actual phones: measure with the LED rig.
3. Does ESP-NOW from the rim to a PC-side ESP32 hold 100% delivery (with repeats) over the real distance and interference (phones on Wi-Fi in the same 2.4 GHz band)?
4. ESP32-to-PC offset residuals over USB and over ESP-NOW with the min-RTT filter: log them during the LED test.
5. Which make sensor: needs a false-positive dry run (rim hits, net sway, hands) before choosing.
6. Is the spec's drift limit (1.2 ms per minute, from phones) appropriate for the PC and ESP32 pair, or should FR-005 state "re-estimate offset every N seconds" instead?

---

## Options for the ADR

### Decision 1: sensor link

| Option | Trade-offs | Error budget (sensor event to PC clock) | Evidence strength |
|---|---|---|---|
| **L1. Direct USB serial cable, ESP32 to PC** (set bridge latency timer to 1 to 2 ms, or use native-USB ESP32) | Simplest; ordered, checked, unplugging is detected by the OS (helps FR-015 and AC-015.1); no radio interference. Needs a cable from the rim to the PC: 5 m limit without powered hubs (secondary source); cable on the court | PC-side stamp 1 to 2 ms (tuned), up to 16 ms on FTDI default; with sensor stamp + offset about 1 to 3 ms | Medium for the 16 ms mechanism (FTDI, tier A); low for the tuned values and for CP210x/CH340/native USB (undocumented) |
| **L2. ESP-NOW rim ESP32 to a gateway ESP32 on USB at the PC** (sequence numbers, repeats, app-level ACK, sensor timestamp) | No router, no cable at the rim; low latency in the only measurement (about 2.4 ms, 1.1 to 1.5 ms std at 2 m); needs a second ESP32 and the same radio channel; range and loss at court distance unmeasured; only MAC-level ACK, so the app must add reliability (Espressif) | with ping-pong: about 3 to 5 ms (link 2.4 ms + USB hop + offset bound), 100% delivery only after repeats | Medium for the mechanism (Espressif tier A), low for the numbers (one preliminary paper) |
| L3. Wi-Fi UDP through the phones' AP, sensor-side timestamp + offset | Reuses the router; but 105 ms mean latency, 55 to 93 ms std and 1.4 to 2.8% loss in the only measurement, shares the channel with two video streams, and modem sleep can add a DTIM cycle (set `WIFI_PS_NONE`) | Works only with sensor stamps: offset error about 1 to 5 ms; PC-stamped would be about 105 ± 55 to 93 ms and fail the 50 ms limit | Low to medium (mechanism tier A; numbers weak) |
| L4. BLE notification to a PC BLE adapter | No router, low power; connection interval chosen by the central (7.5 ms minimum); no primary latency data; Windows behaviour unverified | about 7.5 to 50 ms [UNVERIFIED] | Low |

**Recommendation: L2 as the default design with L1 as the fallback and the field test that decides.** Reasons: the sensor is at the rim 3.05 m up and the PC position is not known; ESP-NOW avoids a router dependency and the Wi-Fi congestion that two phone streams create; the gateway's USB hop is the same as L1, so the code for L1 is reused. If the PC is within about 5 m of the rim, L1 alone is simpler and should be chosen. Reject L3 and L4 for v1. **Confidence: medium** (low for the absolute milliseconds). Acceptance: AC-009.1 and AC-015.1 plus a 30-minute soak with sequence-number gap counting and a repeat count chosen from the measured loss.

### Decision 2: clock model

| Option | Trade-offs | Error budget | Evidence strength |
|---|---|---|---|
| **C1. PC-side arrival stamp only** (no sensor timestamp) | No sync code; bias equals link delay: acceptable on tuned USB only; unusable on Wi-Fi/BLE | USB tuned 1 to 2 ms, FTDI default up to 16 ms; ESP-NOW+USB about 5 ms ± 2; Wi-Fi about 105 ± 55 to 93 ms | Medium (mechanism); numbers weak |
| **C2. Sensor-side timestamp on the ESP32 `esp_timer`, offset to PC `perf_counter` by ping-pong with min-RTT filter and linear drift fit (re-estimate every 10 to 30 s), plus per-camera latency from the LED test at start and end** | A small protocol and a fit; works on every link, removes link jitter; the camera offset is measured, not assumed; end-of-session re-check catches latency drift. Needs the LED in view of both cameras | Sensor to phone about 10 ms (1-sigma), about 21 ms (2-sigma); phone to phone about 14.5 ms (1-sigma), about 29 ms (2-sigma), **if e4 is 10 ms (assumed)**. Clock-only terms are 2 to 4 ms | Medium for the method (RFC 5905, Ansari 2019 [V-bib]); low for e4 (unmeasured) |
| C3. C2 plus continuous in-session LED blinks for live latency tracking | Detects drift during the session; needs a visible LED, extra detection code, and more complexity against the "simplest thing" rule | as C2 with e6 reduced | Low (no primary evidence it is needed) |
| C4. Hardware-grade sync (PTP, RBS/RBIS, beacon schemes) | Microsecond accuracy possible (Elson 2002; Gundall 2025 preprint), but needs custom firmware on the ESP32 and cannot be applied to the phones (no hooks); no requirement needs it | microseconds, but the phone latency term (e4) is unchanged | Medium for the methods; not needed |

**Recommendation: C2.** The single PC clock domain is documented (Microsoft, Python) and removes the phone-clock problem; the sensor timestamp removes link jitter at the cost of a small, standard protocol; the per-camera offset is measured by the same LED rig the spec already requires (AC-005.2). Add to FR-005 or AC-005.2: report the std of `L_k` per camera, require Python 3.10 or later, re-estimate the ESP32 offset every 10 to 30 s, and compare start and end latency medians. Use C1 only if L1 (USB) is chosen and the sensor-side timestamp proves unnecessary on the bench. **Confidence: medium for C2's structure, low for the claim that FR-005's phone-to-phone limit (33 ms, target 15 ms) will be met**, because the dominating term (per-frame stream jitter) has no primary figure for DroidCam or IP Webcam. If the rig shows jitter above about 10 ms per camera, plan on mitigations in section 5.2 or relax the phone-to-phone target.

---

## Sources opened this session

- Montiel Torres, Balich, Balich, "ESP-NOW vs. WiFi: an analysis of temporal determinism in high-frequency industrial telemetry", JAIIO 2026, 55jaiio.sadio.org.ar/wp-content/uploads/2026/07/273.pdf. [V] (PDF decoded locally)
- Espressif, ESP-IDF API reference "ESP-NOW"; "System Time"; "Wi-Fi Performance and Power Save"; "ESP32 Wi-Fi API" (docs.espressif.com, current). [V]
- Kubascik, "Reliability of ESP-NOW", developer.espressif.com, 2024-12-19. [V]
- Bachhuber and Steinbach, ICIP 2016, arXiv:1510.01134. [V]
- Oberndorfer, "Live Latency Analysis of IP Cameras in Camera Monitor Systems", FH OOe, 2025 (abstract page). [V]
- Microsoft Learn, "Acquiring high-resolution time stamps". [V]
- Python 3 documentation, `time` module. [V]
- DroidCam help page, droidcam.app/help. [V]
- arXiv:2606.13292 (Cauchi et al., VTC 2026), abstract only: not relevant to the questions (no latency method details); not used.
- Seen only as search results (V-bib): FTDI AN232B-04; Silicon Labs CP2102N datasheet; Vishay TSSP58038 datasheet; Elson, Girod, Estrin OSDI 2002; Semeraro et al. CCNC 2026; Eridani et al. iSemantic 2021; IIETA swarm ESP-NOW paper; Universitat de Vic hoop thesis; WVU net-sensor thesis; Bluetooth Core spec values.
- Re-used from the earlier note, not re-opened: Ansari 2019, Akhmetyanov 2021, Smid and Matas 2017, RFC 5905, Gundall 2025, AOSP Camera2 documentation.
- Fetch failures: ADXL345 datasheet (timeout), Vishay PDF (binary not extractable), Eridani PDF (404), Universitat de Vic page (bot challenge), USB-IF specification (not fetched).
