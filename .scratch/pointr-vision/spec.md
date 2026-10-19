# Spec — Pointr Vision (December test rig)

source: `.scratch/pointr-vision/decision-record.md` · scope decided with the owner on 2026-10-19

## Scope
**In scope: the December test rig.** It is operated by the owner only, with the owner's group (adults), on 2 phones with fusion, a rim sensor and a borrowed GPU PC. It exists to answer H1–H4, H3b, H6 and H7 of the decision record.

**Backlog (specified later, each when a test justifies it):**
| item | hypothesis | why not now |
|---|---|---|
| "Guarded by" as defender proximity | none yet | tests no December hypothesis |
| Session browser | none | engineering convenience |
| Live metrics in games | H8 (no threshold) | needs H1 and H3 first |
| Cloud sync | none | no hypothesis; first item dropped |
| Coach-facing report | H5 | after a recording exists (owner decision) |
| Learned re-identification ("AI" identity) | H3 | after the jersey method works; architecture first |
| Shot form and hand analysis | none | v2 |

Already built, not re-specified here: person detection and tracking, per-frame logs, health monitor, movement metrics, session folders.

## Completeness check
Who else should have a say: nobody in v1; the owner is the only operator, developer and data viewer · What is missing (data, failure cases, constraints): found in the interview: a way to score the tests against hand labels (FR-013) and a shared clock for phones and sensor (FR-005); failure cases still to confirm: one phone dropping mid-session, sensor offline mid-session, phone battery or overheating · Answered by: owner (solo operator and developer)

## Functional requirements
| ID | User story / EARS statement | as-is / to-be | Hypothesis (MVP) | Metric + threshold | If it fails | Priority |
|---|---|---|---|---|---|---|
| FR-001 | When the operator starts a session, the system shall connect to every configured phone stream and show each camera's status and errors. | as-is | H7 | built; timed inside the H7 setup measurement | simplify setup | 1 |
| FR-002 | When the operator clicks known court points in a camera image, the system shall fit a homography to court metres and check it on points not used for the fit. | as-is | H4 | check error at most 0.5 m against hand measurement on a real court | fix calibration or stop | 1 |
| FR-003 | Before a session starts, the operator shall list the jersey numbers of the players present, and the system shall run five checks, show each result on screen and write it to run.json: at least one camera connected, with the others reported; each connected camera calibrated (error against CFG-003); each listed player gets the correct jersey number after standing in view for 10 seconds; each listed player keeps that number after stepping out of view and back in once; the rim sensor registers 10 of 10 hand drops through the rim. If a check fails, the session shall start anyway with the failure recorded, provided at least one camera is connected. A camera that fails calibration logs positions in pixels, is flagged, and is excluded from fusion. | to-be | H7 | setup time, from the first phone placed to the session started, retries included, is at most 15 minutes (timed); 100% of sessions carry the five results in run.json and on screen | simplify setup | 1 |
| FR-004 | When two phones see the same player, the system shall align their tracks to a common timestamp and merge their records into one final record per player, with each action and stat counted once, and shall report where the two cameras' records for that player differ. | to-be | H6 | the final record lists each person once (distinct IDs equal people on court) in 100% of two-phone test sessions; the share of merged player-frames and the camera differences are reported, and their thresholds are set after the first two-phone session | review the merge rules before the next session | 1 |
| FR-005 | The system shall place every phone frame and every sensor event on one shared timeline, and shall re-estimate the sensor's offset to the PC clock every 10 to 30 seconds. | to-be | H6 | clock offset measured with the LED rig test (AC-005.2): sensor to phone at most 50 ms (target 20 ms); phone to phone at most 33 ms, one frame at 30 fps (target 15 ms); the sensor-to-PC offset re-estimated every 10 to 30 seconds and checked again at session end, and the per-camera latency standard deviation reported (values derived in .suite/research/timing-and-make-window.md, not measured on this rig) | fix the clock sync before any fusion result is trusted | 1 |
| FR-006 | When a player is visible, the system shall assign the track ID equal to the number on their jersey or vest. | to-be | H3 | at least 80% of tracks carry the correct number after voting across frames (counted on tracks covering about 200 hand-labelled frames) | 50–80%: vests with large numbers or manual correction; under 50%: drop the jersey approach | 1 |
| FR-007 | When a player leaves the frame and returns at any point in the same drill, the system shall give them the same ID. | to-be | H3b: the ID survives leaving the frame | at least 8 of 10 returns keep the same ID (owner) | vests with large numbers or manual correction; if still under 8 of 10, decide at the 2026-12-31 review | 1 |
| FR-008 | The system shall detect the ball and the rim in each processed frame. | to-be | H1, H2 | no separate threshold: ball and rim detection are judged through the FR-010 attempt rate, and the share of frames with the ball found is reported; run on the borrowed GPU PC for H2 | see FR-010 and NFR-001 | 1 |
| FR-009 | When the ball passes through the rim, the sensor shall send a make event with a timestamp to the PC. | to-be | H1 | 10 of 10 hand drops through the rim register at the startup check (owner); a dry run with rim hits, net sway and hand passes counts false triggers, and the count is reported | repair or replace the sensor; make calls fall back to video only | 1 |
| FR-010 | When a shot is released, the system shall log an attempt and call it make, miss or uncertain, using the edge-case rules of the decision record (section 4). A sensor make event matches a shot when it falls inside [release time − a, release time + flight_max(d) + a], where d is the shooter's distance to the rim, flight_max(d) is 0.75 s close, 1.15 s free throw or mid-range, 1.55 s arc and 2.1 s half-court (research note), and a is CFG-005 plus one frame period. | to-be | H1 | at least 85% of attempts found and at least 90% of those called right (30 or more shots, hand-counted) | 70–85%: rely on the sensor; under 70% vision-only: stop vision-only | 1 |
| FR-011 | When a make or miss is logged, the system shall attribute the shot to the player who last had possession, or log "shooter unknown". | to-be | H1, H3 | share of shots credited to the correct player, measured on the labelled December sessions; the pass threshold is set by the owner after the first December session | decide at the first December review | 2 |
| FR-012 | The system shall place each attempt at the shooter's position at release, in court metres, and plot it as a map. | to-be | H1, H4 | position error at most 0.5 m against taped marks | fix calibration or stop | 2 |
| FR-013 | When a hand-labelled session exists, the system shall compute the H1, H3, H3b and H4 results from the logs and labels and print them next to their thresholds. Labels are a CSV file with the columns time, event (attempt, make, miss, leave, return) and player number. A detected event matches a label inside the tolerance from the research note. H1 is scored twice: on video alone, which decides the thresholds, and on video plus sensor, which is reported; the hand labels are the ground truth when sources disagree. An "uncertain" call counts as wrong for "called right" and is also reported separately, and false attempts are reported separately. The H4 result is the position error against taped marks (FR-012). | to-be | H1, H3, H3b, H4 (test instrument) | results from the tool equal a hand calculation on one session | score by hand from the CSV files | 2 |
| FR-014 | If one of two phones loses its stream mid-session, the system shall continue with the remaining camera and mark the start and end of the gap in run.json. When the phone returns, the system shall resume it and re-link player IDs by jersey number, as for a player returning to the frame. | to-be | H6 | every forced disconnect in the test (at least 3) keeps the session running, marks the gap and resumes the camera on return; the detection time of each loss is reported; gap periods are left out of the H3b and H6 scoring and reported separately | fix before the first two-phone December session | 1 |
| FR-015 | If the rim sensor stops responding mid-session, the system shall log the start and end of the outage and flag makes in that interval as "no sensor", continuing with the video calls. | to-be | H1 | after an unplugged-sensor test, 100% of the outage interval is flagged | fix before the first December session | 2 |

