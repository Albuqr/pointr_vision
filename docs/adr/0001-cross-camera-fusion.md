# 0001 — Cross-camera fusion as a post-session step
status: accepted · date: 2026-10-19 (accepted by the owner)

## Context
FR-004 asks for one record per player when two phones see the same person, with a report of where the cameras differ. FR-014 covers a phone dropping mid-session. Today D-022 runs one OS process per camera with **no fusion across cameras**, and `docs/BACKLOG.md` notes that cameras of one group are not aligned: each has its own `t0` and `t0_wall`. Both cameras are calibrated to court metres (FR-002, error at most 0.5 m), so ground-plane positions are comparable. Fusion depends on ADR 0002 (the clock model).

## Options considered
| Option | Pros | Cons | Fit to NFRs |
|---|---|---|---|
| B1. Post-session late fusion of per-camera tracks on the court plane: match by distance and time in the overlap zone, then by jersey number and colour; write one record per player plus a difference report | Per-camera processes stay untouched (D-022 holds on the live path); testable offline on recorded files; keeps both cameras' readings | No live fused numbers; relies on the clock model and on the 0.5 m calibration | Fits NFR-003 (swappable layers), NFR-004 (files are the source of truth) |
| B2. B1 run near-live over the growing session files | Shorter delay | Needs files readable while written; provisional IDs change under the user; no deployed example found | Weaker on NFR-004 |
| B3. Early fusion in a bird's-eye-view network | Highest published numbers (WILDTRACK, MultiviewX) | Trained and tested with 6–7 synchronised cameras; no 2-camera result; changes the architecture; needs training data | Not feasible by December |
| B4. No fusion; per-camera stats and a manual merge | Safe fallback if clock sync fails | Violates FR-004 | Fallback only |

## Decision
Decided (owner, 2026-10-19): **B1**. Fusion is a separate step that reads the per-camera session folders of one group and writes its own outputs (`fusion/` under the group), leaving the capture and perception processes unchanged. Matching is limited to the overlap zone; both cameras' readings are kept and disagreements are flagged. Fusion results are trusted only after the clock test of ADR 0002 passes. B2 waits until B1 works. B4 is the fallback.

## Consequences
- New contract section for the fusion outputs (a bump of `CONTRACT_VERSION` from 0.10.0, defined in `DATA_CONTRACTS.md` before the code).
- FR-014 gap periods are marked in the fused record and left out of the H3b and H6 scoring.
- Evidence for any accuracy number is low: no published two-camera, same-kit, tripod result and no timing-tolerance curve was found. H6 stays a `believe` until the first two-phone session.

## Sources
- [EarlyBird: early-fusion multi-view tracking (Teepe et al., 2023)](https://arxiv.org/abs/2310.13350) · tier A, preprint · benchmark on 7 synchronised cameras
- [TrackTacular: lifting tracking to BEV (Teepe et al., 2024)](https://arxiv.org/abs/2403.12573) · tier A, preprint · no 2-camera ablation
- [GTA: global tracklet association for multi-object tracking in sports (Sun et al., 2024)](https://arxiv.org/abs/2411.08216) · tier A, preprint · post-processing improves IDF1 on a fixed camera
- Research note: `.suite/research/identity-and-fusion.md`

**Amendment (R0, D-041).** Fusion writes to `sessions/fusion_<group_id>/<fusion_id>/`, not `fusion/` under the group.
