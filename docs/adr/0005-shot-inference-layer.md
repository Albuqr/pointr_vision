# 0005 — Shot inference as a separate layer over the logged streams
status: accepted · date: 2026-10-19 (accepted by the owner)

## Context
FR-010 logs attempts and calls make, miss or uncertain, matching sensor events with the window rule of the spec; FR-011 attributes the shooter; FR-012 maps the shot; FR-013 scores everything against hand labels. Frames are processed at 2–15 fps, and a shot release lasts well under a second. `ARCHITECTURE.md` already treats the session files as the source of truth, and a replay creates a new run. The owner keeps videos for training and wants real time where possible; live in-game numbers (H8) are backlog.

## Options considered
| Option | Pros | Cons | Fit to NFRs |
|---|---|---|---|
| B1. Shot logic inside the live processing loop | Lowest delay | Couples shot rules to a 2–10 fps loop; a bug stops perception; hard to re-score against labels; worst accuracy at low fps | Against NFR-003 |
| B2. A separate layer reading the logged streams (frame and person boxes, ball and rim boxes, sensor events, timestamps); usable live by tailing the log and afterwards by replay; a full-rate post-session pass decides H1 | Same code live and in replay; rules can be re-tuned on kept video; a candidate shot can trigger re-detection at full rate; FR-013 uses the same logs | A log schema contract; live calls arrive 1–2 s after the shot | Fits NFR-003 and NFR-004 |
| B3. Post-session only | Highest accuracy, with frames before and after each gap | No live numbers | Acceptable, since H8 is backlog |

## Decision
Decided (owner, 2026-10-19): **B2**. The post-session full-rate pass on the recorded video is the number that decides H1; the live tail is a convenience. The rules (edge cases, window formula `[release − a, release + flight_max(d) + a]`, shooter by last possession) are those of the decision record and spec FR-010 and FR-011. The layer needs recorded video and replay, which are Phase 04 deliverables, so they become the first slice of the new track.

## Consequences
- New output `shots.csv` (attempt time, shooter or unknown, call, source video or sensor, window used): contract change.
- Live results lag the shot; the live feature stays out of the December pass criteria.
- Confidence: medium-high for the structure, medium-low that live calls at 2–10 fps will be accurate. No source measures ball detection below 15 fps, and a frame-dropping study on vehicle tracking is the nearest evidence that low rates hurt tracking.

## Sources
- [The impact of frame-dropping on multi-object tracking (Henning et al., IEEE IV 2023)](https://arxiv.org/abs/2304.08152) · tier A · vehicle tracking, not basketball
- [BasketballBench (Hu et al., 2026)](https://arxiv.org/abs/2608.23435) · tier A, preprint · offline tracking pipeline
- [TrackNetV4 (Raj et al., 2024)](https://arxiv.org/abs/2409.14543) · tier A, preprint · builds on the trajectory rectification of TrackNetV3, which gained from frames before and after a gap
- Research note: `.suite/research/ball-rim-shot-detection.md`
