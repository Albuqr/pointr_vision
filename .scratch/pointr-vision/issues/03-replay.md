# 03 Replay as a new run (R1)
Status: done
Delivers: RF09 / Phase 04 replay; RNF05 (MP4 and MOV); R1-A1, R1-A2; Phase 04 A3, A4.
Blocked by: 02

`python -m services.edge.main --replay <session_id | session folder | .mp4/.mov file>`.
A session id or folder adds a run to that session (`mode: replay`, `input.sha256` of the video); the
original run is not touched. A bare file starts a new session with a replay run. Replay reads at file
speed and processes every frame (capture back-pressure instead of drop-oldest). `frames.csv` `t_video`
is the container timestamp. A video whose sha256 differs from `session.json` is refused.

Tests: A3 original run files byte-identical; A4 MP4 and MOV replay; every frame processed; sha256 check.