## Acceptance examples
### AC-001.1 (FR-001)
Given two phones on the same network, when the operator starts a session, then both streams show as connected within 60 seconds, or the failing camera shows an error naming it. (The 60 seconds is the connect step only; the 15-minute limit in FR-003 covers the whole setup.)

### AC-002.1 (FR-002)
Given eight clicked points of which two are held out, when the fit finishes, then the check error on the held-out points is printed and a result over 0.5 m is marked failed.

### AC-003.1 (FR-003)
Given the rim sensor is unplugged, when the operator starts the session, then the session starts, run.json lists the sensor check as failed, and the report states that no makes were recorded by the sensor.

### AC-003.2 (FR-003)
Given camera 1 has a calibration check error of 0.9 m and camera 2 has 0.3 m, when the operator starts the session, then camera 1 logs pixels, is flagged and is left out of fusion, and camera 2 logs metres.

### AC-003.3 (FR-003)
Given the operator lists players 4, 7 and 11, when each stands in view for 10 seconds, then the check passes only if each gets its own number; a wrong or missing number is recorded as failed and the session still starts.

### AC-004.1 (FR-004)
Given one player visible to both phones, when the session ends, then the final record lists that player once, with each shot and stat counted once, and a difference report lists where the two cameras disagreed.

### AC-005.1 (FR-005)
Given a sensor event and a camera frame recorded at the same moment, when the session is loaded, then both carry timestamps from the same clock.

### AC-005.2 (FR-005)
Given the sensor flashes an LED in view of both phones at least 40 times at random intervals and logs each flash time, when each flash is compared with the first video frame where the LED lights, then the median, 95th percentile and standard deviation of the latency per camera are reported, together with the sensor offset estimates at session start and end, and the offsets meet the FR-005 limits; the test is repeated after 30 to 60 minutes.

