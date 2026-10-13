Update this file at the end of every part.

# Current handoff

- Merged: v0 parts 1–4.
- Part 1: session logging and durable session files.
- Part 2: device selection and `docs/RUNBOOK_TONIGHT.md`.
- Part 3: multi-camera launcher, phone URLs, one process per camera, shared `group_id`.
- Part 4: movement report in pixels through a `PositionMap`.
- Part 4b: tracker lost-time, activation, and confirmation settings are configurable; defaults preserve 1 s.
- Real hardware: Ctrl+C in Git Bash stops all cameras cleanly.
- Real hardware: phone URL reports `source_lost` about 2 s after Wi-Fi loss and recovers.
- Phone constraint: one viewer per phone; an open browser tab blocks Pointr.
- i7-10510U, two cameras: 1.5–1.7 fps and 0.35–0.57 fps.
- Tracking: 17 track fragments in 130 s at about 1.5 fps; lost-track buffer is 1 s.
- Next: compare default vs 4 s tracking on webcam; part 5, calibration.
- Tonight: use a stronger PC and several phones; follow `docs/RUNBOOK_TONIGHT.md`.
- Open: phase 02b detector spike.
- Open: phase 03 is not formally closed.
