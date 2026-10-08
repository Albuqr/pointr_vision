# Phase 02 report
Date: 2026-10-08 (automated checks and reviews). Manual sign-off: _pending_
Hardware: Dell Latitude 3410, Intel Core i7-10510U (4 cores, 15 W), 16 GB RAM, Intel UHD
Graphics, **no CUDA**: every figure in this phase is a CPU figure (D-015). Phone: Samsung S22
(SM-S901E), DroidCam phone app + DroidCam Client (free tier, watermark burned in).
Package versions (working repo `.venv`): Python 3.11.9, numpy 2.4.6, opencv-python 5.0.0.93,
torch 2.14.1+cpu (4 threads), torchvision 0.29.1+cpu, rfdetr 1.11.2, supervision 0.30.8,
trackers 2.6.1, transformers 5.19.0, pytest 9.1.1, ruff 0.16.10, setuptools 78.1.0. The CLI
prints the perception versions, device, det-size, threshold, tracker params and torch thread
count at startup.

## Traceability
| # | Criterion | Test | Result |
|---|---|---|---|
| A1 | Detector returns only `person` detections, all above threshold | `tests/edge/test_perception.py::test_detector_keeps_only_persons_above_threshold`, `::test_detector_feeds_the_model_rgb_at_det_size` | Pass |
| A2 | Detections shapes for 0, 1 and many | `tests/edge/test_perception.py::test_detections_shapes[0,1,7]` | Pass |
| A3 | Same ID for a smoothly moving box | `tests/edge/test_perception.py::test_tracker_keeps_one_id_for_a_smoothly_moving_box`, `::test_each_person_keeps_their_own_id` (detection order swapped; one person leaves, the other keeps their ID) (real `trackers` library, synthetic detections) | Pass |
| A4 | Empty frames give zero tracks without errors | `tests/edge/test_perception.py::test_empty_frames_give_no_tracks`, `::test_empty_frames_after_tracks_give_no_tracks` | Pass |
| A5 | Real model on still images with a known number of people | `tests/edge/test_detector_slow.py` (`pytest -m slow`): Apollo 11 crew (3) and an empty building exterior (0), tolerance 0 | Pass |
| A6 | Live: boxes and IDs on the developer moving in frame | manual | _pending_ |
| A7 | Baseline: processing FPS and app delay p50/p95 over 2 minutes, phone via USB | manual (`--benchmark 120`) | _pending_ |
| B1 | Camera size requested on open and reopen; delivered size reported | `tests/edge/test_sources.py::test_camera_requests_size_and_reports_what_it_delivers`, `::test_camera_without_size_requests_nothing`, `::test_open_source_passes_size_to_cameras_only`, `tests/edge/test_cli.py::test_cli_prints_the_size_the_camera_delivers` | Pass |
| B2 | Bad `--det-size`, `--threshold`, `--width`, `--benchmark`: clean error | `tests/edge/test_cli.py::test_bad_phase02_flags_are_rejected` (incl. nan/inf), `::test_valid_phase02_flags_are_accepted`, `::test_defaults` | Pass |
| B3 | `--camera-api` removed | `tests/edge/test_cli.py::test_bad_phase02_flags_are_rejected[...camera-api...]` | Pass |
| B4 | Slow processing: drops counted, seq in order, app delay bounded | `tests/edge/test_perception.py::test_slow_processing_drops_frames_and_keeps_app_delay_bounded`, `::test_stop_mid_stream_accounts_for_every_frame`, `::test_processed_timings_are_ordered`, `::test_detector_failure_is_an_error_event` | Pass |
| B5 | `--benchmark` block; `--no-detect` end to end | `tests/edge/test_cli.py::test_benchmark_prints_the_baseline_block`, `::test_benchmark_stops_after_its_seconds`, `::test_file_runs_to_end`, `tests/edge/test_perception.py::test_capture_only_mode_counts_every_frame`, `::test_rates`, `::test_delay_stats` | Pass |
| B6 | HUD drawn once, fits 640 wide | `tests/edge/test_cli.py::test_hud_status_is_one_text_pass_on_a_dark_strip`, `::test_draw_hud_every_state`, `::test_draw_tracks_labels_each_track`; visual check in A6 | Pass (auto); manual _pending_ |
| B7 | Phase 01 A9/A9b hold at 1280x720 | manual | _pending_ |