### AC-006.1 (FR-006)
Given a player wearing the number 7, when the player stands in view of a phone for 10 seconds, then the voted number for that track is 7, and across the labelled tracks at least 80% have the correct voted number.

### AC-007.1 (FR-007)
Given player 7 walks out of frame and back in after 30 seconds, when tracking resumes, then the player has ID 7 again; 8 of 10 such returns must keep their ID.

### AC-008.1 (FR-008)
Given a recorded shot, when the frames are processed, then the ball and the rim are boxed in the frames around the release.

### AC-009.1 (FR-009)
Given 10 balls dropped through the rim by hand at the startup check, when the last one has passed, then 10 make events with timestamps have reached the PC, or the check is recorded as failed.

### AC-009.2 (FR-009)
Given a dry run of 10 rim hits, 10 net sways and 10 hand passes with no ball through the rim, when the run ends, then the number of false make events is reported.

### AC-010.2 (FR-010)
Given a free throw released at time t at 10 frames per second, when a sensor make event arrives at t + 0.9 s, then the shot is a make; when the only event arrives at t + 3 s, then it is not matched to that shot.

### AC-010.1 (FR-010)
Given 30 hand-counted shots, when the session is scored, then at least 85% of attempts are found and at least 90% of those carry the correct make or miss.

### AC-011.1 (FR-011)
Given a make with no clear possession before the shot, when it is logged, then the shooter is "unknown" and the shot is not credited to any player.

### AC-012.1 (FR-012)
Given a shot released from a taped mark, when the map is drawn, then the plotted point lies within 0.5 m of the mark.

### AC-013.1 (FR-013)
Given a session with hand labels, when the scoring tool runs, then it prints H1, H3, H3b and H4 results and the thresholds side by side.

### AC-014.1 (FR-014)
Given a two-phone session in progress, when one phone's stream is cut three times (5, 20 and 60 seconds) and restored each time, then the session keeps running on the other camera, run.json holds each gap with its detection time, and the phone resumes on return with player IDs re-linked by jersey number.

### AC-015.1 (FR-015)
Given a session in progress, when the rim sensor is unplugged for 60 seconds and replugged, then run.json holds the outage, and any make in that interval is flagged "no sensor".

## Quality requirements (ISO/IEC 25010 categories)
| ID | Characteristic | Verifiable behaviour | Metric | Target | Verified by |
|---|---|---|---|---|---|
| NFR-001 | Performance efficiency | total processing rate with two phones streaming on the borrowed GPU PC | frames per second, total across both phones | baseline measured in the H2 run, then the owner sets a hard limit (reference from the decision record: about 10–15 with one phone) | GPU run on the borrowed PC |
| NFR-002 | Performance efficiency | delay between the camera and detections on screen, kept as low as the design allows | seconds | baseline measured in the H2 run, then the owner sets the ceiling (reference: 0.4–0.7 s on the CPU laptop today; 1–2 s is too much) | GPU run on the borrowed PC |
| NFR-003 | Maintainability | the identity method is replaceable behind a fixed interface | columns changed in tracks.csv when swapping the jersey method for another | 0 | run both methods over one recorded session and compare the file headers |
| NFR-004 | Reliability | a crash mid-session leaves readable files and an honest status | files that load after the process is killed | 100% load; status reads incomplete | kill test during a session |

## Constraints
cost: about 100 BRL of new hardware (rim sensor); 2 phones supplied by the owner, possibly 3; a borrowed GPU PC · deadline: December 1- and 2-person tests; review on 2026-12-31 · data: all session video and data stay on the owner's PC, and videos are kept for training · people: adults in the owner's test group only; consent and minors are out of scope for the PoC and reopen if anyone outside that group is filmed · team: one developer working with AI agents

