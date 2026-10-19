# Track R: December test rig

Accepted by the owner, 2026-10-19. Own track (D-033), separate from phases 03–09. Written by suite stage 3 from
`.scratch/pointr-vision/spec.md` (signed 2026-10-19), `.scratch/pointr-vision/decision-record.md`
and the proposed ADRs `docs/adr/0001`–`0006`. Slices below are ordered by the risk of the
hypothesis they test. No effort figures are given: none is measured (`CLAUDE.md` rule 5).

## Goal
A test rig the owner operates alone, with 2 phones, a PC and a rim sensor, that records basketball
sessions with the ball, rim, shots and jersey numbers logged and scored against hand labels, so
that hypotheses H1, H2, H3, H3b, H4, H6 and H7 can be decided in the December tests.

## Requirements
Spec FR-001 to FR-015, NFR-001 to NFR-004, CFG-001 to CFG-005 (`.scratch/pointr-vision/spec.md`).
Existing requirements touched: RF04 (IDs), RF08 and RF09 (recording), RNF02 (real time),
RNF04 and RNF05 (video).

## Scope: slices
Each slice adds one layer behind an interface. A slice is closed by its acceptance rows and by the
gate below. Contracts first: R0 writes every new format before any code reads or writes it.

| Slice | Adds | Spec items | Decisions | Hypothesis |
|---|---|---|---|---|
| R0 | Contracts and decisions: `objects.csv`, `events.csv`, `shots.csv`, `run.json` blocks `checks` and `clock`, `tracks.csv` columns `player_number` and `id_source`, fusion outputs; JSON Schemas; `CONTRACT_VERSION` 0.11.0; a `DECISIONS.md` entry per accepted ADR | all new formats | 0001–0006 | all |
| R1 | Recording and replay for the rig, the hand-label file and the scoring tool | FR-013, RF08 video, RF09, RNF04, RNF05 | — | H1–H4 (instrument) |
| R2 | Ball and rim detection and the H2 baseline: measure first (ball pixel size, 2/5/10/15 fps subsample), then fine-tune; rim fixed per session | FR-008, NFR-001, NFR-002 | 0004 | H1, H2 |
| R3 | Shot layer: attempts, make/miss on video alone, shooter by last possession, shot map | FR-010 (video), FR-011, FR-012 | 0005 | H1, H4 |
| R4 | Rim sensor and clock model: `EventSource`, firmware, ping-pong sync, LED test, outage handling, sensor matching | FR-005, FR-009, FR-010 (sensor), FR-015 | 0002, 0003 | H1 |
| R5 | Identity: `IdentityResolver`, number voting, roster, then colour and position gating | FR-006, FR-007, NFR-003 | 0006 | H3, H3b |
| R6 | Two-camera fusion, failure handling and the startup checks in Studio | FR-001, FR-003, FR-004, FR-014 | 0001 | H6, H7 |