## Automated checks
In the working repo `.venv`, at commit `3f9ff39` (after the gate fixes):
- `ruff check .`: all checks passed.
- `ruff format --check .`: 68 files already formatted.
- `pytest -q`: 209 passed, 3 deselected (the `slow` tests). The 171 phase 00/01 tests still
  pass. `tests/conftest.py` fails any default test that imports `rfdetr`, so the default
  run needs no camera, network or model weights.
- `pytest -q -m slow`: 3 passed (A5 and the D-015 config check), CPU, cached weights. The
  first run needs the network: it downloads the weights (366 MB) and the two images
  (`tests/fixtures/README.md`; SHA-1 checked, gitignored). Detections at threshold 0.5
  (measured 2026-10-08, before the strict `>` change, which does not affect these values):
  Apollo 11 crew, 3 people, confidences 0.957, 0.924, 0.922; building exterior, 0 people
  (also 0 at threshold 0.05). The colour order is proven by the stub test against the API in
  D-015; three large people would likely be found in BGR too.
- Import time, measured once during verification: importing `rfdetr`, `supervision` and
  `trackers` took 10.5 s. In a CLI run on a synthetic clip the model load (import + weights)
  printed 14.0 s and the warm-up 469 ms. These are setup costs before capture starts, not
  part of any per-frame figure.
- Clean install: a fresh clone at `3804031`, a new venv, and the README commands give
  `torch 2.14.1+cpu`, `torch.cuda.is_available() == False`, 171 passed.
- Install footprint: `.venv` 236 MB → 1363 MB; model weights `rf-detr-nano.pth` 366 MB in
  `~/.roboflow/models` (D-016).

## Manual tests
Setup, in Git Bash at the repo root, phone connected the way the row says (DroidCam: one
active source only, virtual camera enabled with the hotkey, see README):
```bash
source .venv/Scripts/activate
```
Every run prints `source: ...`, `requested 1280x720, camera delivers WxH`, `health: ...`,
`perception: ...` (device, det-size, threshold, model load and warm-up time) and `tracker:
...`, then events as they happen and a summary line on exit (`captured`, `dropped`,
`failed_reads`, `processed`, `unprocessed`, `events`). Check `captured = processed + dropped
+ unprocessed` and `unprocessed=0`. Copy the console output into the Notes. The model loads
(several seconds) before the camera opens.

**Before the benchmark runs (A7 and the matrix):** notebook on AC power, Windows power mode
"Best performance", no other heavy programs open, preview off (it competes for the CPU).
Point the phone at the same scene each time, with you in it, moving normally. The 15 W CPU
throttles with heat, so wait a minute between runs and keep the order below.

| Test | Command | What to do / pass condition |
|---|---|---|
| A6 | `python -m services.edge.main --source 1 --link usb --preview` | Walk across the frame, stop, turn, leave and come back. Pass: a box with a `#id` label follows you; the ID stays the same while you stay in view (a new ID after you leave and come back is expected). HUD: two lines, white on black, no doubled text (B6); `people` and `tracks` counts shown. Note how choppy the image is (it updates at processing FPS, D-017) and whether `people` > `tracks` happens for long (D-016 threshold gap) |
| A7 | `python -m services.edge.main --source 1 --link usb --benchmark 120` | Baseline. Copy the three `benchmark:` lines. This is the input for Q-02 |
| B7 (A9 again) | `python -m services.edge.main --source 1 --link usb --preview --no-detect` | Check `camera delivers` first: if it is still 640x480, the letterbox remains and B7 is not meaningful; record that. Otherwise cover the lens fully. Pass: DARK banner and a `dark_frames` line within about 1 s; uncover: OK. Record the brightness in the event line |
| B7 (A9b again) | `python -m services.edge.main --source 1 --link usb --preview --no-detect` | Phone on a stand, still empty scene, normal light, untouched for 60 s. Pass: no FROZEN banner and no `frozen_frames` line. If FROZEN appears, record the `mean abs diff` value and retry with `--frozen-diff 0.2` |

