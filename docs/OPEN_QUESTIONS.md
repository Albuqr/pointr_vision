# Open questions

Not decided. Claude Code must not decide these silently; ask, or stop at the phase that
needs the answer.

| ID | Question | Needed by | Notes |
|---|---|---|---|
| Q-01 | What replaces "10 a 12 MP" in RNF01? | 01 (recorded), team text | MP measures photo resolution. Video needs resolution + fps (e.g. 720p/1080p at X fps), validated in the baseline |
| Q-02 | Numeric real-time criterion for RNF02 | after phase 02 baseline and phase 02b | Scope v2: rate is a measurement result, no target in advance. **Input, phase 02 CPU baseline (D-019):** RF-DETR Nano on i7-10510U, 1280x720 capture, headless: 1.89 fps, app delay p50/p95 547/641 ms at det-size 384 (USB); 2.42 fps, 437/484 ms at 320; Wi-Fi the same within noise; ~94% of frames dropped, delay bounded. About 4x is needed for ~10 fps. Phase 02b adds other runtimes/models and ID survival through short exits |
| Q-03 | ~~Local UI frontend stack~~ | 06 | **Closed: D-024.** FastAPI + React/Vite/TypeScript; built frontend committed, Node only for UI development |
| Q-04 | Video retention period after downgrade (RN12) | 09 | Configurable value either way |
| Q-05 | Locked-video mechanism (RNF11) | 09 | Proposed: per-file key wrapped by the server. Alternative: no local lock, only UI hiding (weaker, does not meet RNF11) |
| Q-06 | Object storage | 09 | MinIO on the VPS vs hosted S3-compatible bucket; VPS disk size limits MinIO |
| Q-07 | Keep weight, height, birth date? | 06 | Personal data under LGPD; minors likely. Keep only what an analysis uses |
| Q-08 | ~~Camera app for phases 01-12~~ | 01 | **Closed: D-010.** Wi-Fi or USB; DroidCam primary (webcam index), IP Webcam via URL, laptop webcam as dev fallback |
| Q-09 | ~~Session start: automatic on launch, or explicit start button?~~ | 03 | **Closed (2026-10-28):** answered in practice; Pointr Studio has explicit start and stop (D-025) |
| Q-10 | Resolve conflicts C-01 and C-02 in REQUIREMENTS.md | 08 / 04 | Team decision on the text |
| Q-11 | ~~What is `t0`, the zero of every monotonic time in a run?~~ | 03 | **Closed: D-011.** `time.monotonic()` when the capture thread starts for a run; one t0 per run. Storing its wall-clock anchor is in BACKLOG |
