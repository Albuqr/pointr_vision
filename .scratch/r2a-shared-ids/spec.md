# Spec: R2a, one process per group with track IDs shared live
Status: ready-for-agent
Slice: Phase R, R2a · Decisions: ADR 0007, D-045, D-047 · Acceptance: R2a-A1 to R2a-A5 (`PHASE_R.md`)
Date: 2026-10-28 · Synthesised from the grill-with-docs session of the same day

## Problem Statement

In the 2026-10-22 field test the operator recorded a group with two phones, and the same person got a different track
on each camera. Each camera runs in its own process with its own detector and tracker, so nothing links a person seen
by camera 1 to the same person seen by camera 2 while the group records. The cross-camera link only existed as a plan
for after the practice (ADR 0001). The operator and coach need one track per person across the whole group while it
records, so that anything built on tracks (shots, player numbers, leaves and returns, fusion records) talks about one
person, not one person per camera. The field test also showed tracks breaking when one person walks behind another.
Each camera also loads its own copy of the detector, which wastes memory on the PC.

## Solution

Every camera of a group runs in one process. The process loads one detector and keeps one tracker state for the
group. When a person is seen by two cameras, the two cameras' readings carry the same track. Cameras are matched by
court position and time where their views overlap. Where that is not possible (a camera without a valid calibration,
or no overlap), clothing colour and box height are used instead, with no learned model. The same colour and height
cue helps a track survive when one person walks behind another. Each camera still writes its own session folder with
its own video, frames and tracks, so the scoring tool, replay, Studio and run reports keep working. A replay of a group
processes the group's videos together and gives the same shared tracks. If one camera's stream drops, the other keeps
recording. If the process crashes, every camera's files stay readable up to the last flush.

## User Stories

1. As an operator, I want to start a two-camera group with one action, so that both cameras record together without me managing two programs.
2. As an operator, I want both cameras to run in one process, so that the detector is loaded once and the PC has memory to spare.
3. As an operator, I want a person seen by both cameras to have the same track in both, so that the group's data describes one person once.
4. As an operator, I want each camera to keep its own session folder, so that I can still find, play and replay each camera's video on its own.
5. As an operator, I want to know when a camera could not share tracks (for example it has no valid calibration), so that I understand why its tracks may differ.
6. As an operator, I want a camera without a valid calibration to still share tracks where colour and height allow, so that a failed calibration does not cost me shared tracks entirely.
7. As an operator, I want a failed calibration check to never block the group from starting, so that I can still record a practice when setup goes wrong.
8. As an operator, I want one camera's stream loss to leave the other camera recording, so that a phone dropping off Wi-Fi does not end the practice.
9. As an operator, I want a camera whose stream comes back to rejoin the group's shared tracks, so that a short outage does not split people into new tracks for the rest of the practice.
10. As an operator, I want a crash of the process to leave every camera's files readable with an honest status, so that I never lose a practice silently.
11. As an operator, I want a crash to be logged as an event, so that I can tell a crash from a normal stop.
12. As an operator, I want Studio to start, show and stop a group the same way as before, so that I do not relearn the tool.
13. As an operator, I want each camera's frame rate and dropped frames recorded separately, so that I can see which camera is struggling.
14. As an operator, I want to replay a recorded group as a new run, so that I can reprocess the practice with the shared tracks without touching the original.
15. As an operator, I want a replay of a single camera's session to still work, so that older sessions and single-camera recordings remain usable.
16. As an operator, I want a single camera without a group to keep working as before, so that a quick one-phone recording needs no group setup.
17. As a coach, I want a player who leaves one camera's view but stays in the other's to keep the same track, so that their numbers are not split in two.
18. As a coach, I want a player who walks behind a teammate to keep their track, so that the practice data does not invent new people.
19. As a coach, I want two players standing side by side to keep separate tracks, so that their numbers are not merged into one.
20. As a coach, I want the fusion record for a player to combine both cameras' readings of their shared track, so that I get one record per player number.
21. As a coach, I want camera disagreements listed, so that I can see where the two cameras saw the same player differently.
22. As the developer, I want the cross-camera matching in one module with a small interface, so that I can test its edge cases without running cameras.
23. As the developer, I want the group run testable with a scripted fake detector and synthetic clips, so that default tests need no camera, weights or network.
24. As the developer, I want the contract to say that a track is unique within a group before any code changes, so that every reader agrees on what a track means.
25. As the developer, I want every track row to say how it was linked (position, appearance or unshared), so that a wrong merge can be traced.
26. As the developer, I want the matching thresholds recorded in each run's metadata, so that a run can be reproduced and compared.
27. As the developer, I want the ID changes per person on a recorded occlusion clip measured before and after R2a, so that the improvement is a recorded figure, not a claim.
28. As the developer, I want each camera's processing rate with the shared detector recorded, so that the effect of one model on throughput is measured against the field-test runs.
29. As the developer, I want R2 to R6 to build on the group process, so that ball, shots, identity and fusion are not rebuilt later.
30. As the developer, I want the existing per-camera tests to keep passing, so that R2a does not break recording, replay, scoring or reports.

