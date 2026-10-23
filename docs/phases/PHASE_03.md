# Phase 03: Session and logging

## Goal
Every run produces a complete, readable record on disk, including what went wrong, and
survives a crash with partial data intact.

## Requirements
RF06, RF07, RF08 (frame data), RNF03, partial RNF02.

## Scope
- Session lifecycle: start on launch (or explicit start key), end on q, Ctrl+C, source end
  or exception. One shutdown path.
- Writer thread with bounded `write_queue`; owns all file handles; flushes at least once per
  second; logs `writer_backlog` events if the queue fills.
- Files per `DATA_CONTRACTS.md`: `session.json`, `runs/<run_id>/run.json`, `frames.csv`,
  `tracks.csv`. Rows for zero-detection frames. Events from phase 01 into `session.json`.
- Versions of Python, rfdetr, supervision, opencv, device and all thresholds in `run.json`.
- Status `ended`, `interrupted` or `error` written in a `finally` block.
- No network, no database, no recorded video required.

## Out of scope
Video recording, replay, reports, SQLite.

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | Running on a fixture clip produces all files, valid against the schemas | integration |
| A2 | `frames.csv` has one row per processed frame, including frames with 0 detections; seq increasing | integration |
| A3 | Killing the process mid-run (simulated exception) leaves readable CSVs and `session.json` with status `error` | integration |
| A4 | Ctrl+C → status `interrupted`, end time written | integration (send SIGINT / KeyboardInterrupt) |
| A5 | Two runs never write to the same folder | unit |
| A6 | Run with network disabled completes normally (weights cached) | manual |
| A7 | **Soak:** 10 minutes live from the phone: app delay does not trend upward, drop rate stable, clean shutdown | manual, plot app_delay_ms over time in the report |

## Scope addition (D-044, 2026-10-22)

From the 2026-10-22 field test (`.scratch/pointr-vision/field-test-2026-10-22.md`). A bounded
scope exception, like D-025. Items marked **contract** need `DATA_CONTRACTS.md` updated and
the version bumped before code. Items that overlap Track R or phase 11 must build on that
work, not duplicate it.

### Session and logging
- Stopping from Studio ends each camera's session as a normal end, not `interrupted` /
  `Ctrl+C`. **contract**
- Audit trail: every Studio action (camera add, edit, test, start, stop, calibration save)
  and every error is recorded with time and outcome, so a session can be rebuilt from its
  files. **contract**
- Error handling: expected failures (for example a preview client disconnecting) are logged
  as one readable line or event, never a raw traceback. Every failure has a reason.
- Session control: Studio shows each camera's state (starting, loading model, waiting for
  first frame, recording, preview ready, stopping, ended).
- Per-camera ready times logged: model loaded, first frame, first preview frame.
  **contract**
- Power state (on AC or battery, charge) recorded in `run.json`. **contract**

### Sessions page and camera connection
- The sessions page shows each session in readable form (when, cameras, duration, fps,
  drops, events, status), not the raw report text.
- Camera connection and testing based on the network the notebook is on: find or suggest
  the cameras' addresses instead of typing every URL.
- Camera 2's preview appears without the multi-minute wait seen on 2026-10-22.

### Live performance
- Find the cause of the ~10 fps per-camera cap with runs L1–L8 before changing code.
- Then, depending on the result: lower camera resolution, hardware or faster video encoding
  (`.mp4` would be a **contract** change), fewer preview frames, cameras started in
  parallel, one shared model, tracker frame rate set from the real input rate.

### Tracking and calibration
- Fewer ID changes when a person walks behind another (re-identification after occlusion).
- The same person gets the same ID across cameras (builds on Track R two-camera fusion).
- Per-camera calibration that uses only the court points that camera can see, not the
  full court. **contract**

### Acceptance (scope addition)
| # | Criterion | Test |
|---|---|---|
| B1 | A Studio stop writes a normal end status and a stop event naming the UI as the source | integration |
| B2 | Each Studio action listed above writes one audit entry with time and outcome | integration |
| B3 | A preview client disconnecting writes no traceback and the session continues | integration |
| B4 | Studio status reports each camera's state through start, record and stop | integration |
| B5 | Model-loaded, first-frame and first-preview-frame times are in the session files | integration |
| B6 | `run.json` holds the power state | unit |
| B7 | The sessions page lists each session's time, cameras, duration, fps, drops, events and status | e2e (Playwright) |
| B8 | Camera discovery finds a DroidCam stream on the current network | manual |
| B9 | Runs L1–L8 recorded, cause of the cap named, chosen fix measured against L1 | manual, in the phase report |
| B10 | ID changes per person on a recorded occlusion clip go down against the current tracker | integration on a recorded clip, plus manual check |
| B11 | One person seen by both cameras has one ID in the fused output | integration (Track R fixtures) |
| B12 | A calibration fitted from a visible subset of court points saves, and check points report their error | unit + manual |

## Gate reviewers
`code-reviewer`, `test-auditor`, `contract-guardian`, `reliability-reviewer`.
