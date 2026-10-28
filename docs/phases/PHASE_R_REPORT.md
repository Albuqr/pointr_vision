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

**Status:** merged to `main` (PR #4, merge commit b8e2722) after gate step 3 ran twice (round 2 below). Not tagged. Manual acceptance is open (below).

**What R1 delivers.** (1) `FileRecorder`: raw frames to `video.mkv` on its own thread, a bounded queue that drops and counts, sha256 on stop; on by default, `--no-record` to skip (tickets 01, 02). (2) `frames.csv` `t_video` for live runs. (3) `--replay <session id | folder | .mp4/.mov>`: a new run in the session (original run untouched) or a new session from a video file; every frame processed; a changed video is refused (ticket 03). (4) `python -m services.edge.score <session>`: reads `labels.csv`, prints H1 and H3b beside their thresholds, and H3 and H4 as not scorable (ticket 04). Decisions: D-042, D-043.

**Automated.** On the branch, project `.venv` (Python 3.11.9, torch 2.14.1 CPU), `pytest -q`: 811 passed, 3 deselected, none failed. `ruff check` is clean for `services` and `tests`; `ruff check .` reports 5 E501 in `testkit/` (the suite's scaffolding, not R1).

**Reviews (2026-10-20, fresh contexts, round 1): all four CHANGES REQUIRED.** `reliability-reviewer`: 1 BLOCKER, 4 MAJOR. `test-auditor`: 5 MAJOR. `contract-guardian`: 1 MAJOR. `code-reviewer`: 3 MAJOR. Fixed, each with a test that fails without the fix:
- **BLOCKER: a killed session left an unreadable video.** OpenCV's MP4 has no index until closed. Measured: after a kill, MP4 and MOV give 0 readable frames, MKV and AVI stay readable; the FFmpeg fragmented-MP4 option has no effect through OpenCV. The recording is now `video.mkv` (D-042; a change from the `video.mp4` of Phase 04, flagged for the owner). Test: kill a recording process and read the video back (114 of 120 frames; the same test on an MP4 path reads 0).
- `recorder.stop()` was unbounded and unguarded: it now waits at most 10 s, and a failure there is an `error` event and never skips the final `session.json` write.
- `t_video` claimed frames that were not in the video (a failed writer, a frame of another size that OpenCV skips silently): only written frames have a time; the rest are counted as dropped.
- An interrupted or failed replay looked complete: it now adds an `interrupted` or `error` event tagged `replay <run_id>:` to `session.json`; the scorer warns when the labels run past the run's frames.
- Two replays of one session lost a run id: the session file is re-read and merged on each write, and temp file names carry the process id (a read-merge-write, not a lock).
- H3b read the tracker's temporary id, so a correct identity layer would have scored about 0%: it now reads the player's number (D-043).
- Missing interface and contract text: `SessionWriter.start_run` is in the Protocol, ARCHITECTURE and interface tests (three additions in all); DATA_CONTRACTS now says what `input.sha256`, `rec_dropped` and replay events are; the live and replay files are validated against the schemas in tests.
- Test gaps closed: lossless capture with a slow consumer (it was untested), the recorder failure and size-change paths, the `t_video` join with an offset (it was faked by `seq / 10`), PASS and FAIL tokens, the 70, 85 and 90% boundaries, the latest-run default, `--tolerance`, a BOM in `labels.csv`, shots on a frame with no video time, a session with no video hash.
- Also fixed: a frame given up at stop in a replay was uncounted; the recorder queue is 64 frames (it was 256, about 1.6 GB at 1080p); the `t_video` index is bounded; the `dropped` count is thread-safe.

**Reviews, round 2 (the same four, on the fixes).** `reliability-reviewer`: PASS (BLOCKER verified fixed by killing a live run: 243 readable frames; a clean 900-frame run valid and hash-checked). `code-reviewer`: PASS. `contract-guardian`: CHANGES REQUIRED for one stale `video.mp4` name, fixed. `test-auditor`: CHANGES REQUIRED for one item, that nothing tested main's `lossless=` wiring for `--replay`; fixed with a slow-detector replay test (dropped 0 of 30) and a live control that does drop, and checked by mutation (forcing `lossless=False` makes the replay drop 27 of 30 and the test fails). Also fixed from round 2: the recorder's index and counters are under one lock (a dict-changed-size error could stop capture; a frame could be neither written nor counted at a writer failure); frames of another size get their own `recorder_backlog` event; `--replay` follows `recording.path` (an older `video.mp4` session replays) and accepts `.mkv`; tests for the outcome-window cap and H3b at exactly 80%. Round 2 has not been run on this last commit.

**Known, not fixed (minor).** Two replays of one session started within the same milliseconds can still lose a run id (8 concurrent replays lost one; 2 or 3 did not): a read-merge-write, not a lock. `run.json` has no status field, so an interrupted replay is visible only in `session.json` events. A replay of a session whose live run is still writing is not refused. The "no video hash" warning goes to stderr only. The partial-run note can fire falsely on a live run whose last processed frame is well before the end of the video. One replay of eight exited with a native crash (0xC0000005) once, cause not investigated. The test for the per-process temp file name runs its two writers in one process.

**Not fixed, on purpose.** (1) H1 is scored once, not twice (video alone and video + sensor, FR-013): `shots.csv` holds only the final call, so two scores need two runs (D-043). (2) H3 and H4 print "not scorable": `labels.csv` has no field for them (D-043); the owner has deferred that decision. (3) A truncated video file is read as a normal end of file: only the scorer's warning marks it. (4) A disk-full during recording that OpenCV does not report as an error is not detected.

**One real run (2026-10-20, CPU, RF-DETR Nano, the synthetic 30-frame clip, before the MKV change).** Live run 8951d370: captured 30, processed 5, dropped 25, `rec_dropped` 0, the video has all 30 frames. Replay fc115354 of that session: captured 30, processed 30, dropped 0; `input.sha256` equals the session's `recording.sha256`. A synthetic clip with no people shows the plumbing, not detection quality.

**Open for the developer.**
- Confirm `video.mkv` in place of `video.mp4`, or accept losing the video of a killed session (D-042).
- Phase 04 A6 and R1-A4 are manual and not done: a live 5-minute session with recording (playable video, size per minute recorded, check it plays in your player), and the scoring tool against a hand calculation on one real session.
- D-043: the matching tolerance (1.0 s) and the window rules are chosen, not measured. H1 is "not scorable" until slice R3 writes `shots.csv`; H3b until R5 puts numbers in `tracks.csv`. The scorer was tested on built fixtures, not on a real shot layer.
- Re-run the four reviewers on the fix (gate step 3 requires it).
- Recording is on by default in Studio too: measure disk use per minute on the real setup.
- A phone that reports a wrong fps gives a wrong `t_video` scale (D-042).
