# Track R report

## R0 Contracts (branch track-r-r0-contracts)

**Status:** ready for the developer to read, then tag `track-r-R0`. Not committed beyond the first two R0 commits (39c5f68, a224b85); the review fixes are in the working tree. Nothing is pushed.

**What R0 delivers.** Contract 0.11.0: DATA_CONTRACTS.md sections 11 to 15 (objects, events, shots, labels, fusion), the new run.json blocks (`t0_mono`, `checks`, `clock`, `objects`, `gaps`, `outages`), `frames.csv` `t_video`, `tracks.csv` `player_number` and `id_source`, four new session event kinds, JSON Schemas and fixtures (JSON and CSV), code constants, the writer changes (`set_final`), D-041, and an amendment to ADR 0001.

**Environment.** Light Python 3.11.9 .venv (numpy, opencv, jsonschema, pytest, ruff). No torch or supervision, so 17 end-to-end tests and tests/edge/test_perception.py cannot run here; this is the same set as before R0 (baseline compared by test name). Result: 675 passed, 17 failed (baseline), 1 collection error (baseline).

**Reviews (fresh context, two rounds).** Round 1: code-reviewer and contract-guardian CHANGES REQUIRED. Round 2 (after the fixes): all three CHANGES REQUIRED, with smaller findings; the second-round fixes are applied and the test-auditor's three majors are fixed (per-column enum tests, doc-driven CSV types and empty cells, the ADR-to-decision existence test). Round 3 found a blocker (the Studio read frames.csv by position and would have shown no live stats; fixed, with a test) and gap/outage definitions (fixed; `detected_t` added). The test-auditor's round-3 majors (null t0_mono test, hardened ADR test, extra negative cases) are fixed. The owner confirmed the per-group sensor file (extended to two sensors, one per rim), the gaps/outages fields and detected_t on 2026-10-19. No fourth review round was run.

**Open for the developer.**
- Confirm the per-group sensor file `sessions/sensor_<group_id>/events.csv` and the run.json `gaps`/`outages` fields (D-041; spec FR-014/FR-015).
- PC-to-rim distance (ESP-NOW assumed) and spec CR-1 are still open.
- Run the end-to-end tests on a machine with torch before the gate (BACKLOG).
- R0-A2: the "entry written before the code" half stays a review item.
