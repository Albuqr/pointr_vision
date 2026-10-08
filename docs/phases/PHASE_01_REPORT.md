# Phase 01 report
Date: 2026-10-08 (automated checks and reviews). Manual sign-off: _pending_
Hardware: _to fill: notebook model, CPU/GPU, phone model, connection (USB/Wi-Fi), camera app + version (DroidCam phone app and PC client; IP Webcam if used)_
Package versions (working repo `.venv`): Python 3.11.9, numpy 2.4.6, opencv-python 5.0.0.93
(`cv2.__version__` 5.0.0), jsonschema 4.26.0, pytest 9.1.1, ruff 0.16.10, setuptools 65.5.0
(build only). The CLI prints the Python/OpenCV/numpy versions at startup.

## Traceability
| # | Criterion | Test | Result |
|---|---|---|---|
| A1 | File source reads every frame of a fixture in order, seq strictly increasing | `tests/edge/test_sources.py::test_file_reads_every_frame_in_order` (MP4 and MOV) | Pass |
| A2 | Slower consumer: queue never above 1, drops counted | `tests/edge/test_capture.py::test_never_blocks_and_keeps_newest`, `::test_slow_consumer_accounting`, `::test_put_race_is_not_counted_as_a_drop` | Pass |
| A3 | Black → `dark_frames`; frozen → `frozen_frames`; normal → none | `tests/edge/test_health.py::test_fixture_events` | Pass |
| A4 | Source stops → `source_lost`; resumes → `source_recovered` | `tests/edge/test_health.py::test_lost_then_recovered`, `::test_lost_after_lost_secs_with_few_slow_reads`, `::test_lost_secs_counts_from_the_last_good_frame`, `tests/edge/test_capture.py::test_fake_source_lost_and_recovered` | Pass |
| A5 | Invalid ref → clear message, non-zero exit, no traceback | `tests/edge/test_cli.py::test_bad_ref_exits_cleanly`, `::test_cv2_error_on_open_exits_cleanly` | Pass |
| A6 | Laptop webcam opens and previews | manual | Pass |
| A7 | Phone over Wi-Fi (DroidCam) opens and previews | manual | _pending_ |
| A8 | Wi-Fi off / cable unplugged → LOST or FROZEN + event; back → recovers or exits cleanly (Wi-Fi and USB) | manual | _pending_ |
| A9 | Covering the lens shows DARK | manual | _pending_ |
| A9b | Still, empty scene for 60 s over the phone does not show FROZEN | manual | _pending_ |

Supporting tests (no criterion of their own):
- The reopen path of camera and stream sources: `test_live_source_reopens_after_failures`.
- Frozen clearing and firing again: `test_frozen_clears_and_fires_again`.
- No frozen comparison across a gap: `test_no_frozen_comparison_across_a_gap`.
- Banner priority: `test_lost_has_priority_over_dark`.
- File pacing: `test_file_realtime_is_paced_to_its_fps`.
- HUD: `test_draw_hud_every_state`, `test_banner_colours_differ`.
- Threshold validation: `test_thresholds_must_be_positive`.
- Every emitted event kind is in the contract: `tests/test_contracts.py::test_emitted_event_kinds_are_in_contract`.

## Automated checks
In the working repo `.venv`, at commit `010e1aa`:
- `ruff check .`: all checks passed.
- `ruff format --check .`: 59 files already formatted.
- `pytest -q`: 171 passed.
  - Tests in the phase 00 files (`test_contracts.py`, `test_fixtures.py`, `test_interfaces.py`): 124 passed, i.e. the 114 original tests plus 10 new cases in `test_contracts.py` (60 → 70): 5 `source.link` values, 1 `source_open_failed` with null `t_mono`, 3 broken `link` values, 1 emitted-kinds check.
  - `tests/edge`: 47 passed.
- No test needs a camera, a phone or a network. Sources are the synthetic clips from `tests/fixtures/make_clips.py` (now also `moving.mov`), a scripted fake source, or a fake `VideoCapture`.

