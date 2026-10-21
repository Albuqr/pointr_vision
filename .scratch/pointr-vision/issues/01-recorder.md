# 01 Recorder (R1)
Status: done
Delivers: RF08 (video), RF09 (no annotations), RNF04; Phase 04 A1, A2, A5; R1 spec items FR-013 (instrument).
Blocked by: none

`FileRecorder` implements `Recorder` (services/edge/recording/types.py). Raw frames only, written on its
own thread from a bounded `rec_queue`; a full queue drops the frame and counts it (`rec_frames_dropped`).
Writes MP4 (mp4v). `t_video(seq)` gives the time of a recorded frame in the video (index / fps).
`stop()` joins, releases and returns `RecordingInfo` with the sha256 of the file.

Tests: A1 frame count = written frames, A2 frames carry no annotation, A5 sha256 matches the file,
a full queue is counted not blocked.
