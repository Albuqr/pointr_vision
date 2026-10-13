Update this file at the end of every part.

# Current handoff

- Merged: v0 parts 1–4.
- Part 1: session logging and durable session files.
- Part 2: device selection and `docs/RUNBOOK_TONIGHT.md`.
- Part 3: multi-camera launcher, phone URLs, one process per camera, shared `group_id`.
- Part 4: movement report in pixels through a `PositionMap`.
- Part 4b: tracker settings are configurable; default lost-track duration remains 1 s.
- Real hardware: Ctrl+C in Git Bash stops all cameras cleanly.
- Real hardware: phone URL reports `source_lost` about 2 s after Wi-Fi loss and recovers.
- Phone constraint: one viewer per phone; an open browser tab blocks Pointr.
- i7-10510U, two cameras: 1.5–1.7 fps and 0.35–0.57 fps.
- Tracking: 17 track fragments in 130 s at about 1.5 fps; lost-track buffer is 1 s.
- Part 4b test: two 60 s laptop-webcam runs, same walking script, about 2.2 fps each.
- Default 1 s and `--track-lost-secs 4` both produced 3 tracks; 4 s did not improve fragmentation.
- With 4 s, a 1.0 s exit still produced a new ID: at low fps, the returning box misses the IoU prediction, so the buffer is not the cause.
- Keep the default 1 s for tonight; next is part 5, calibration.
- Tonight: use a stronger PC and several phones; follow `docs/RUNBOOK_TONIGHT.md`.
- Open: phase 02b detector spike.
- Open: phase 03 is not formally closed.