## Manual tests
Setup, in Git Bash at the repo root:
```bash
source .venv/Scripts/activate
```
Every run prints `source: ...` (with resolution, reported fps and link), `health: ...` (the
thresholds in use), each event as it happens, and a summary line on exit. Press `q` in the
preview window (or Ctrl+C in the terminal) to stop. Copy the console output into the Notes.

**Which webcam index?** The laptop webcam is usually `0` and DroidCam usually `1`. If DroidCam
does not open on `1`, try `2`. If it still does not open, add `--camera-api dshow` (DroidCam's
virtual webcam may be visible only to DirectShow); use the same flag in every DroidCam
command below.

**DroidCam links.** On Wi-Fi, the phone and the notebook are on the same network, and the
DroidCam PC client is connected over Wi-Fi with the phone's IP. On USB, the cable is plugged
in, USB debugging is on, and the PC client is connected in USB mode. Start the client first,
then the command.

| Test | Link | Command | What to do / pass condition |
|---|---|---|---|
| A6 | builtin | `python -m services.edge.main --source 0 --link builtin --preview` | Preview shows the webcam image, banner OK, capture fps and `dropped` on screen |
| A7 | Wi-Fi | `python -m services.edge.main --source 1 --link wifi --preview` | Preview shows the phone image, banner OK |
| A8 (Wi-Fi) | Wi-Fi | `python -m services.edge.main --source 1 --link wifi --preview` | With the preview running, turn **off Wi-Fi on the phone**. Pass: the banner leaves OK (LOST or FROZEN) and the console prints `source_lost` or `frozen_frames`. Turn Wi-Fi back on and reconnect the DroidCam client if it needs it. Pass: OK again (`source_recovered` if it was LOST), or `q` exits cleanly with the summary line. Record which state appeared |
| A8 (USB) | USB | `python -m services.edge.main --source 1 --link usb --preview` | Same as above, but **unplug the USB cable**, then replug. Record which state appeared |
| A8 (IP Webcam, optional) | Wi-Fi | `python -m services.edge.main --source http://<phone-ip>:8080/video --link wifi --preview` | Exercises `StreamSource`. Turn off Wi-Fi on the phone: expect LOST (a stream read times out). Note the time between Wi-Fi off and the `source_lost` line (D-014 records no figure yet) |
| A9 | Wi-Fi or USB | `python -m services.edge.main --source 1 --link wifi --preview` (or `--link usb`) | Cover the lens fully. Pass: DARK banner and a `dark_frames` line within about `dark_secs` (1.0 s). Uncover: banner back to OK |
| A9b | Wi-Fi or USB | `python -m services.edge.main --source 1 --link wifi --preview` (or `--link usb`) | Phone on a stand, pointed at a still, empty scene with normal lighting, untouched for 60 s. Pass: no FROZEN banner and no `frozen_frames` line. If FROZEN appears, the `frozen_diff` default (0.5) is too loose: record the `mean abs diff` value from the event line and retry with e.g. `--frozen-diff 0.2` |

Threshold flags, all must be > 0: `--lost-reads`, `--lost-secs`, `--frozen-diff`,
`--frozen-secs`, `--dark-level`, `--dark-secs`. If any value is changed to pass a test, record
it here; it then goes into DECISIONS.md as the tuned value (D-013 holds the initial ones).

| Test | Link | Result | State seen (A8) | Notes |
|---|---|---|---|---|
| A6 | builtin | PASS | n/a | index 0, 640x480 (OpenCV default, not requested), banner OK, ~30 fps, 1886 captured / 19 dropped (~1%) in ~63 s, 0 failed reads, no events, clean exit on q. HUD text overlap noted (BACKLOG) |
| A7 | Wi-Fi | | | |
| A8 | Wi-Fi | | | |
| A8 | USB | | | |
| A8 | IP Webcam (optional) | | | |
| A9 | | | | |
| A9b | | | | |

## Measurements
Phase 01 writes no files, so there is no `run_id`. Fill these from the preview HUD and the
console summary line during the manual runs:

