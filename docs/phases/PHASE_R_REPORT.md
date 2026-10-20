# Track R report

## R0 Contracts (branch track-r-r0-contracts)

**Status:** merged to `main` (PR #1, 2026-10-19, merge commit 5b309b3), including the review fixes (a16b7e8, a0b0d5f). Waiting for the developer to read this report and tag `track-r-R0`; the tag does not exist yet.

**What R0 delivers.** Contract 0.11.0: DATA_CONTRACTS.md sections 11 to 15 (objects, events, shots, labels, fusion), the new run.json blocks (`t0_mono`, `checks`, `clock`, `objects`, `gaps`, `outages`), `frames.csv` `t_video`, `tracks.csv` `player_number` and `id_source`, four new session event kinds, JSON Schemas and fixtures (JSON and CSV), code constants, the writer changes (`set_final`), D-041, and an amendment to ADR 0001.

**Environment.** The R0 review ran in a light Python 3.11.9 .venv (numpy, opencv, jsonschema, pytest, ruff) with no torch or supervision, so 17 end-to-end tests and tests/edge/test_perception.py could not run; this is the same set as before R0 (baseline compared by test name). Result there: 675 passed, 17 failed (baseline), 1 collection error (baseline).

**Re-run on merged `main` (2026-10-20).** At 39a1e59, in the project `.venv` (Python 3.11.9, torch 2.14.1 CPU), `python -m pytest -q`: 725 passed, 3 deselected (`slow` marker, `addopts` in `pyproject.toml`), no failures, no collection errors. This closes the "run the end-to-end tests with torch" item for R0 on CPU; the GPU PC (H2) is still untested. No CI is configured on GitHub, so this is a local result.

**Reviews (fresh context, two rounds).** Round 1: code-reviewer and contract-guardian CHANGES REQUIRED. Round 2 (after the fixes): all three CHANGES REQUIRED, with smaller findings; the second-round fixes are applied and the test-auditor's three majors are fixed (per-column enum tests, doc-driven CSV types and empty cells, the ADR-to-decision existence test). Round 3 found a blocker (the Studio read frames.csv by position and would have shown no live stats; fixed, with a test) and gap/outage definitions (fixed; `detected_t` added). The test-auditor's round-3 majors (null t0_mono test, hardened ADR test, extra negative cases) are fixed. The owner confirmed the per-group sensor file (extended to two sensors, one per rim), the gaps/outages fields and detected_t on 2026-10-19. No fourth review round was run.

**Open for the developer.**
- Confirm the per-group sensor file `sessions/sensor_<group_id>/events.csv` and the run.json `gaps`/`outages` fields (D-041; spec FR-014/FR-015).
- PC-to-rim distance (ESP-NOW assumed) and spec CR-1 are still open.
- Tag `track-r-R0` after reading this report.
- R0-A2: the "entry written before the code" half stays a review item.

## R1 Recording, replay and scoring (branch track-r-r1)

**Status:** built and tested on the branch; not merged, not reviewed, not tagged. Slice gate steps 3 and 4 are open (below).

**What R1 delivers.** (1) `FileRecorder`: raw frames to `video.mp4` on its own thread, a bounded queue that drops and counts, sha256 on stop; on by default, `--no-record` to skip (tickets 01, 02). (2) `frames.csv` `t_video` for live runs. (3) `--replay <session id | folder | .mp4/.mov>`: a new run in the session (original run untouched) or a new session from a video file; every frame processed; a changed video is refused (ticket 03). (4) `python -m services.edge.score <session>`: reads `labels.csv`, prints H1 and H3b beside their thresholds, and H3 and H4 as not scorable (ticket 04). Decisions: D-042, D-043.

**Automated.** On the branch, project `.venv` (Python 3.11.9, torch 2.14.1 CPU), `pytest -q`: 769 passed, 3 deselected, none failed. New tests: `test_recorder.py` (Phase 04 A1, A2, A5), `test_record_live.py`, `test_replay.py` (A3, A4, R1-A1, R1-A2) and `test_score.py` (R1-A3, results worked out by hand in the test). `ruff check` is clean for `services` and `tests`; `ruff check .` reports 5 E501 in `testkit/` (the suite's scaffolding, not R1).

**One real run (2026-10-20, CPU, RF-DETR Nano, the synthetic 30-frame clip).** Live: captured 30, processed 5, dropped 25, `rec_dropped` 0, video has all 30 frames. Replay of that session: captured 30, processed 30, dropped 0; `input.sha256` equals the session's `recording.sha256`. This is a synthetic clip with no people, so it shows the plumbing, not detection quality.

**Open for the developer.**
- Phase 04 A6 and R1-A4 are manual and not done: a live 5-minute session with recording (playable video, size per minute recorded), and the scoring tool against a hand calculation on one real session.
- D-043: the matching tolerance (1.0 s) and the window rules are chosen, not measured. H3 and H4 cannot be scored with the current `labels.csv`; extending it is a contract bump and your call.
- H1 is "not scorable" until slice R3 writes `shots.csv`; H3b until R5 puts numbers in `tracks.csv`. The scorer was tested on built fixtures, not on a real shot layer.
- Gate step 3 not run: `code-reviewer`, `test-auditor`, `reliability-reviewer` (and `contract-guardian`, since `recording.sha256` and `t_video` are now written) in fresh contexts.
- Recording is now on by default in Studio too: measure disk use per minute on the real setup.
- A phone that reports a wrong fps gives a wrong `t_video` scale (D-042).
