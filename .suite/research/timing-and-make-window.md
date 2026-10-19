# Timing, court geometry and the make-window rule for Pointr Vision

Date of research: 2026-10-19. Protocol: `research-sources` (tiers A/B/C, evidence type, cross-check, date check, verification pass).
Source policy for this note: **primary and academic only** (rule documents, standards, peer-reviewed papers, university groups). Search-engine summaries, forums, patents and vendor blogs were not used as evidence.

Decision framed: *Which numbers should the spec use to (a) tie a rim-sensor "make" event to the shot that caused it and (b) merge two phone cameras into one record per player?*

Recommendation: use a make-window `[t_release - a, t_release + flight_max(d) + a]` with `a = e_clk + e_ts + T_frame` (about 160 ms at 10 fps, about 560 ms at 2 fps), and require a measured clock offset of at most 50 ms for sensor association and at most 15 ms for camera fusion (confidence: **medium** for the structure, **low** for the absolute milliseconds, because phone-to-microcontroller offset over Wi-Fi has no primary measurement and must be measured on the rig).

Verification legend (applies to every claim):
- `[V]` the source text/page was opened and read this session (fetched PDF/HTML, text extracted and searched).
- `[V-bib]` only the bibliographic record or an abstract seen through a search result; the source itself was NOT opened (publisher pages returned HTTP 403 or the search gave only a summary).
- `[UNVERIFIED]` recalled or inferred; not checked.
- `DERIVED` = my arithmetic on `[V]` inputs; it is a calculation, not a measurement or a published number.

---

## 1. Official court geometry

Documents opened (all tier A, standard / official rules):
- FIBA, *Official Basketball Rules 2024* v1.0a, valid 1 Oct 2024 (Rules and Equipment), `assets.fiba.basketball/.../fiba-official-rules-2024-obri-v10a.pdf` [V].
- FIBA, *Official Basketball Rules 2026* v1.0 (rules) and *2026 Equipment* (July 2026), valid 1 Oct 2026 (the edition in force today) [V].
- FIBA 3x3, *Official 3x3 Basketball Rules* (file stamped "Valid as of 1 January 2026"; an older stamp "18 November 2021" also appears in the file), `fiba3x3.com/docs/fiba-3x3-basketball-rules-full-version.pdf` [V].
- NBA, *Official Rules, Rule No. 1: Court Dimensions - Equipment*, `official.nba.com/rule-no-1-court-dimensions/` [V for the text; its court diagram is an image and was not readable].

| Quantity | FIBA 5x5 | FIBA 3x3 | NBA | Evidence (type, tier A) |
|---|---|---|---|---|
| Court size | 28 m x 15 m, inner edge of boundary line [V] | 15 m wide x 11 m long (half court) [V] | 94 ft x 50 ft [UNVERIFIED] (page text has no court size; only the diagram) | FIBA 2024 Art. 2.1; 2026 Art. 2.1 identical [V]; FIBA 3x3 Art. 2.2.1 [V] |
| Three-point / two-point arc | radius 6.75 m from the floor point under the centre of the basket, to the outer edge of the arc; straight segments 0.90 m from the sidelines [V] | "2-point line" 6.75 m, same construction; 1.575 m from baseline [V] | 23 ft 9 in (7.239 m) from the middle of the basket; corner segment 3 ft from sideline [V] | FIBA 2024 Art. 2.5.4; FIBA 3x3 Art. 2.2.4; NBA Rule 1 Sec. I item 4 |
| Corner distance to basket | 6.60 m = 7.50 - 0.90 (DERIVED from [V] 15 m width and 0.90 m) | n/a (half court is 15 m wide: same 6.60 m, DERIVED) | 22 ft [UNVERIFIED] | |
| Free-throw line | furthest edge 5.80 m from inner edge of endline, 3.60 m long, lines are 5 cm wide [V] | furthest edge 5.80 m from inner edge of baseline [V] | 15 ft from the face of the backboard [V] | FIBA 2024 Art. 2.5.3; FIBA 3x3 Art. 2.2.2; NBA Rule 1 Sec. I item 3 |
| Baseline to centre of basket | 1.575 m (inner edge of endline to the floor point under the exact centre of the basket) [V] | 1.575 m [V] | 4 ft backboard offset + 15 in [UNVERIFIED] (text gives ring geometry only: nearest inner ring edge 6 in from backboard, inner diameter 18 in [V]) | FIBA Art. 2.5.4; FIBA 3x3 Art. 2.2.4; NBA Rule 1 Sec. II items 4-5 |
| Rim height | top edge of ring 3,050 mm +/- 6 mm above floor [V] (2026 Equipment 1.2.4; the 2024 rules file only refers to the Equipment appendix) | not found in the 3x3 rules file (the 3x3 equipment appendix was not retrieved) [UNVERIFIED]; same ring expected | upper edge 10 ft = 3.048 m [V] | FIBA 2026 Equipment; NBA Rule 1 Sec. II item 5 |
| Ring inside diameter | 450-459 mm; nearest inside point 151 mm +/- 2 mm from backboard face [V] | [UNVERIFIED] | 18 in = 457 mm; nearest inner edge 6 in from backboard [V] | FIBA 2026 Equipment 1.2.x; NBA Sec. II |

