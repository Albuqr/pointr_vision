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
| A7 | Phone via USB (camera app) opens and previews | manual |
| A8 | Unplugging the phone shows LOST in preview and prints the event; replugging recovers or exits cleanly | manual |
| A9 | Covering the lens shows DARK | manual |

## Gate reviewers
`code-reviewer`, `test-auditor`.
