# 02 Record in the live run (R1)
Status: done
Delivers: RF08 (video), RNF04; Phase 04 A1 end to end; `frames.csv` `t_video` for a live run (contract 0.11.0).
Blocked by: 01

Capture feeds the recorder from its own thread (`Capture(on_frame=...)`). Recording is on by default;
`--no-record` turns it off (REQUIREMENTS C-02). `session.json` recording block: enabled, path, sha256 on
stop. `run.json` `counts.rec_dropped` is set when recording is on, null otherwise. `frames.csv`
`t_video` is the recorder's time for that frame's seq.

Tests: a file source run writes video.mkv with frames = captured - rec_dropped; sha256 in session.json
matches; `--no-record` leaves no video and null rec_dropped; t_video present for processed frames.
