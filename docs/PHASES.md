# Phases

**Current phase: 03 (session and logging): v0 core built ahead of 02b (D-020); gate, A6, A7 and report pending. 02b closed as superseded (D-046). Scope extended with the 2026-10-22 field-test fixes (D-044, PHASE_03.md "Scope addition").**

**Approved scope exception (D-025):** Part 5a pulls the local Studio shell from phase 06
forward, and part 5b pulls visual calibration from phase 10 forward into that app. This is
one approved, bounded v0 deliverable, not a claim that intervening phases are complete or
that phase 03 is formally closed. Keep work within Studio and per-camera calibration; the
explicitly excluded phase work remains deferred.

Each phase adds one layer behind an interface and ends with a gate (`GATES.md`). Phases
00-05 are the first delivery from scope v2: the live pipeline working before the first
structured test with one person. Later phases follow the scope's progression.

| Phase | Name | Adds | Requirements | Depends on |
|---|---|---|---|---|
| 00 | Foundations | repo, tooling, contracts, test harness, fixtures | - | - |
| 01 | Capture | frame sources, source health, preview | RF01 (partial), RF02, RNF01 (recorded) | 00 |
| 02 | Perception | detector + tracker, HUD metrics | RF03, RF04, RNF02 (measured) | 01 |
| 02b | Detector spike (closed, superseded by B9 and R2-A3, D-046) | compare RF-DETR Nano via OpenVINO/ONNX vs YOLOX-Nano/Tiny on a recorded clip; input to Q-02. Also measure ID survival through short (<1 s) exits at each speed | RNF02 (input to Q-02) | 02 |
| 03 | Session and logging | session lifecycle, files, partial data, soak test | RF06, RF07, RF08 (data), RNF03 | 02 |
| 04 | Recording and replay | raw video, replay as new run, MP4/MOV | RF08 (video), RF09, RNF04, RNF05 | 03 |
| 05 | Reports | coverage and failure reports | RF10, RF11 | 03, 04 |
| — | **Milestone A** | scope v2 gate: one-person tests can start | | 00-05 |
| 06 | Local store and registrations | SQLite, players, teams, sessions, local web UI | RF12, RF13, RF14, RN06, RN07 | 03 |
| 07 | Cloud API | FastAPI + Postgres, idempotent sync endpoints, auth | RF15 (server), RNF08 | 06 |
| 08 | Sync agent | outbox, background agent, pull cursor | RF15 (client), RNF08, RNF09 | 06, 07 |
| 09 | Video lane and plans | entitlements, resumable upload, locked video, retention | RF16-RF20, RNF10, RNF11, RN12 | 04, 08 |
| — | **Milestone B** | full local-first platform | | 00-09 |
| 10 | Court calibration | pixels to metres, error report | scope step 6 | 03 |
| 11 | Athlete assignment | track → registered player, identity corrections (3x3) | RF04 extension | 06, 10 |
| 12 | Movement recognition | pose, event definitions, manual validation | RF05 | 10, 11 |
| 13 | Custom phone app (optional) | camera + device checks on the phone | RF01 (full) | 01 |
| 14 | Analytics (pointr-data) | bronze/silver/gold over synced data | scope section 12 | 08 |
| R | **Track R: December test rig** (own track, D-033) | one process with shared IDs (R2a, D-045), ball and rim detection, rim sensor and clock model, shot layer, jersey identity, two-camera fusion, scored against hand labels | spec FR-001 to FR-015 | 03 running; recording and replay: open decision in `phases/PHASE_R.md` |

Phases 10-14 have short specs only. Expand each into a full phase file when it becomes the
current phase, using what the earlier tests showed.