## Configuration register
| ID | Name | Option / flag | Why the system can't decide | Type, format, valid range | Safe default | Depends on / invalid combinations | Value per env (dev/test/prod) | Secret? Source | Owner | Expiry + removal criterion (flags) | On invalid value | Validated / tested by | Deployed by | Doc text |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CFG-001 | CAMERA_SOURCES | option | depends on which phones are in use | list of stream addresses, 1 to 4 entries | none; must be set | fusion needs 2 or more entries | same on every run | no | owner | — | refuse to start; message names the option, the value received and the valid range | startup validation; unit test with 0, 1 and 5 entries | edited config file | generated from this row |
| CFG-002 | FRAME_RATE_TARGET | option | depends on the PC's hardware | integer 1 to 30 frames per second, total across all cameras | 10 | none | set per PC | no | owner | — | refuse to start; message names the option, the value and the range 1–30 | startup validation; measured in the H2 run | edited config file | generated from this row |
| CFG-003 | CALIBRATION_MAX_ERROR_M | option | defines what counts as a failed calibration (H4) | number 0.1 to 2.0 metres | 0.5 | none | same on every run | no | owner | — | refuse to start; message names the option, the value and the range | startup validation; tape test (H4) | edited config file | generated from this row |
| CFG-004 | IDENTITY_METHOD | option | selects the identity layer so the method stays replaceable (NFR-003); vests with large numbers and manual correction are fallbacks named in FR-007, not identity methods | enum: jersey | jersey | a future learned method needs a model-path option; no other combinations | same on every run | no | owner | — | refuse to start; message names the option, the value and the allowed list | startup validation; NFR-003 comparison test | edited config file | generated from this row |
| CFG-005 | MAKE_MATCH_ALLOWANCE_MS | option | covers clock offset and timestamp jitter when matching a sensor event to a shot; only the rig can measure it | integer 0 to 500 ms | 60 (50 ms clock offset plus 10 ms timestamp jitter, from the research note; tuned after the December rig test) | none | same on every run | no | owner | — | refuse to start; message names the option, the value and the range | startup validation; LED rig test and December tests | edited config file | generated from this row |

## Validation record
Structured reading (usage-based) by: independent Sonnet agent with no prior context, tasks A (start a 2-phone session), B (run and score 30 shots), C (phone drops) · date: 2026-10-19 · defects found: 18 (5 high, 9 medium, 4 low); 11 fixed by wording, 7 batched as open question 8, 1 waiting for the research note (FR-005)
Flow walk-through with user: · Prototype test (if UI): · Hypothesis test planned: the December tests (H1–H4, H3b, H6, H7)

## Open questions
| # | Question | Recommended answer | Owner | Deferred? |
|---|---|---|---|---|
| 1 | FR-005: confirm the clock limits from the research note: sensor to phone at most 50 ms (target 20), phone to phone at most 33 ms (target 15), drift at most 1.2 ms per minute | yes | owner | resolved: confirmed by the owner on 2026-10-19 |
| 2 | FR-011: what share of shots credited to the correct player counts as a pass? | owner's number first | owner | yes: after the first December session (owner decision) |
| 3 | CFG-005: confirm the make-matching rule (window per shot from its distance to the rim, allowance 60 ms plus one frame period) | yes | owner | resolved: confirmed by the owner on 2026-10-19 |
| 4 | NFR-001 and NFR-002: the hard limits for frame rate and delay | set after the baseline measured in the H2 run | owner | yes: after the H2 baseline |
| 5 | FR-004: thresholds for the merged-frame share and camera differences | set after the first two-phone session | owner | yes: after the first two-phone session |
| 6 | How does the rim sensor reach the PC (serial, Wi-Fi, Bluetooth)? | decide with the architecture | owner and agent | yes: decided in stage 3 (dev-model) |
| 7 | Which "AI" identity method, and when? | after the jersey method works | owner | yes: backlog, after H3 |
| 8 | Confirm the fixes from the reading: (a) a camera failing calibration is left out of fusion and logs pixels; (b) a session needs at least one camera; (c) the startup identity check uses a roster typed by the operator, with 10 seconds in view; (d) "uncertain" counts as wrong in "called right"; (e) gap periods are left out of H3b and H6 scoring; (f) a returning phone resumes and re-links IDs by jersey number; (g) a sensor outage flags makes as "no sensor" | yes to all | owner | resolved: confirmed by the owner on 2026-10-19 |

## Change requests
CR-1 (built code, to verify): the owner said a refused calibration does not behave as FR-003 describes. The repo shows otherwise for a missing or corrupt calibration: DECISIONS.md D-027 and services/app/server.py (event calibration_not_used) start that camera uncalibrated with a warning, and tracks.csv keeps the pixel box with empty x_m and y_m (DATA_CONTRACTS section 5). Open: what the owner saw that differs, for example a calibration rejected at fit time, or a whole session refusing to start.
CR-2 (FR-005, accepted by the owner 2026-10-19): the drift limit of 1.2 ms per minute was a phone figure; replaced by a periodic sensor offset estimate and a per-camera latency standard deviation (D-035). Amended in place.
CR-3 (FR-006, accepted by the owner 2026-10-19): the 80% target is read per track after voting across frames, as the literature scores it; the decision record's H3 is read the same way (D-039). Amended in place.
CR-4 (FR-009, accepted by the owner 2026-10-19): a dry run counts false triggers, because 10 of 10 hand drops proves little about them (D-036). Amended in place.

## Sign-off
approved_by: owner (project owner) · date: 2026-10-19