### Rim-centre to free-throw-line distance (the user's estimate of about 4.2 m)

| Rule set | Computation | Result | Status |
|---|---|---|---|
| FIBA 5x5 | 5.80 m (far edge of line) - 1.575 m (rim centre from endline) | **4.225 m** to the far edge; 4.175 m to the near edge of the 5 cm line | DERIVED from [V] inputs. **Confirmed (4.2 m).** |
| FIBA 3x3 | same two numbers | **4.225 m** | DERIVED from [V]. **Confirmed.** |
| NBA | 15 ft (line to backboard face) - (6 in gap + 9 in ring radius = 15 in) = 13.75 ft | **4.191 m** (about 4.19 m) | DERIVED from [V]. **Confirmed (4.2 m).** Caveat: the NBA text does not say which edge of the 2 in line the 15 ft is measured to; the ambiguity is about 0.05 m. |

Corrections to the draft: the 4.2 m figure is right for all three rule sets (within 5 cm). Two other numbers that are easy to confuse: the FIBA free-throw line is **5.80 m from the baseline** (not from the rim), and the NBA arc is **7.24 m** from the rim centre against **6.75 m** FIBA. FIBA 2024 and FIBA 2026 court articles read identically on all values above [V].

Dissent / caveats: NBA court size and backboard offset were not in the readable text (diagram image); do not put 94 x 50 ft or 4 ft in the spec as verified. The FIBA 3x3 file carries two validity stamps.

---

## 2. Shot kinematics

### 2.1 Evidence