## Implementation Decisions

- **Contract first.** `DATA_CONTRACTS.md` changes before code, with a minor `CONTRACT_VERSION` bump and a `DECISIONS.md`
  entry. A track ID is unique within a group, not a run: the same `track_id` in two cameras' tracks files of one group
  is the same person. A camera without a group keeps run-scoped track IDs as today. A run's metadata records the
  group run (which cameras were processed together) and the matching parameters. The tracks file gains a `link`
  column on each row, next to `id_source`: `position`, `appearance` or `unshared`, saying how that row's track was
  linked to the other cameras (owner, 2026-10-28). No separate match log.
- **Group runner (new deep module, seam A).** Takes a group's cameras (each with source, camera id and optional
  calibration), one detector and the session output root. It owns one capture thread per camera (unchanged capture
  and health per camera), one processing loop that feeds every camera's frames through the shared detector, one group
  tracker state, and one session writer and recorder per camera. It replaces the per-camera child processes for a
  group; a single camera without a group may run through it as a group of one.
- **Shared detector.** Loaded once per group. Frames from every camera are detected in turn, or batched if the
  installed `rfdetr` supports it: check the installed source before choosing (CLAUDE.md rule 3). Processing order
  stays increasing `seq` within each camera.
- **Per-camera tracking, group-level linking.** Each camera keeps its own tracker for frame-to-frame association (the
  existing ByteTrack wrapper). A group-level linker maps each camera's local tracks to group track IDs. The written
  `track_id` is the group ID.
- **Cross-camera matcher (new deep module, seam B).** Interface: given, for one moment in group time, each camera's
  local tracks with their court position (when calibrated) and an appearance descriptor, plus the matcher's own state,
  return the group track ID for every local track. Rules: match by court-plane distance and time within the overlap
  zone; when a camera has no valid calibration or the person is outside the overlap, fall back to appearance (clothing
  colour histograms of the upper and lower box and box height); never merge two local tracks of the same camera that
  are present at the same time; a local track that loses its link keeps its group ID while lost, within the tracker's
  lost-track time, so a return or an occlusion re-links instead of creating a new ID. Thresholds are parameters with
  recorded defaults.
- **Appearance descriptor.** Hand-built with OpenCV and numpy, which are already installed: no learned re-ID and no new
  dependency (ADR 0007). Computed from the person's box in the frame being processed.
- **Clock.** All cameras are on the one PC clock (ADR 0002). Group time aligns cameras using each camera's frame
  receive time minus its camera latency when one has been measured, otherwise zero, the same correction fusion uses.
- **Failure handling.** One camera's source loss or outage is handled per camera as today (FR-014); its gap is logged
  and the other cameras continue. A camera that comes back re-links through the matcher. An exception in shared code
  ends the group through the one shutdown path: every writer writes its final status, the error is a session event in
  every camera's session, and the files stay readable (NFR-004). A native crash cannot be caught; the flush-per-second
  durability of today keeps the files readable up to the last flush.