### Benchmark matrix
2 minutes each, headless. `small` = `--det-size 320` (0.69x the pixels of 384); `default` =
no `--det-size` (the model's 384, D-015). Run in this order:

| Run | Link | det-size | Command |
|---|---|---|---|
| M1 | USB | default | `python -m services.edge.main --source 1 --link usb --benchmark 120` (this is A7) |
| M2 | USB | small | `python -m services.edge.main --source 1 --link usb --benchmark 120 --det-size 320` |
| M3 | Wi-Fi | default | `python -m services.edge.main --source 1 --link wifi --benchmark 120` |
| M4 | Wi-Fi | small | `python -m services.edge.main --source 1 --link wifi --benchmark 120 --det-size 320` |

Switching USB ↔ Wi-Fi: change the source in the DroidCam client and hide the other one (one
active source), then check the `camera delivers` line.

### Results
| Test | Link | Result | Notes |
|---|---|---|---|
| A6 | USB | | |
| A7 | USB | | |
| B6 (visual) | USB | | |
| B7 (A9) | | | |
| B7 (A9b) | | | |

## Measurements
Phase 02 writes no files, so there is no `run_id`; the figures come from the `benchmark:`
lines of each run.

| Run | Link | Frames (delivered) | det-size | Captured | Processed | Proc FPS | Dropped (% of captured) | App delay p50 / p95 / max (ms) |
|---|---|---|---|---|---|---|---|---|
| M1 (A7) | USB | | 384 | | | | | |
| M2 | USB | | 320 | | | | | |
| M3 | Wi-Fi | | 384 | | | | | |
| M4 | Wi-Fi | | 320 | | | | | |

App delay is frame received to processing done (`t_proc_end − t_recv`), including the time
the frame waited in `proc_queue`. It is not camera-to-screen latency.

## Reviewer outcomes
| Reviewer | Result | Findings fixed |
|---|---|---|
| `code-reviewer` | PASS; re-review after the fixes PASS | No BLOCKER or MAJOR. **MINOR fixed (D-018):** shutdown did not drain `proc_queue`; source opened before the slow model load (stale stream frames); `nan`/`inf` accepted by float flags; second Ctrl+C during shutdown; `processor.stop()` result ignored; preview coupled to `Processor`; benchmark reading non-Protocol detector attributes; an unmeasured import figure in D-016. Re-review MINORs fixed: no 10 s processor wait when capture did not stop; `source.close()` guarded; a Ctrl+C inside `capture.stop()` no longer reported as a timeout; D-018 invariant wording. **MINOR to BACKLOG:** size change after a reopen; `delays_ms` growth |
| `test-auditor` | CHANGES REQUIRED → PASS after one fix round | **MAJOR:** the A3 tests passed with an adapter numbering tracks by list position. Fix: one person leaves while the other must keep their ID (the first fix attempt, swapping detection order, still passed the mutation: the library returns tracks in track order). Re-audit killed three variants of the mutation. **MINOR fixed:** benchmark stop-after-SECONDS and the FPS/drop-rate formulas (`rates()`) tested; label pixels and label ID tested; valid B2 values tested; CLI "camera delivers" line tested. A5's first-run network need is documented above. Re-audit: no flakiness in 90 + 60 runs under load |
| `contract-guardian` | CHANGES REQUIRED → PASS after one fix round | **MAJOR:** a mid-stream stop left the queued frame neither processed nor counted (`captured = processed + dropped + 1`), rule 6. Fix: drain at shutdown, `unprocessed` counter (D-018); re-review stress check 394 random stops, invariant held. **MINOR fixed:** model-load failure tested; `> threshold` as in the contract. **MINOR to BACKLOG (03):** run.json example `package`, `runtime.device` normalisation, `dropped_total` snapshot, `unprocessed` in run.json counts, processing-timeout shortfall in data |

## Decisions taken in this phase
- D-015: API verification of rfdetr 1.11.2, supervision 0.30.8, trackers 2.6.1 and the torch
  CPU wheel, from the wheel sources, re-checked after install. No GPU.
- D-016: pinned dependencies and licences; ByteTrack from `trackers` (supervision's is
  deprecated), timestamp mode, defaults recorded; install footprint.
- D-017: perception design. Processing thread, preview of processed frames, `--det-size` via
  `predict(shape=)`, warm-up, capture size request, `--camera-api` removed, HUD fix,
  `--no-detect`, `--benchmark`.
- D-018: gate fixes. Shutdown drains `proc_queue` (counts add up), the model loads before the
  source opens, strict `> threshold`, shutdown Ctrl+C guards; corrects D-016's import figure.

## Known limitations carried forward
- All inference is on the CPU. No accelerator (ONNX, OpenVINO, TorchScript) is used; if the
  A7 baseline is too slow, that is a separate, approved step (BACKLOG). Q-02 stays open.
- The preview image updates at processing FPS (D-017); live frames with lagging boxes are in
  BACKLOG.
- Detector threshold 0.5 vs ByteTrack activation 0.7: people scored 0.5-0.7 are counted but
  not tracked (D-016, BACKLOG).
- `TrackObs.state` is always empty: the tracker exposes no observed/predicted state.
- `run.json` has no field yet for det-size and the requested capture size (BACKLOG, 03).
- Nothing is persisted; phase 03.
