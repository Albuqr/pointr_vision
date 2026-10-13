# Backlog

Ideas and findings outside the current phase. One line each: what, why it came up, which
phase it might belong to.

| Item | Raised in | Possible phase |
|---|---|---|
| Cloud recording analysis service: user uploads a recorded video, a cloud GPU runs the pipeline as a replay and returns runs and reports. No real time, no local hardware needed. Possible separate product offering. Not the focus. See D-005 | Architecture review, 2026-10-07 | After 09, optional |
| ARCHITECTURE §3 lists `tests/edge/ sync_agent/ api/ e2e/`; not created (git does not track empty dirs). Create each when its first test lands | code-reviewer, phase 00 gate | 01+ |
| Contract drift tests compare keys, enums and event kinds only, not types/nullability or `runtime.device` pattern; `RecordingInfo` fields are not checked against ARCH §4. Extend when phase 03 adds CSV schemas | contract-guardian / test-auditor, phase 00 gate | 03 |
| DARK and FROZEN have no end event: the banner returns to OK silently, so a report cannot tell how long an episode lasted. Add an end event (e.g. `dark_cleared`/`frozen_cleared`, or the episode duration) - contract change with its own version bump and DECISIONS entry | A9b manual test, phase 01 | 03 |
| DroidCam disconnect signature: frozen (diff 0.00) followed within ~1 s (USB) or ~6 s (Wi-Fi) by dark (brightness 0.0); RF11 report could label it "feed dropped" instead of two separate problems | A8 manual test, phase 01 | 05 |
| Detector threshold (0.5) is below ByteTrack's `track_activation_threshold` (0.7): a person scored 0.5-0.7 is counted but never starts a track (D-016). Tune the pair with A6 footage, not before | Phase 02 build, D-016 | 03 |
| rfdetr warns "Model is not optimized for inference" and offers `optimize_for_inference()` (a TorchScript trace). Not an ONNX/OpenVINO accelerator, but it is a speed change: measure it only as part of the separate, approved speed step if the A7 baseline is too slow | Phase 02 build | after Q-02 |
| `runtime.device`: `cuda` is now written as `cuda:0` (D-020), but `mps`/`xpu` from `--device auto` would fail the schema. Widen the pattern or map them | contract-guardian, phase 02 gate | 03 |
| After a reopen the camera may come back at another size (e.g. a DroidCam client restart); frames change size with no event, while run.json holds the open-time size. Report a size change (event or line) | code-reviewer, phase 02 gate | 03 |
| `Processor.delays_ms` keeps one float per processed frame for the whole run (fine for a 2-minute benchmark). Phase 03 writes app delay per row to frames.csv; keep the in-memory list only for `--benchmark` | code-reviewer, phase 02 gate | 03 |
| Startup warnings from torch (`jit.script` deprecation) and rfdetr (DINOv2 positional encodings, "not optimized for inference") clutter the console; filter or document them | Phase 02 manual tests | 03 |
| Tracker `lost_track_buffer` = 1.0 s: occlusions longer than 1 s create new IDs (at ~2 fps even a short exit does, A6). Tune with basketball footage | Phase 02 manual tests | 11 |
| Hugging Face hub / transformers came in with rfdetr; verify a fully offline run (network disabled, weights cached) for RNF03 | Phase 02 install | 03 (A6) |
| The preview shows processed frames only, so its image updates at processing FPS (the window and banner stay responsive). If that is too choppy, show live capture frames with the latest boxes, at the cost of boxes lagging behind a moving person | Phase 02 design (D-017) | after A6 |
| `source_open_failed` and model-load failures leave no session folder: the session starts when the source opens (D-020). Start sessions earlier when the UI starts them | Phase 03 v0, D-020 | 06 |
| A hard kill (power cut, `taskkill /f`) leaves `run.json` `counts` null and loses up to 0.5 s of rows (flush, no fsync). Derive counts from frames.csv in the report, or write counts periodically | Phase 03 v0, D-020 | 05 |
| Credentials are stripped from the URL userinfo only; a token in the query string (`?token=`) is still written | Phase 03 v0, D-020 | 07 |
| If the writer thread is still busy past the 15 s close timeout, the fallback writes status `error` and the writer may later overwrite it with its own status | Phase 03 v0, D-020 | 03 |
| Phase 03 gate not complete: test-auditor review, A6 (offline run), A7 (10-minute soak with app delay plot) and `PHASE_03_REPORT.md` | Phase 03 v0, D-020 | 03 |
