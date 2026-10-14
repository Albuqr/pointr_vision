# Current handoff — 2026-10-14

## Merged into `main`

`main` is at `ba071db` (`origin/main`). Today's merge, `Merge branch 'fix/calibration-review': calibration review fixes`, includes the calibration correctness fixes and records the review findings for follow-up. The baseline already on `main` includes the v0 Studio and persistent camera-error work (`v0-studio-2026-10-13`), multi-camera capture, configurable tracker persistence, and calibration.

The review fixes cover corrupt calibration isolation, capture-resolution checks, projection validation, and resilient handling of malformed track rows. The review also deferred broad calibration documentation alignment; see `docs/BACKLOG.md`.

## Open branches

- `v0-cameras-studio` — seven commits ahead of `main`; camera settings UI and validation, config backup/write handling, event labeling, DNS pinning, and persistent Test camera failures. Code review against `main` passed; the requested test run on this branch passed (585 passed, 3 deselected). This is the next branch to merge.
- `v0-calibration` — one commit ahead of `main`: `0b0ab43`, recording calibration review findings and a fix plan. Check whether that review-only note should be merged with the next calibration follow-up.

`v0-tracker`, `v0-cameras`, `handoff-codex`, and `fix/calibration-review` have no unmerged commits relative to `main`; their relevant work is already integrated. Phase 02b and formal phase 03 closure remain open per `docs/PHASES.md`.

## Known risks and constraints

- **Phone link stability:** a phone stream can drop when Wi-Fi changes, the phone sleeps, or another viewer takes its single stream slot. Close browser test tabs before connecting Pointr; use a phone hotspot if the Wi-Fi isolates devices.
- **CPU throughput:** measured CPU-only multi-camera rates are low and vary substantially by camera. Treat FPS as hardware-dependent; use a CUDA-capable PC where possible, lower `det_size` to 320, and record fewer cameras if needed.
- **Tracker fragmentation:** at low processing rates, people who leave and return can receive new IDs. Increasing lost-track persistence did not fix the observed short-exit case; IDs are temporary and are not player identities.
- **Calibration:** a saved calibration is valid only while the phone remains fixed at the calibrated position and orientation. Recalibrate after moving it; verify with held-out points and a measured distance.
- **Second PC / App Control:** Windows App Control is blocking the PyTorch/torch runtime on the second PC. Until that machine permits the installed runtime, do not assume GPU detection is available there; resolve the policy block and verify `torch.cuda.is_available()` before a recording session.

## Exact next three commands

Run from the repository in Git Bash, after this handoff commit:

```bash
git switch main
git merge --no-ff v0-cameras-studio -m "Merge branch 'v0-cameras-studio': Studio camera settings"
python -m pytest -q -p no:cacheprovider
```

`docs/RUNBOOK_TONIGHT.md` recording and setup commands have not changed. Keep sessions outside the repository at `C:/pointr_sessions`.
