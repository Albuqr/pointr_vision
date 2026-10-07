# Open questions

Not decided. Claude Code must not decide these silently; ask, or stop at the phase that
needs the answer.

| ID | Question | Needed by | Notes |
|---|---|---|---|
| Q-01 | What replaces "10 a 12 MP" in RNF01? | 01 (recorded), team text | MP measures photo resolution. Video needs resolution + fps (e.g. 720p/1080p at X fps), validated in the baseline |
| Q-02 | Numeric real-time criterion for RNF02 | after phase 02 baseline | Scope v2: rate is a measurement result, no target in advance |
| Q-03 | Local UI frontend stack | 06 | Options: plain HTML + HTMX, or React (already known). Keep it small |
| Q-04 | Video retention period after downgrade (RN12) | 09 | Configurable value either way |
| Q-05 | Locked-video mechanism (RNF11) | 09 | Proposed: per-file key wrapped by the server. Alternative: no local lock, only UI hiding (weaker, does not meet RNF11) |
| Q-06 | Object storage | 09 | MinIO on the VPS vs hosted S3-compatible bucket; VPS disk size limits MinIO |
| Q-07 | Keep weight, height, birth date? | 06 | Personal data under LGPD; minors likely. Keep only what an analysis uses |
| Q-08 | Camera app for phases 01-12 | 01 | DroidCam over USB (webcam index) vs IP Webcam over Wi-Fi (URL). Check free-tier resolution limits |
| Q-09 | Session start: automatic on launch, or explicit start button? | 03 | Phase 06 UI will need explicit start/stop |
| Q-10 | Resolve conflicts C-01 and C-02 in REQUIREMENTS.md | 08 / 04 | Team decision on the text |
| Q-11 | What is `t0`, the zero of every monotonic time in a run? | 03 | DATA_CONTRACTS says monotonic times are s since t0 but never defines t0 or stores its wall-clock anchor, so frames.csv cannot be aligned to wall time or video. Raised by contract-guardian at the phase 00 gate |