| Link | Resolution / reported fps (from `source:` line) | Capture fps (HUD) | dropped (summary) | Notes |
|---|---|---|---|---|
| builtin | 640x480 (OpenCV default, not requested; BACKLOG: --width/--height) | ~30 | 19 of 1886 captured (~1%), ~63 s, preview on | A6 run; 0 failed reads |
| DroidCam Wi-Fi | | | | |
| DroidCam USB | | | | |

There is no perception yet (phase 02), so the only consumer is the headless loop or the
preview. In the A6 preview run, the preview loop dropped 19 of 1886 frames (~1%).

## Reviewer outcomes
| Reviewer | Result | Findings fixed |
|---|---|---|
| `code-reviewer` | PASS after one fix round | **MAJOR:** a stalled `StreamSource` took about 150 s to reach `source_lost`, because lost was counted only in failed reads and each stream read or reopen blocks. Fix: `lost_secs` time bound (D-014), counted from the last good frame. Re-review confirmed it on a blocking-fake simulation. **MINOR fixed:** stop timeout (8 s) longer than the slowest stream read; fps cleared while failing; `SourceEnded`/`utc_now` moved to `types.py` and documented in the Protocol and ARCH §4; Ctrl+C and main-loop exceptions become `interrupted`/`error` events (exit 130/1); Ctrl+C during open handled; the preview owns `destroyAllWindows`; `open()` releases a previous capture; re-review MINORs: D-014's wrong "about 7 s" estimate corrected, second Ctrl+C during shutdown keeps the summary, `on_event` locked, threshold flags must be > 0. **MINOR to BACKLOG:** phase 03 event routing through the writer queue |
| `test-auditor` | PASS | No BLOCKER or MAJOR. **MINOR fixed:** tests for the reopen path, frozen clearing back to OK, no comparison across a gap, LOST > DARK priority, the put race, the `cv2.error` open branch, distinct banners, a MOV fixture (closes the phase 04 BACKLOG row); deadlines instead of fixed sleeps in two capture tests |
| `contract-guardian` | PASS after one fix round | **MAJOR:** `source_open_failed` precedes any run's `t0`, but the contract did not say that `t_mono` is then `null`, and `HealthEvent.t_mono` could not be `None`. Fix: a sentence in DATA_CONTRACTS §2, `t_mono: float \| None`, `None` passed on open failure (D-014; still 0.3.0, never released). **MINOR fixed:** the null-in-enum exemption limited to `source.link`; a test that every emitted kind is in the contract; Ctrl+C is an `interrupted` event; the test asserts `t_mono is None` on the event itself. **MINOR to BACKLOG:** `link`/`kind` consistency; stream credentials in `source.ref` |

Both MAJOR fixes were re-reviewed by the same reviewer: PASS.

## Decisions taken in this phase
- D-010: phone over Wi-Fi or USB; DroidCam primary (webcam index), IP Webcam through `StreamSource`, laptop webcam as dev fallback. Closes Q-08.
- D-011: `t0 = time.monotonic()` when a run's capture thread starts; one t0 per run. Closes Q-11.
- D-012: contract 0.2.0 → 0.3.0. `source_open_failed` event kind, `session.json` `source.link`, t0 per run.
- D-013: capture design. `SourceEnded` at the end of a file, seq per read attempt, reconnect inside the source, drop-oldest queue, dark resets frozen, initial untuned thresholds.
- D-014: gate fixes. `source_lost` is time-bounded (`lost_secs`), `t_mono` is null before t0, the shutdown path, `SourceEnded` in `types.py`.

## Known limitations carried forward
- Thresholds are initial values, not tuned on real footage (D-013). A9b and A8 give the first real data.
- No stream loss time is measured; D-014 states the mechanism only.
- The notebook cannot detect USB vs Wi-Fi; `--link` is declared by the user and not checked against `kind` (BACKLOG).
- Nothing is persisted. Events, resolution and versions print to the console. `session.json` (with `source.link`, t0's wall anchor and thresholds) is phase 03 (BACKLOG).
- The DroidCam backend (`--camera-api any` vs `dshow`) is not verified on this hardware yet.
