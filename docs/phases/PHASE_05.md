# Phase 05: Reports

## Goal
After a session ends, show what the system saw and what went wrong, computed only from the
session's own files.

## Requirements
RF10, RF11.

## Scope
- `reports/` module: functions that take a run folder and return a report dataclass; no
  access to live state. Writes `report.json` and prints/shows a summary screen.
- Coverage (RF10): processed vs captured frames, share of processed frames with ≥1
  detection, number of distinct track IDs, track durations (median, max), gaps (periods with
  no detection longer than a threshold), new-ID count after gaps.
- Failures (RF11): every event from `session.json` with times, drop rate, writer/recorder
  backlog, app delay p50/p95/max, longest stall.
- CLI: `python -m services.edge.report <session_id> [--run <run_id>]`. Also runs
  automatically at session end.

## Out of scope
Accuracy against ground truth (needs manual annotation, a later evaluation task), metric
positions, athlete identity.

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | Report on a hand-built run folder with known numbers returns exactly those numbers | unit |
| A2 | A run with zero detections reports 0% coverage, no crash | unit |
| A3 | Events in `session.json` all appear in the failure report | unit |
| A4 | Report generated automatically at the end of a live session | manual |

## Gate reviewers
`code-reviewer`, `test-auditor`, `contract-guardian`.

## Milestone A
After this gate, the scope's condition for starting one-person tests is met: live input,
detector, tracker and logging working, with recording, replay and reports.
