# Phases 10-14: short specs

Expand each into its own `PHASE_XX.md` when it becomes current, using results from the
one-person, 3x3 and 5x5 tests. Scope v2 sections 6, 11 and 12 are the reference.

## Phase 10: Court calibration
Homography from measured floor marks to court coordinates. Foot point estimated from the
box bottom (later from pose). Report static error on marks **not** used for calibration.
Adds `x_m`, `y_m`, `calibration_id`, `position_method` to tracks (contract bump). Distance
and speed only after the error is known.

## Phase 11: Athlete assignment (3x3)
Assign a registered player to a track segment, with source (manual, number, rule) and
review. Identity corrections in a separate table with history. Measure ID switches and
review time per session. Registering players does not make the system recognise them; this
phase is where that link is made.

## Phase 12: Movement recognition (RF05)
Pose estimation added to perception. Define each event (jump, sprint, shot) precisely,
annotate a held-out set manually, compare detections against it. No event is reported in the
UI until its validation result is recorded.

## Phase 13: Custom phone app (optional)
Android app that streams the camera to the notebook and reports device facts: camera
present, resolution and fps supported, battery, temperature. Completes RF01's device check.
Only worth building if the existing camera apps limit resolution, stability or control.

## Phase 14: Analytics (pointr-data)
Bronze/silver/gold over synced sessions; one real question answered first (scope step 9).
dbt where it earns its place.
