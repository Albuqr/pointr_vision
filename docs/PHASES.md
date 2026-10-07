# Phases

**Current phase: 00**

Each phase adds one layer behind an interface and ends with a gate (`GATES.md`). Phases
00-05 are the first delivery from scope v2: the live pipeline working before the first
structured test with one person. Later phases follow the scope's progression.

| Phase | Name | Adds | Requirements | Depends on |
|---|---|---|---|---|
| 00 | Foundations | repo, tooling, contracts, test harness, fixtures | - | - |
| 01 | Capture | frame sources, source health, preview | RF01 (partial), RF02, RNF01 (recorded) | 00 |
| 02 | Perception | detector + tracker, HUD metrics | RF03, RF04, RNF02 (measured) | 01 |
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

Phases 10-14 have short specs only. Expand each into a full phase file when it becomes the
current phase, using what the earlier tests showed.
