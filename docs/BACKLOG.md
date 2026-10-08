# Backlog

Ideas and findings outside the current phase. One line each: what, why it came up, which
phase it might belong to.

| Item | Raised in | Possible phase |
|---|---|---|
| Cloud recording analysis service: user uploads a recorded video, a cloud GPU runs the pipeline as a replay and returns runs and reports. No real time, no local hardware needed. Possible separate product offering. Not the focus. See D-005 | Architecture review, 2026-10-07 | After 09, optional |
| CLAUDE.md rule 3 says to record package versions in `session.json`, but DATA_CONTRACTS puts them in `run.json` (`detector`/`tracker`/`runtime`). Contract wins for now; reword rule 3 | Phase 00 planning, 2026-10-07 | 03 |
| Phase 01 emits `source_open_failed`, which is not in the contract's event kinds (and ARCH §4 names health kinds `lost/frozen/dark/recovered`). Add the kind to DATA_CONTRACTS + schema (minor bump) when phase 01 needs to persist it | Phase 00 planning, 2026-10-07 | 01 / 03 |
| Phase 01 frozen/dark thresholds and phase 03 "all thresholds in run.json" have no field in `run.json` besides `detector.threshold` and `tracker.params`. Decide where health thresholds go before phase 03 | Phase 00 schema writing, 2026-10-07 | 03 |
| Phase 04 needs a MOV fixture; `make_clips.py` writes MP4 only | Phase 00 fixtures, 2026-10-07 | 04 |
| `SessionWriter.start(meta)`/`close(status)` cannot carry run.json data (run_id, mode, input, detector, tracker, runtime, counts). Phase 03 must add run metadata (e.g. `RunMeta`, `start_run`) with a DECISIONS entry; replay (04) adds runs to an existing session. See D-008 | code-reviewer, phase 00 gate | 03 |
| ARCHITECTURE §3 lists `tests/edge/ sync_agent/ api/ e2e/`; not created (git does not track empty dirs). Create each when its first test lands | code-reviewer, phase 00 gate | 01+ |
| Contract drift tests compare keys, enums and event kinds only, not types/nullability or `runtime.device` pattern; `RecordingInfo` fields are not checked against ARCH §4. Extend when phase 03 adds CSV schemas | contract-guardian / test-auditor, phase 00 gate | 03 |
