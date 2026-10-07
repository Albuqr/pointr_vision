# Phase 04: Recording and replay

## Goal
Keep the raw video of a session and re-run the pipeline on it with a different
configuration without touching the original run.

## Requirements
RF08 (video), RF09, RNF04, RNF05.

## Scope
- Recorder fed from the capture thread through `rec_queue`. Raw frames only, no annotations.
  Counts `rec_frames_dropped`. Writes `video.mp4` in the session folder; sha256 computed on
  stop and written to `session.json`.
- Recording on by default, `--no-record` to disable (see conflict C-02 in REQUIREMENTS.md).
- Frame-to-time mapping recorded so a video frame can be matched to `frames.csv` seq.
- Replay: `python -m services.edge.main --replay <session_id|path> [--threshold ...]`
  creates a new `run_id` under the session with `mode: replay` and the input sha256.
- MP4 and MOV both accepted as replay input.

## Out of scope
Encryption/locking (phase 09), upload, reports.

## Notes
- Disk use: roughly bitrate × duration. Measure the actual file size per minute on the
  real setup and record it in the report; do not quote estimates.
- Replay at file speed is useful for integration but does not validate the live camera path.

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | Recorded video frame count equals captured frames minus `rec_frames_dropped` | integration on a file source |
| A2 | Recorded frames contain no annotations (compare a frame with the source frame) | integration |
| A3 | Replay creates a new run; the original run's files are byte-identical before and after | integration |
| A4 | Replay of MP4 and MOV fixtures both succeed | integration |
| A5 | sha256 in `session.json` matches the file | unit |
| A6 | Live 5-minute session with recording: playable video, size per minute recorded | manual |

## Gate reviewers
`code-reviewer`, `test-auditor`, `contract-guardian`.
