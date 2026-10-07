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

## Gate reviewers
`code-reviewer`, `test-auditor`, `contract-guardian`, `reliability-reviewer`.