| Claim | Evidence (citation, venue, type, sample) | Strength | Mechanism / note | Status |
|---|---|---|---|---|
| Release speed rises with shot distance: 4.39 (2.8 m) to 5.75 (4.6 m) to 6.89 m/s (6.4 m) | Okazaki & Rodacki 2012, *J Sports Sci Med* 11:231-237; kinematic study, 10 male expert players, 100 Hz 2D video, 10 jump shots per distance, rim 3.05 m | Moderate (n=10, 2D, one lab) | Longer shot needs more ball energy; elbow/shoulder/wrist angular velocity increase | [V] (full PDF read) |
| Release height falls slightly with distance: 2.46, 2.38, 2.33 m | same | Moderate | Less jump height at long range (release after the jump peak at close range) | [V] |
| Reported "release angle" 78.9 deg (close), 65.6 (4.6 m), 69.3 (6.4 m) | same | **Weak as a launch angle**: defined from the ball displacement in the first 0.05 s after release and horizontal; the paper's own velocity components imply much flatter angles, and the paper is internally inconsistent (abstract 4.6 / 6.4 m, methods 4.8 / 6.8 m; table columns scrambled in the PDF text) | Do not use these angles for flight time | [V] |
| Free-throw flight time 0.89-1.02 s; release height about 2.02 m; speed 6.99-7.82 m/s; angle 53.3-58.5 deg (mean about 56) | Barzykina 2017, arXiv:1702.07234 (physics-model paper, supported by recorded shots); 25 consecutive free throws, one school student, 52% make rate, 30 fps video; drag and Magnus neglected | Weak-moderate (n=1 novice, 30 fps) but it is a direct time-of-flight measurement | Model: `t = d/(v cos θ)`; successful angle band widens with speed ("smile" region) | [V] (via fetched text of the paper) |
| Optimal free-throw launch angle about 52 deg; up to 3 Hz backspin; higher release is better if consistent; simulation assumed a 70% shooter releasing at 2.134 m | Tran & Silverberg 2008, *J Sports Sci* 26(11):1147-1155; simulation study (hundreds of thousands of 3D trajectories) | Moderate for the optimum, none for observed human data | Aim at the back of the ring; entry-angle effects | [V-bib] (publisher page returned 403; abstract seen via search result; authorship as given in the record) |
| Optimal free-throw trajectory near 60 deg and 7.3 m/s for the modelled release | Hamilton & Reinschmidt 1997, *J Sports Sci* 15(5):491-504; theoretical model | Weak-moderate; later work reports different angles (Tan & Miller about 9 deg lower, Huston & Grau 51.2 deg per a secondary summary) | Model with bounce on rim/backboard; ignores drag | [V-bib] (numbers come from a search summary, not the paper) |
| Minimum-speed angle = 45 deg + half the angle of incline to the basket; higher entry angle widens the success region | Brancazio 1981, *Am J Phys* 49:356 | Theory | Projectile geometry | [V-bib] (paper not opened; formula is attributed to Brancazio's 1984 book in secondary text) |
| Miller & Bartlett 1993, *J Sports Sci* 11:285-293: 3D 50 Hz video of Universiade-level players from three distances | Study exists; their numbers were not seen | - | - | [V-bib] |
| Okazaki, Rodacki & Satern 2015 review, *Sports Biomech* 14(2):190-205 (DOI 10.1080/14763141.2015.1052541) | Review of free throw and jump shot; abstract names three areas (ball trajectory factors, shot phases, other variables) | no numbers seen | - | [V-bib] (page 403 on fetch; abstract from search result) |

Not found with primary access: any study that compares **amateur versus elite** release speed/angle/flight time with numbers I could open. Okazaki & Rodacki 2012 is experts only; Barzykina 2017 is one novice. Treat "player level" as an open question and use wider ranges for amateurs.

### 2.2 Flight time from release to the rim: DERIVED table

Drag-free projectile reaching the rim centre height 3.05 m at horizontal distance `d` (rim-centre distance from line, DERIVED from section 1: free throw 4.19-4.23 m, FIBA arc 6.75 m, NBA arc 7.24 m, half-court heave about 12.4 m = 14.0 m half-court line minus 1.575 m, full-court heave about 24.8 m). Release height 2.0-2.5 m, launch angle 40-60 deg ("core" = 45-55 deg, h = 2.3 m). Inputs: rim height and distances [V], release height and speed range from Okazaki 2012 and Barzykina 2017 [V]. Check of the arithmetic against Barzykina: his measured 0.89-1.02 s falls inside the table's free-throw core range.

| Shot | d (m) | Required release speed (m/s), core | Flight time, core 45-55 deg, h=2.3 | Flight time, full envelope 40-60 deg, h=2.0-2.5, d shortened by up to 0.3 m for forward lean | Your draft |
|---|---|---|---|---|---|
| Close (2 m) | 2.0 | 5.3-5.6 | 0.50-0.66 s | 0.36-0.74 s | 0.5 s: low end of the core range; **raise to 0.5-0.7 s** |
| Free throw | 4.19-4.23 | 7.1 | 0.84-1.03 s | 0.71-1.15 s | 0.9-1.0 s: **confirmed** (and consistent with measured 0.89-1.02 s) |
| FIBA arc | 6.75 | 8.6-8.7 | 1.11-1.35 s | 0.97-1.49 s | 1.1-1.35 s: **confirmed** |
| NBA arc | 7.24 | 8.9-9.0 | 1.15-1.40 s | 1.01-1.55 s | 1.1-1.35 s: slightly low at the top |
| Half-court heave | about 12.4 | 11.4-11.6 | 1.54-1.86 s | 1.38-2.06 s | 1.6 s: fine as a central value, but the range is 1.4-2.1 s |
| Full-court heave | about 24.8 | 15.8-16.3 | 2.2-2.7 s | 2.0-2.9 s | not in draft; out of scope for the first spec |

Limits: no drag, no spin, no rim bounce; the player-level effect on flight time is only through angle and height (a flatter, lower shot is faster). Release speeds here (5.3-9 m/s for d up to the arc) are consistent with the verified measured 4.4-6.9 m/s of Okazaki 2012 for distances up to 6.4 m and the 7-7.8 m/s of Barzykina's free throws: the speed grows with distance, as reported.

Time from rim contact to the sensor "make" event (ball dropping through the net): not found in primary sources; assume 0.1-0.3 s [UNVERIFIED]; it is carried inside `a` below.

---

## 3. Smartphone timing

### 3.1 Evidence

| Claim | Evidence (citation, venue, type, sample) | Strength | Mechanism / conditions | Status |
|---|---|---|---|---|
| NTP-class network time: LAN clients typically within a few hundred microseconds; "a few tens of milliseconds" quoted for the NTPv4 envelope with long polls; accuracy to tens of microseconds only on wired modern workstations | Mills et al., RFC 5905 (NTPv4), IETF, 2010; standard (tier A) | Strong as a standard; says nothing about Wi-Fi phones | Limited by path asymmetry and clock stability | [V] (RFC text read) |
| Wi-Fi/phone NTP-variant with min-filter and 300 samples gives clock error under about 1 ms; the mean filter shows a systematic bias of about 0.4 ms against an external reference; asymmetric one-way latency (about 0.5-1 ms) is the dominant error | Ansari, Wadhwa, Garg, Chen (Google Research), "Wireless Software Synchronization of Multiple Distributed Cameras", ICCP 2019 (arXiv:1812.09366); lab experiment; 2 Pixel 3 phones in the LED-panel test, 5 phones in the rig, 239 trials, WiFi hotspot from a leader phone, clocks stable over 1 h | Moderate-strong (peer-reviewed; own measured reference; only Pixel phones, custom Camera2 app) | NTP-style 4-timestamp exchange; the min filter chooses the lowest round-trip sample; PTP would remove it but is not on phones | [V] |
| Total frame synchronisation (clock + phase) below 250 us (max error 121 us, mean absolute 32 us over 239 trials); naive methods: Wi-Fi trigger 677 ms max, Bluetooth 200 ms, wired 180 ms max error | same paper, Table I | Moderate-strong in lab; relies on the custom app | Software clock sync + frame-phase alignment by exposure injection; reference = LED array with 100 us exposures | [V] |
| NTP-only sync gives only about half a frame of accuracy (for example 16 ms at 30 fps) unless phase alignment is added | same paper (introduction) | Moderate (author statement) | Clock offset plus unknown capture phase | [V] |
| Sub-millisecond video sync: frame differences across 5 pairs of 1-min videos from 2 Galaxy S20 phones are at most 250 us (flash blinking + rolling shutter test) | Akhmetyanov, Kornilova, Faizullin, Pozo, Ferrer (Skoltech), "Sub-millisecond Video Synchronization of Multiple Android Smartphones", IEEE Sensors 2021 (arXiv:2107.00987); app test | Moderate (tiny sample: 2 phones, 5 videos) | Builds on the same phase-alignment method; video mode keeps the phase | [V] |
| Clock drift below 1.2 ms per minute for most of 47 Android models (Firebase test lab); timestamp differences are Gaussian on some phones, while other phones drop frames and the differences fall in clusters (phase kept) | same paper | Moderate (47 models; drift estimated from the last 1000 frames of the timestamp series) | Camera clock vs system clock; after one hour, up to about 72 ms drift on a typical phone if not resynchronised (DERIVED) | [V] |
| Camera2 timestamps cannot be compared with other camera instances or other devices; "UNKNOWN" source is monotonic with "loose accuracy guarantees"; REALTIME needs manual correction for audio sync | Android Open Source Project, platform/frameworks/base commit 1ce3c167 (documentation of `SENSOR_INFO_TIMESTAMP_SOURCE` and `SENSOR_TIMESTAMP`); vendor primary doc (tier A, vendor) | Strong for the API contract | Two phones need an explicit clock-offset step; frame timestamps are on-device clock | [V] |
| Content-based flash sync of rolling-shutter cameras gives std 0.3-0.5 ms (0.44-0.49 ms jointly for 4 cameras) without hardware triggers | Smid & Matas (CTU Prague), "Rolling Shutter Camera Synchronization with Sub-millisecond Accuracy", VISAPP 2017 (arXiv:1902.11084); 5 min of 4 Axis IP-camera streams of one ice-hockey match | Moderate (IP cameras, not phones; one match) | Photographers' flashes detected row by row; affine time map with drift | [V] (arXiv text; venue year from the arXiv record is not stated on the page, VISAPP 2017 is from the slide-deck link: `[V-bib]` for the venue) |
| Frame-level synchronisation is judged too coarse for fast objects (a puck moves about 1.44 m in one 40 ms frame) | same paper | Weak-moderate (author argument) | Motion x frame period | [V] |
| ESP32 with Reference Broadcast Infrastructure Synchronization (RBIS) over a commercial AP reaches +/-30 us | Gundall, Herbst, Muller, Schotten, "Benchmarking OpenWiFiSync on ESP32", arXiv:2511.14457 (Nov 2025, preprint, ETFA 2025 per the page's wording to be confirmed) | Moderate (preprint, abstract read only); it is not SNTP | Uses Wi-Fi beacon broadcast as common reference | [V] for the abstract only; no SNTP baseline on the page |
| Plain SNTP on a microcontroller over Wi-Fi: no millisecond figure from a primary source was found | A TU Wien thesis reports that SNTP "suffers from asymmetric packet delays" and that a filtered variant cut the relative-time standard deviation by up to 78% | no absolute numbers | - | [V-bib] (search snippet only) |
| Audio-beep sync accuracy on phones: **no peer-reviewed measurement found**; results were patents only (not accepted) | - | none | - | [UNVERIFIED] |
| IEEE 1588 (PTP) gives sub-microsecond only with hardware timestamping | cited as a statement in Ansari et al. | Strong as a standard, not available on consumer phones | - | [V-bib] (IEEE 1588 not opened; statement read inside Ansari et al.) |

### 3.2 Achievable accuracy, with conditions (my summary)

| Link | Achievable | Conditions | Source | Status |
|---|---|---|---|---|
| Phone to phone, clock + frame phase, custom Camera2 app | less than 1 ms (lab: 0.03-0.25 ms) | same Wi-Fi hotspot, 300 min-filter samples, exposure-injection phase alignment, Pixel and Galaxy S20 | Ansari 2019; Akhmetyanov 2021 | [V] |
| Phone to phone, clock only (NTP-style, no phase alignment) | about half a frame, e.g. 16 ms at 30 fps; at 10 fps and 2 fps the capture phase is then up to 50 ms and 250 ms off | stock camera app or any app that does not control the frame phase | Ansari 2019 | [V] |
| Drift after sync | less than 1.2 ms/min on most phones (could be larger on some) | after 10 min up to 12 ms, after 60 min up to 72 ms (DERIVED) | Akhmetyanov 2021 | [V] |
| Phone to microcontroller over Wi-Fi with SNTP | **not published at ms level**; protocol-class value "low milliseconds" for a good LAN, tens of ms in the worst case; Wi-Fi power-save and asymmetry can make it worse | - | RFC 5905 (class only) | [V] for RFC; the Wi-Fi/phone figure is [UNVERIFIED] and **must be measured on the rig** |
| Phone to MCU with a purpose-built protocol (RBIS) | +/-30 us | ESP32 only, specific AP | Gundall 2025 | [V] (abstract) |
| Frame timestamp jitter | Gaussian with sub-millisecond spread on some phones; frame drops create clusters; rolling-shutter readout skew inside a frame about 3.3 ms across the LED-panel region of the test, up to roughly one frame period across the full sensor height | per-model | Akhmetyanov 2021; Ansari 2019 | [V] |
| Variable frame rate | not quantified by a primary source for stock apps; Ansari requires a camera that "streams frames indefinitely with low timing variance" | modern phones in Camera2 streaming mode | Ansari 2019 | [V] (requirement), [UNVERIFIED] (stock-app behaviour) |
| Flash/LED sync as a method | std 0.3-0.5 ms | Axis rolling-shutter cameras; LED array in Ansari | Smid & Matas 2017; Ansari 2019 | [V] |

Dissent: every sub-millisecond result uses a custom app that controls the camera pipeline; none shows a stock camera app or an iPhone reaching that. A stock app with only NTP time will not be better than the frame period.

---

## 4. Timing tolerance for multi-view tracking

### 4.1 Player speeds

| Claim | Evidence | Strength | Status |
|---|---|---|---|
| Peak speeds in basketball matches: all 12 players of a Spanish fourth-division team exceeded 24 km/h (6.7 m/s) during the season; "typical elite values" reported in the literature are 20-24.5 km/h (5.6-6.8 m/s) | Ruiz-Alvarez, Leicht, Vaquera, Gomez-Ruano, *Sensors* 25(19):6085, 2025; 12 players, ultra-wideband tracking, one season; the 20-24.5 km/h range is the authors' statement about earlier literature (secondary inside a primary paper) | Moderate for the 6.7 m/s figure, weaker for the range | [V] |
| Sprint speeds above 6.7 m/s reached by only 3 of the players (8%) in an elite U20 study | Game demands in male elite U20 basketball (record seen through a search index) | Weak | [V-bib] |
| Match-play: 5-6 km per 40-min game at high intensity; guards sprint more | Stojanovic et al., *Sports Med* 48:111-135, 2018, systematic review of 25 articles | Moderate; numbers on speed zones not seen | [V-bib] |
| Jog speed 2-3 m/s | zone thresholds were not read from a primary source | - | [UNVERIFIED] (use 2.5 m/s only as an illustration) |

### 4.2 Position error versus timing error (DERIVED: error = speed x offset)

| Timing error | Jog 2.5 m/s [UNVERIFIED speed] | Sprint 6.7 m/s [V] | Where it comes from |
|---|---|---|---|
| 1 ms | 2.5 mm | 6.7 mm | sub-ms phone sync |
| 15 ms | 3.8 cm | 10 cm | roughly half of one 30 fps frame |
| 33 ms | 8.3 cm | 22 cm | one frame at 30 fps |
| 50 ms | 12.5 cm | 34 cm | half a frame at 10 fps |
| 100 ms | 25 cm | 67 cm | one frame at 10 fps |
| 250 ms | 63 cm | 1.7 m | half a frame at 2 fps |
| 500 ms | 1.25 m | 3.4 m | one frame at 2 fps |

### 4.3 What multi-camera systems report

| Claim | Evidence | Strength | Status |
|---|---|---|---|
| A jogger at 10 m/s filmed by two 30 Hz cameras, paired by best-aligned frame, gives up to 40 cm reconstruction error; sub-frame alignment removes most of it | Vo, Sheikh, Narasimhan, "Spatiotemporal Bundle Adjustment for Dynamic 3D Human Reconstruction in the Wild", IEEE TPAMI (accepted), arXiv:2007.12806 (CMU); worked example in the introduction plus mocap experiments | Moderate (illustrative example; the 10 m/s speed is higher than basketball sprinting) | [V] |
| Frame-level alignment is "too coarse" for a fast puck (1.44 m per frame) | Smid & Matas 2017 | Weak-moderate | [V] |
| Stated tolerance for multi-person tracking in km/h terms: **no primary source found** that gives a required synchronisation tolerance in ms for multi-camera player tracking | - | - | [UNVERIFIED] |

Derivation for the spec (not a published threshold): if the association gate between the two camera tracks is about half a body width (0.25 m) and the target speed is the verified sprint peak 6.7 m/s, the timing mismatch must be at most `0.25/6.7 = 37 ms`; for 0.10 m positional accuracy it must be at most 15 ms. Important side effect: **at 10 fps and 2 fps nearest-frame pairing already produces up to 50 ms / 250 ms of mismatch (0.34 m / 1.7 m at sprint speed)**. Clock offset therefore matters only if tracks are interpolated to a common timestamp before fusion; otherwise the frame quantisation dominates.

---

## 5. Make-window rule (DERIVATION, not a measurement)

Rim-sensor event time `t_make` (sensor clock mapped to the PC clock). Detected release time `t_rel` (frame timestamp where the ball leaves the hand, back-dated). Candidate shot is associated if

```
t_make in [ t_rel - a ,  t_rel + flight_max(d) + a ]
a = e_clk + e_ts + T_frame
```

| Term | Meaning | Value | Source / status |
|---|---|---|---|
| `flight_max(d)` | release-to-rim time, upper envelope (40-60 deg, h 2.0-2.5 m), from section 2.2 | close (d up to about 2.5 m) 0.75 s; mid-range and free throw 1.15 s; arc 1.55 s; half-court heave 2.1 s; full-court 2.9 s (out of scope) | DERIVED from [V] rim height and distances; kinematic inputs Okazaki 2012, Barzykina 2017 [V] |
| `e_clk` | clock offset phone-to-sensor, maximum accepted | 50 ms (target 20 ms) | Design limit; achievable value must be measured; literature [V]: 0.25-1 ms phone-to-phone with a custom app, class "low ms" for NTP LAN; phone-to-MCU Wi-Fi [UNVERIFIED] |
| `e_ts` | frame timestamp jitter and rolling-shutter skew | 10 ms | Akhmetyanov 2021, Ansari 2019 [V]; value chosen above the 3.3 ms skew measured and below one 30 fps frame |
| `T_frame` | release detection: quantisation of the release instant to a frame (plus at most half a frame of detector lag if the release is back-dated) | 100 ms at 10 fps; 500 ms at 2 fps | frame period; DERIVED |
| `a` | total margin | **160 ms at 10 fps**; **560 ms at 2 fps** (with the measured offset 20 ms instead of 50 ms: 130 ms and 530 ms) | DERIVED |
| Rim contact to sensor event | time between first touch and the sensor trigger (roll-in, net) | 0.1-0.3 s | [UNVERIFIED]; not added separately; at 10 fps it is covered partly by `flight_max`'s upper envelope, so the check on the rig is mandatory |

Initial values (DERIVED, to be replaced by the rig measurement):

| Frame rate | Close | Free throw / mid-range | Arc | Heave (half court) |
|---|---|---|---|---|
| 10 fps (`a` = 0.16 s) | [-0.16, +0.91] s | [-0.16, +1.31] s | [-0.16, +1.71] s | [-0.16, +2.26] s |
| 2 fps (`a` = 0.56 s) | [-0.56, +1.31] s | [-0.56, +1.71] s | [-0.56, +2.11] s | [-0.56, +2.66] s |

The lower bound is negative only to absorb timing error: physically the make cannot precede the release. At 2 fps the window is about 2-3 s wide, which will often contain two candidate shots (for example a put-back after a miss); the tie-break must use the distance-dependent `flight_min(d)` (see table 2.2, lowest values) to discard releases that are too recent, and choose the release whose predicted flight time best matches `t_make - t_rel`.

Inputs not verified: release-detection lag of the actual detector, sensor-to-network latency, and the roll-in time. They are the largest unknowns; the rig test below measures them.

---

## Dissent / caveats

- All sub-millisecond phone results are from custom apps in a lab with 2-5 phones; the rig's real apps, phones and Wi-Fi are different.
- Flight time is derived without drag or spin; measured free-throw flight (one novice, 30 fps) supports the free-throw core range only.
- No primary study was found comparing amateur and elite release kinematics with numbers, nor any published ms tolerance for multi-camera basketball tracking, nor a measurement of SNTP on microcontrollers over Wi-Fi.
- Okazaki & Rodacki 2012 is internally inconsistent (distances 4.6/6.4 m vs 4.8/6.8 m; release-angle definition); only its speeds and heights were used.
- Date check: FIBA rules were taken from the 2024 and 2026 editions (2026 in force from 1 Oct 2026); timing papers are 2017-2021 (not "fast-moving AI tooling", so no `[STALE?]`), but phone camera stacks change with each Android/iOS release; re-measure.

## Open questions

- Phone-to-sensor (ESP32 or similar) offset over the actual Wi-Fi: unknown, to be measured.
- Does the chosen camera app expose per-frame hardware timestamps in the same clock as the system clock on both phones?
- Rim-contact to sensor-event delay and detector release lag.
- Whether the spec should use frame-rate-specific windows or one window of `max(a)`.

---

## Valores recomendados para o spec

Todos os valores abaixo sao derivacoes a partir de fontes lidas; nenhum e uma medicao do equipamento real. Forca: **alta** = regra oficial lida; **media** = aritmetica sobre entradas lidas; **baixa** = depende de algo nao verificado.

| # | Valor | Recomendacao | Forca | Base |
|---|---|---|---|---|
| 1 | Offset maximo de relogio para associar evento do sensor ao arremesso | **ate 50 ms** (meta: 20 ms). Com `T_frame` de 100 ms (10 fps) ou 500 ms (2 fps), o offset nao deve dominar a margem; acima de 100 ms a associacao deve ser marcada como duvidosa. | **Baixa-media**: o limite e de projeto; o valor alcancavel entre celular e microcontrolador por Wi-Fi nao tem fonte primaria (so a classe "ms baixos" da RFC 5905) e precisa ser medido. | Secao 3 e 5 |
| 2 | Offset maximo de relogio para fusao das duas cameras | **ate 15 ms** (limite duro 33 ms), **com interpolacao das trilhas para um instante comum**; sem interpolacao, a quantizacao por quadro (ate 50 ms a 10 fps, 250 ms a 2 fps) domina e o offset deixa de ser o gargalo. | **Media**: erro = velocidade x offset com velocidade de sprint de 6,7 m/s (Ruiz-Alvarez 2025, lido); o limite de 0,10 m / 0,25 m e escolha de projeto, sem tolerancia publicada. Sincronizacao celular-celular de menos de 1 ms existe (Ansari 2019, Akhmetyanov 2021, lidos), mas so com app proprio de camera. | Secao 3 e 4 |
| 3 | Formula da janela de "make" | `[t_lancamento - a ,  t_lancamento + voo_max(d) + a]`, com `a = e_clk + e_ts + T_quadro`; `e_clk` = offset aceito (50 ms), `e_ts` = 10 ms, `T_quadro` = periodo do quadro. | **Media** (estrutura); **baixa** (constantes) | Secao 5 |
| 4 | Valor inicial da janela | `a` = **160 ms a 10 fps** e **560 ms a 2 fps**. `voo_max(d)`: perto 0,75 s; lance livre/meia distancia 1,15 s; arco 1,55 s; arremesso de meia quadra 2,1 s. Ex.: arco a 10 fps = [-0,16 s ; +1,71 s]; a 2 fps = [-0,56 s ; +2,11 s]. E uma **derivacao, nao uma medicao**; substituir pelos valores medidos no teste abaixo. | **Media-baixa**: tempos de voo vem de balistica sem arrasto com altura 2,0-2,5 m e angulo 40-60 graus, conferidos contra voo medido de 0,89-1,02 s (Barzykina 2017, n=1) e velocidades de saida medidas (Okazaki e Rodacki 2012, n=10). | Secoes 2 e 5 |
| 5 | Teste para medir o offset real de relogio na estrutura | Ver procedimento abaixo. | Metodo validado por Ansari 2019 e Smid e Matas 2017 (referencia por LED/flash); limites de aceite sao de projeto. | Secao 3 |

Geometria oficial a usar no spec (alta forca, regras lidas): quadra FIBA 28 x 15 m; meia quadra 3x3 15 x 11 m; arco FIBA/3x3 6,75 m do centro da cesta; arco NBA 7,24 m (23 pes e 9 pol); linha de lance livre FIBA/3x3 a 5,80 m da linha de fundo e NBA a 15 pes da tabela; centro da cesta a 1,575 m da linha de fundo (FIBA e 3x3); aro a 3,05 m (FIBA) e 10 pes (NBA). Distancia centro da cesta a linha de lance livre: **4,22 m (FIBA e 3x3) e 4,19 m (NBA): a estimativa de 4,2 m esta correta**. Nao registrar como verificados: tamanho de quadra e recuo da tabela da NBA, altura do aro no 3x3.

### Teste para medir o offset real de relogio (pelo menos 30 minutos, repetir no inicio e apos 30-60 min)

1. **Pulso de LED**: o microcontrolador do sensor do aro pisca um LED visivel para as duas cameras, em instantes `T_k` (k = 1..N, N >= 40, intervalos aleatorios de 1-5 s para variar a fase em relacao ao quadro) e registra cada `T_k` no seu relogio.
2. Cada celular grava no modo e fps de operacao (10 fps e 2 fps) com marcas de tempo de hardware por quadro. Para cada pulso, achar o primeiro quadro com o LED aceso (usar a linha do rolling shutter onde o LED aparece) e calcular `offset_k = ts_quadro - T_k_mapeado`.
3. Reportar: mediana do offset, percentil 95 do valor absoluto, desvio-padrao e a inclinacao em ms/min (deriva). A quantizacao de +/- T_quadro/2 se reduz por `T_quadro/raiz(N)` gracas a fase aleatoria.
4. **Entre as duas cameras**: o mesmo LED aparece nas duas; a diferenca entre os instantes dos quadros do mesmo pulso da o offset celular-celular (refinar com o teste de 1-2 min a 60 fps, se o app permitir).
5. **Criterios de aceite**: mediana e P95 do offset celular-sensor <= 50 ms (meta 20 ms); celular-celular <= 15 ms; deriva <= 1,2 ms/min (limite de Akhmetyanov 2021) ou resincronizar a cada 10 min.
6. **Ponta a ponta**: 50 arremessos reais (ou lancamentos de bola pelo aro) com marcacao manual do instante de soltura e do evento do sensor; medir `t_make - t_soltura` por distancia e verificar que 100% ficam dentro da janela e quantos arremessos vizinhos caem na janela (ambiguidade). Ajustar `voo_max(d)` e o tempo entre toque no aro e evento do sensor com estes dados.

---

## Sources opened this session (all fetched and read unless marked)

- FIBA Official Basketball Rules 2024 v1.0a and 2026 v1.0 (rules) and 2026 Equipment, assets.fiba.basketball, 2024-2026. [V]
- FIBA 3x3 Official Rules, fiba3x3.com/docs/fiba-3x3-basketball-rules-full-version.pdf. [V]
- NBA Official Rules, Rule No. 1, official.nba.com/rule-no-1-court-dimensions/. [V]
- Okazaki & Rodacki 2012, J Sports Sci Med 11:231-237, jssm.org/11-2-231.p_d_f. [V]
- Barzykina 2017, arXiv:1702.07234. [V]
- Ansari, Wadhwa, Garg, Chen 2019, arXiv:1812.09366 (ICCP 2019). [V]
- Akhmetyanov et al. 2021, arXiv:2107.00987 (IEEE Sensors 2021). [V]
- Smid & Matas 2017, arXiv:1902.11084. [V]
- Vo, Sheikh, Narasimhan, arXiv:2007.12806 (TPAMI). [V]
- Mills et al., RFC 5905 (2010); RFC 4330 (SNTP v4, 2006). [V] (RFC 5905 quoted for accuracy class only)
- AOSP commit 1ce3c167 (Camera2 timestamp documentation). [V]
- Ruiz-Alvarez et al. 2025, Sensors 25(19):6085. [V]
- Gundall et al. 2025, arXiv:2511.14457. [V] (abstract)
- Tran & Silverberg 2008; Hamilton & Reinschmidt 1997; Miller & Bartlett 1993; Okazaki, Rodacki & Satern 2015; Brancazio 1981; Stojanovic et al. 2018. [V-bib]
