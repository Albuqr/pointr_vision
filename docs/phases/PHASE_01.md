# Phase 01: Capture

## Goal
Open any supported source, keep reading frames in real time without backlog, and detect
when the source stops delivering usable images.

## Requirements
RF01 (partial), RF02, RNF01 (resolution recorded, not enforced yet).

## Scope
- `FrameSource` implementations: `CameraSource` (index), `StreamSource` (URL),
  `FileSource` (path, MP4 and MOV). One factory: `open_source(ref) -> FrameSource`.
- Capture thread with `proc_queue(maxsize=1)`: drop oldest when full, count drops.
- `SourceHealth` monitor emitting events:
  - `source_lost`: N consecutive failed reads (N configurable, default 30)
  - `source_recovered`
  - `frozen_frames`: consecutive frames nearly identical (mean abs diff below a threshold)
    for longer than T seconds
  - `dark_frames`: mean brightness below a threshold for longer than T seconds
  - `source_open_failed`: with the reason
- Preview window: live image, source state banner (OK / LOST / FROZEN / DARK), capture FPS,
  drop count. Closes on q.
- CLI: `python -m services.edge.main --source <ref> [--preview]`.

## Out of scope
Detection, tracking, writing files (events print to console only in this phase).

## Notes
- With an existing phone camera app, the notebook sees a webcam index or a URL. It cannot
  ask the phone whether it has a camera. RF01's device check belongs to phase 13; here RF01
  is covered by "source opens and delivers frames, or the user is told why not".
- Thresholds for frozen/dark are configurable and recorded; tune them on real footage and
  note the values in DECISIONS.md.

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | File source reads every frame of a fixture in order, seq strictly increasing | unit |
| A2 | When consumer is slower than producer, queue never exceeds 1 and drops are counted | unit with a slow fake consumer |
| A3 | Black fixture → `dark_frames` event; frozen fixture → `frozen_frames` event; normal fixture → none | unit |
| A4 | Source that stops returning frames → `source_lost`; resumes → `source_recovered` | unit with a fake source |
| A5 | Invalid source ref → clear error message, non-zero exit, no traceback dump | unit |
| A6 | Laptop webcam opens and previews | manual |
| A7 | Phone over **Wi-Fi** (DroidCam, webcam index) opens and previews | manual |
| A8 | Wi-Fi: turning off Wi-Fi on the phone shows LOST or FROZEN in the preview and prints `source_lost` or `frozen_frames`; turning it back on recovers or exits cleanly. Repeated over **USB**: unplugging the cable, then replugging. The report records which state each link produced | manual |
| A9 | Covering the lens shows DARK | manual |
| A9b | A still, empty scene over the phone for 60 s does **not** show FROZEN. If it does, `frozen_diff` is too loose; record it in the report | manual |

### Notes on the manual tests
- A8 accepts LOST or FROZEN (D-010): when the phone drops, the DroidCam client keeps its
  virtual webcam open and may send a still placeholder, which reads as frozen, not lost.
  The FROZEN banner says "image frozen, check camera connection" for that reason.
- A9b checks the frozen threshold against real sensor noise. Threshold values that need
  changing go in DECISIONS.md (D-013 holds the initial ones).

## Traceability
| # | Test |
|---|---|
| A1 | `tests/edge/test_sources.py::test_file_reads_every_frame_in_order` |
| A2 | `tests/edge/test_capture.py::test_never_blocks_and_keeps_newest`, `::test_slow_consumer_accounting` |
| A3 | `tests/edge/test_health.py::test_fixture_events` (black, frozen, moving) |
| A4 | `tests/edge/test_health.py::test_lost_then_recovered`, `tests/edge/test_capture.py::test_fake_source_lost_and_recovered` |
| A5 | `tests/edge/test_cli.py::test_bad_ref_exits_cleanly` |
| A6-A9b | manual, commands in `PHASE_01_REPORT.md` |

## Gate reviewers
`code-reviewer`, `test-auditor`, `contract-guardian` (contract 0.3.0, D-012).
