# Phase 02: Perception

## Goal
Detect people in each processed frame and keep temporary IDs across frames.

## Requirements
RF03, RF04, RNF02 (measured, no numeric target yet).

## Scope
- `RFDETRDetector(Detector)`: RF-DETR Nano, pretrained COCO weights, keeps only the
  `person` class, configurable threshold, device auto (CUDA if available, else CPU).
  Converts library output to `Detections`; library objects do not leave the module.
- `ByteTrackTracker(Tracker)`: ByteTrack from the `trackers` package, default params
  recorded. (Originally "supervision ByteTrack"; that class is deprecated and removed in
  supervision 0.31, so `trackers.ByteTrackTracker` is used instead, D-016.)
- Processing loop: take from `proc_queue`, detect, track, measure `t_proc_start`,
  `t_proc_end`, app delay.
- Preview: boxes, `#track_id` labels, HUD with processing FPS, app delay (ms), people
  count, drops, source state.
- `--threshold`, `--device` CLI options.

### Scope additions from BACKLOG (developer, 2026-10-08)
- `--width/--height`: request a camera resolution (default 1280x720) and print what the
  camera delivers. Removes the DroidCam letterbox (phase 01 A7).
- `--det-size`: the square side the image is resized to for detection, separate from the
  capture size. Default: the model's own resolution (384 for Nano, D-015).
- Remove `--camera-api` (DSHOW cannot open by index on opencv 5.0, phase 01 A7).
- Fix the HUD status text drawn twice (phase 01 A6).
- README setup note: one active DroidCam source; enable the virtual camera (hotkey) after
  every client restart.
- `GATES.md` step 5: close a phase with an annotated tag whose message summarises it.
- `--benchmark SECONDS`: print processing FPS, app delay p50/p95/max, drop rate, capture
  resolution and det-size. Produces the A7 baseline.
- `--no-detect`: capture only, as in phase 01 (re-running phase 01 A9/A9b at the new
  resolution without the CPU load of detection; CLI tests without model weights).

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

### Scope additions
| # | Criterion | Test |
|---|---|---|
| B1 | Camera size is requested on open and on every reopen; the delivered size is reported, not the requested one | unit with a fake `VideoCapture` |
| B2 | Bad `--det-size`, `--threshold`, `--width`, `--benchmark` values: clean argparse error | unit |
| B3 | `--camera-api` no longer exists | unit |
| B4 | Processing slower than capture: frames dropped and counted, seq in order, app delay bounded (no backlog) | unit with a fake source and a slow stub detector |
| B5 | `--benchmark` prints the baseline block; `--no-detect` runs end to end without the model | CLI test on a synthetic clip |
| B6 | HUD status drawn once, white on a dark strip, fits a 640-wide frame | unit + manual (A6) |
| B7 | Phase 01 A9/A9b still hold at 1280x720 (no letterbox) | manual |

## Traceability
| # | Test | Result |
|---|---|---|
| A1 | `tests/edge/test_perception.py::test_detector_keeps_only_persons_above_threshold`, `::test_detector_feeds_the_model_rgb_at_det_size` | see report |
| A2 | `tests/edge/test_perception.py::test_detections_shapes` (0, 1, 7) | see report |
| A3 | `tests/edge/test_perception.py::test_tracker_keeps_one_id_for_a_smoothly_moving_box`, `::test_each_person_keeps_their_own_id` (detection order swapped; one person leaves, the other keeps their ID) | see report |
| A4 | `tests/edge/test_perception.py::test_empty_frames_give_no_tracks`, `::test_empty_frames_after_tracks_give_no_tracks` | see report |
| A5 | `tests/edge/test_detector_slow.py` (`pytest -m slow`) | see report |
| A6, A7 | manual, commands in `PHASE_02_REPORT.md` | see report |
| B1 | `tests/edge/test_sources.py::test_camera_requests_size_and_reports_what_it_delivers`, `::test_camera_without_size_requests_nothing`, `::test_open_source_passes_size_to_cameras_only`, `tests/edge/test_cli.py::test_cli_prints_the_size_the_camera_delivers` | see report |
| B2, B3 | `tests/edge/test_cli.py::test_bad_phase02_flags_are_rejected` (incl. nan/inf), `::test_valid_phase02_flags_are_accepted`, `::test_defaults` | see report |
| B4 | `tests/edge/test_perception.py::test_slow_processing_drops_frames_and_keeps_app_delay_bounded`, `::test_stop_mid_stream_accounts_for_every_frame`, `::test_processed_timings_are_ordered`, `::test_detector_failure_is_an_error_event` | see report |
| B5 | `tests/edge/test_cli.py::test_benchmark_prints_the_baseline_block`, `::test_benchmark_stops_after_its_seconds`, `::test_file_runs_to_end`, `tests/edge/test_perception.py::test_capture_only_mode_counts_every_frame`, `::test_rates`, `::test_delay_stats` | see report |
| B6 | `tests/edge/test_cli.py::test_hud_status_is_one_text_pass_on_a_dark_strip`, `::test_draw_hud_every_state`, `::test_draw_tracks_labels_each_track`; manual in A6 | see report |
| B7 | manual | see report |

## Gate reviewers
`code-reviewer`, `test-auditor`, and `contract-guardian` (requested by the developer).
No file format changes in this phase.
