# Phase 02: Perception

## Goal
Detect people in each processed frame and keep temporary IDs across frames.

## Requirements
RF03, RF04, RNF02 (measured, no numeric target yet).

## Scope
- `RFDETRDetector(Detector)`: RF-DETR Nano, pretrained COCO weights, keeps only the
  `person` class, configurable threshold, device auto (CUDA if available, else CPU).
  Converts library output to `Detections`; library objects do not leave the module.
- `ByteTrackTracker(Tracker)`: supervision ByteTrack, default params recorded.
- Processing loop: take from `proc_queue`, detect, track, measure `t_proc_start`,
  `t_proc_end`, app delay.
- Preview: boxes, `#track_id` labels, HUD with processing FPS, app delay (ms), people
  count, drops, source state.
- `--threshold`, `--device` CLI options.

## Out of scope
Writing files (phase 03), recording, reports, pose, athlete identity.

## Before coding
- Verify the `rfdetr` and `supervision` APIs against the installed versions: model class
  name, predict signature and input colour order, class-id mapping for `person`, ByteTrack
  update method. Write what you found in DECISIONS.md.
- Check whether a CUDA-capable GPU exists. If not, record that the baseline is CPU.

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | Detector returns only `person` detections, all above threshold | unit with a stub model returning mixed classes |
| A2 | Detections dataclass has correct shapes for 0, 1 and many detections | unit |
| A3 | Tracker keeps the same ID for a box moving smoothly across synthetic frames | unit with synthetic detections |
| A4 | Empty frames produce zero tracks without errors | unit |
| A5 | Real model smoke test: a still image with a known number of people returns that many (± documented tolerance) | integration, marked `slow`, image is the developer's own or a licensed sample |
| A6 | Live: boxes and IDs on the developer moving in frame | manual |
| A7 | Baseline recorded: processing FPS and app delay p50/p95 over 2 minutes, phone via USB | manual, in report |

## Gate reviewers
`code-reviewer`, `test-auditor`.