## Out of scope
The backlog table of the spec: "guarded by", session browser, live metrics (H8), cloud sync,
coach-facing report (H5), learned re-identification, shot form. Consent and minors (adults only in
the owner's test group). Phases 03–09 and 10–14 scope.

## Owner decisions (2026-10-19)
Decided (D-034 to D-040):
1. **Recording and replay** are built inside Track R as slice R1, following the Phase 04 contract so they merge into Phase 04 later.
2. **New dependencies** are approved by category: a labelling and fine-tuning workflow (R2), a number-recognition model (R5), ESP32 firmware tooling in a `firmware/` folder (R4). Each slice names the exact packages or models here before they are installed.
3. **Spec changes** CR-2 (FR-005), CR-3 (FR-006) and CR-4 (FR-009) are accepted and the spec is amended.

Still open:
- **PC-to-rim distance.** About 5 m or less picks a USB cable (ADR 0003, L1); more picks ESP-NOW (L2). L2 is assumed until the owner gives it.
- **Spec CR-1.** What behaved differently on a failed calibration (D-027 already starts the camera uncalibrated with a warning).
## Acceptance
| # | Criterion | Test |
|---|---|---|
| R0-A1 | Every new file and field is in `DATA_CONTRACTS.md` and its schema; `CONTRACT_VERSION` bumped; sample files validate | contract tests |
| R0-A2 | A `DECISIONS.md` entry exists for each accepted ADR before the code that needs it | review |
| R1-A1 | A recorded session replays as a new run; the original is untouched (RF09) | integration |
| R1-A2 | MP4 and MOV replay (RNF05) | integration |
| R1-A3 | Given a hand-labelled session, the scoring tool prints H1, H3, H3b and H4 next to their thresholds (AC-013.1) | integration on a fixture |
| R1-A4 | The scoring tool's results equal a hand calculation on one session | manual |
| R2-A1 | Ball and rim are boxed around a recorded release (AC-008.1) | integration on a fixture |
| R2-A2 | Subsampled runs at 2, 5, 10 and 15 fps report ball pixel size and the share of frames with the ball found | integration |
| R2-A3 | The H2 baseline on the borrowed GPU PC logs total fps, time per stage and delay with two phones (NFR-001, NFR-002) | manual, record `run_id` |
| R3-A1 | 30 hand-counted shots: at least 85% of attempts found and 90% of those called right, on video alone (AC-010.1) | manual on a recorded session |
| R3-A2 | A make with no clear possession has shooter "unknown" and is credited to no player (AC-011.1) | unit |
| R3-A3 | A shot released from a taped mark plots within 0.5 m (AC-012.1) | manual |
| R4-A1 | A sensor event and a frame recorded together carry timestamps from one clock (AC-005.1) | integration |
| R4-A2 | The LED test reports median, 95th percentile and standard deviation per camera, and the drift (AC-005.2) | manual |
| R4-A3 | 10 hand drops through the rim register 10 events (AC-009.1); a dry run with rim hits, net sway and hands counts false triggers | manual |
| R4-A4 | A free throw released at t with a sensor event at t + 0.9 s is a make; the only event at t + 3 s is not matched (AC-010.2) | unit |
| R4-A5 | An unplugged sensor is logged as an outage and its makes are flagged "no sensor" (AC-015.1) | integration |
| R4-A6 | A 30-minute soak with sequence-number gap counting; the repeat count is chosen from the measured loss | manual |
| R5-A1 | A player in view for 10 seconds gets the number on the jersey on at least the agreed share (AC-006.1) | manual, hand-labelled frames |
| R5-A2 | Returns after leaving the frame keep the ID in at least 8 of 10 cases (AC-007.1) | manual |
| R5-A3 | Swapping the identity method changes no column of `tracks.csv` (NFR-003) | integration |
| R6-A1 | Two phones see one player: the final record lists the player once, with a difference report (AC-004.1) | integration on fixtures, then manual |
| R6-A2 | A phone's stream cut three times (5, 20 and 60 s): the session continues, each gap is logged and the phone resumes with IDs re-linked (AC-014.1) | manual |
| R6-A3 | The five startup checks show on screen and in `run.json`; a failed check still starts the session (AC-003.1 to AC-003.3) | integration |
| R6-A4 | Full setup, first phone placed to session started, retries included, takes at most 15 minutes (H7) | manual, timed |
| R-A1 | A kill during a session leaves readable files and an honest status (NFR-004) | integration |
| R-A2 | Tests from earlier phases still pass | automated |

## Gate
`GATES.md` steps 1 to 5 apply to every slice, with the manual acceptance recorded in
`docs/phases/PHASE_R_REPORT.md` and a tag `track-r-<slice>` after each slice's gate passes.

**Gate reviewers:** `code-reviewer` and `test-auditor` on every slice; `contract-guardian` on R0 and on
any slice that writes or reads the new files; `reliability-reviewer` on R1, R4 and R6 (recording,
outages, gaps). `security-reviewer` is not needed: nothing leaves the owner's PC.

Hypotheses are decided only by the manual acceptance rows on real hardware, with the thresholds of
the spec. Any figure written to a doc must come from a recorded run (`CLAUDE.md` rule 5).