- **Studio.** Studio keeps calling the launcher through its existing factory. For a group the launcher starts one group
  process instead of one child per camera, and Studio's per-camera status, preview and stop keep working on top of it.
- **Replay.** A replay of a group adds a new run to every camera's session, processing the group's videos together in
  group time. A replay of one session (or a bare video file) works as today.
- **Fusion (R6) changes shape.** Fusion no longer matches cameras. It combines each shared track's per-camera readings
  into one fusion record per player number and lists the camera disagreements. The fusion contract's matching
  parameters are trimmed when R6 is built, not in R2a.
- **No speed or accuracy claims.** Per-camera processing rate, drops and app delay are recorded as today; no figure is
  written in docs until a recorded run (CLAUDE.md rule 5).

## Testing Decisions

- **Good tests check outcomes a reader of the session files can see**, not internals: which `track_id` appears in
  which camera's tracks file, what status and events each `session.json` holds, how many detector instances were
  created. No test asserts on the linker's internal tables.
- **Seam A, the group runner**, tested in-process with synthetic sources and a scripted fake detector that returns
  chosen boxes per camera and frame, then by reading the session folders. Covers: one detector instance for two
  cameras and two complete session folders (R2a-A1); a person placed at the same court point in both cameras gets one
  `track_id` in both tracks files (R2a-A2); a camera without a calibration falls back to appearance and a session event
  says so (R2a-A3); one source ending early leaves the other camera recording, and an injected processing error leaves
  every camera with a final status and an error event (R2a-A4); a camera without a group behaves as before; a replay of
  the group adds one run per camera and gives the same shared IDs as the live run on the same frames; every new file
  and field validates against the bumped schemas.
- **Seam B, the matcher**, unit-tested on scenarios with synthetic tracks, positions and descriptors: same court point
  in two cameras links; two people side by side stay apart; two local tracks of one camera present together are never
  merged; a track that is lost and returns within the lost-track time keeps its group ID; an uncalibrated camera links
  by appearance only when the descriptor is close enough and never by pixel position; a camera that rejoins after an
  outage re-links; thresholds come from parameters.
- **Studio** through its existing launcher factory seam: a group starts one group process, per-camera status and stop
  still report correctly.
- **Manual (R2a-A5):** ID changes per person on a recorded occlusion clip and per-camera processing rate, recorded
  before and after R2a with their `run_id`s in `PHASE_R_REPORT.md`, on the GPU PC and on the notebook.
- **Prior art:** the live recording and replay tests (synthetic clip, no detector, files read back), the capture tests'
  scripted fake source, the Studio API tests with an injected launcher factory, and the Track R contract tests that
  validate sample files against schemas. Default tests need no camera, weights or network; any test needing real
  weights is marked `slow`.

## Out of Scope

- Ball and rim detection, the shot layer, rim sensor, jersey identity and fusion itself (R2 to R6).
- Learned re-identification or any new dependency.
- Separate processes that exchange tracks live (rejected in ADR 0007).
- Fixing the ~10 fps cap: runs L1 to L8 come after R2a, once the field-test note is in the repo.
- Linking tracks to athletes (phase 11).
- Requiring calibration to start a group.

## Further Notes

- Prerequisites in the order of D-047: `track-r-R0` tagged and R1's manual checks done; the Studio stop fix and
  per-camera partial calibration (court-position matching needs each camera calibrated to the part of the court it
  sees).
- Crash isolation is given up on purpose (ADR 0007): a native crash ends every camera of the group.
- The appearance fallback's accuracy is unknown until R2a-A5 records it. Treat any merge it makes as low confidence in
  later slices until then.
- `reliability-reviewer` joins `code-reviewer`, `test-auditor` and `contract-guardian` at this slice's gate.
