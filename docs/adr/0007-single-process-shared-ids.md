# 0007 — One process for all cameras of a group, with track IDs shared live
status: accepted · date: 2026-10-28 (owner) · supersedes D-022 for groups; supersedes ADR 0001's matching

## Context
In the 2026-10-22 field test (D-044) the same person got a different ID on each camera, and the owner needs one ID per
person across both cameras while recording. D-022 runs one OS process per camera and ADR 0001 (B1) matches cameras
only after the session, so neither can give shared IDs live. The same field test showed that one process per camera
does not explain the ~10 fps live cap (two replay processes ran as fast as one), so process layout is not a speed
argument either way.

## Decision
Decided (owner, 2026-10-28): every camera of a group runs in **one process** with one shared detector model and one
tracker state, and a track ID means the same person in every camera of the group. People are matched across cameras
by court-plane position and time where the views overlap; when that is not possible (a camera without a valid
calibration, or no overlap) the fallback is hand-built appearance cues: clothing colour histograms and box height, no
learned model and no new dependency. The same cues serve recovery after one person walks behind another. Each camera
keeps its own session folder; post-session fusion stays, but only combines each shared track's per-camera readings and
lists the camera disagreements. Built as Phase R slice R2a.

## Considered options
- **Separate processes that exchange tracks live**: keeps crash isolation, but adds inter-process messaging and a live
  clock hand-off for no gain the owner needs.
- **Keep B1 (post-session matching)**: no live shared IDs, which is the need.
- **Learned re-identification for the fallback**: likely stronger, but out of Phase R scope and a new dependency.
- **Require calibration on every camera**: would break the rule that a failed startup check never blocks the start.

## Consequences
- **No crash isolation.** A native crash or a hang in shared code ends every camera of the group. Accepted by the owner;
  every camera's files stay readable up to the last flush (NFR-004) and the crash is logged. Stream loss on one camera
  is still handled per camera (FR-014), each camera keeping its own capture thread.
- Contract change before code: track IDs are unique within a group, not a run; a replay processes a group's videos
  together. Minor bump of `CONTRACT_VERSION`, defined in `DATA_CONTRACTS.md` first.
- The appearance fallback's accuracy is unmeasured; it is scored on a recorded clip before anyone relies on it.
  Speed of the shared model is recorded per camera, with no figure written until a recorded run.
- R2–R6 are built inside the single process, which is why R2a comes before them.
