# Decisions

Write entries as decisions are made, including the ones that turn out wrong, and how that
was found. Never edit an old entry's reasoning; add a new entry that supersedes it.

Format: `D-NNN · date · title` / Context / Decision / Consequences / Status.

## D-001 · 2026-10-07 · Layers in one edge process; services only where the boundary is real
**Context.** The goal is iterable layers that can be added and tested independently.
**Decision.** Capture, perception, session, recording and reports are modules in one edge
process, separated by Protocols. Sync agent, cloud API, object storage and analytics are
separate processes/services.
**Consequences.** Frames are never serialised between local services, so the real-time path
stays short. Each layer is still testable alone through its interface.
**Status.** Accepted.

## D-002 · 2026-10-07 · Phone is only a video source; vision runs on the notebook
**Context.** Scope v2 excludes a native app from the first delivery and assumes a notebook.
**Decision.** Use an existing camera app (USB preferred). Detection and tracking in Python
on the notebook.
**Consequences.** RF01's "device has a camera" check is only partial until phase 13.
**Status.** Accepted.

## D-003 · 2026-10-07 · Initial detector and tracker
**Context.** Scope v2 lists RF-DETR and YOLOX as detector candidates, ByteTrack as baseline
tracker. RF-DETR Nano/Small/Medium are Apache-2.0; published latencies are measured on a T4
GPU with TensorRT FP16, not on this hardware.
**Decision.** Start with RF-DETR Nano, pretrained COCO, person class only, plus ByteTrack
from `supervision`. Switch only if measured quality or speed on this hardware justifies it.
**Consequences.** Baseline numbers come from phase 02 measurements, not from the vendor.
**Status.** Accepted, to be validated in phase 02.

## D-004 · 2026-10-07 · Local-first sync, adapted from Linear's sync engine
**Context.** Sessions must work offline and reach the server later without duplicates.
**Decision.** Persistent SQLite outbox; client-generated UUIDs; idempotency key on every
write; server-assigned `server_seq` with a pull cursor; LWW for registrations; append-only
session parts; separate resumable lane for video. No WebSocket broadcast in v1.
**Consequences.** Resends after crashes are safe. Live collaboration between devices is not
supported, and is not needed for one-device sessions.
**Status.** Accepted.

## D-005 · 2026-10-07 · Live inference stays local; cloud GPU only for offline analysis
**Context.** A cloud GPU may become available later. Live cloud inference would send the
stream over the internet in real time, breaking RNF03 (no internet dependency) and adding
network delay to every frame (RNF02).
**Decision.** Live detection and tracking run on the local PC. A cloud GPU, if used, runs
only offline analysis of recorded videos, as replay runs (new `run_id`), possibly offered
as a separate service for users without local hardware.
**Consequences.** No change to phases 01-09. The `Detector` Protocol and replay design
already allow a cloud worker later. Logged in BACKLOG.md; not on the current roadmap.
**Status.** Accepted, deferred.

## D-006 · 2026-10-07 · Contract 0.2.0: run.json carries its version and accepts stream input
**Context.** While writing the phase 00 schemas, two gaps showed up in contract 0.1.0:
`run.json` had no `contract_version` (only `session.json` did), so a run file read on its
own could not say which format it follows; and `run.json` `input.kind` allowed only
`camera | file`, while `session.json` `source.kind` also allows `stream`, so a live run
from an IP camera URL (Q-08) had no valid value.
**Decision.** Add `contract_version` to `run.json` and add `stream` to `input.kind`. Both are
additive, so the contract goes from 0.1.0 to 0.2.0 (minor). Schemas in `contracts/` are
written for 0.2.0; no file was ever written under 0.1.0.
**Consequences.** Phase 03 writes `contract_version` in every `run.json`. Readers can reject
a run file with an unknown version.
**Status.** Accepted.

## D-007 · 2026-10-07 · Python 3.11.9 virtualenv; setuptools as build backend only
**Context.** Phase 00 left the interpreter and the packaging setup open.
**Decision.**
- `.venv` uses Python 3.11.9 (the version run.json shows; safest for the phase 02 stack).
- `setuptools` is the build backend only, for `pip install -e ".[dev]"`.
**Consequences.** PyCharm and any other tooling point at `.venv`.
**Status.** Accepted.

## D-008 · 2026-10-07 · All §4 Protocols in each layer's types.py; session payloads provisional
**Context.** Phase 00 left open where the session and recording Protocols live.
**Decision.** All six Protocols from ARCHITECTURE §4 (plus `Frame`) are defined now, each in
its layer's `types.py` (`capture`, `perception`, `session`, `recording`), with no
implementations. `FrameRecord.app_delay_ms` is derived from `t_proc_end - t_recv`, not
stored.
**Consequences.** The Protocol method names and parameters follow §4 exactly. The payload
dataclasses of the session and recording layers (`SessionMeta`, `RecordingInfo`) are
provisional: they cannot yet carry run metadata (`run_id`, mode, input, detector, tracker,
runtime) or end-of-run counts that `run.json` needs. Phase 03 completes them (e.g. a
`RunMeta`, counts on close) with its own DECISIONS entry; that is expected, not a
regression.
**Status.** Accepted.

## D-009 · 2026-10-07 · Strict JSON Schemas, hand-written and checked against the contract
**Context.** Phase 00 left open how strict the schemas are, and how "generated from
DATA_CONTRACTS.md" is enforced.
**Decision.**
- Schemas are strict: every documented key is required (missing value = `null`), no
  additional properties. UUIDv4, UTC timestamps and sha256 are checked by regex, because
  jsonschema's `date-time` format needs an extra package that phase 00 does not allow.
- Schemas are written by hand. Tests check them against the JSON examples, enums and
  event kinds in DATA_CONTRACTS.md, so a change on one side without the other fails.
**Consequences.** Writers in phases 03-04 must emit every key, using `null` for unknowns.
**Status.** Accepted.

## D-010 · 2026-10-08 · Phone link: Wi-Fi or USB, DroidCam primary (closes Q-08)
**Context.** Phase 01 needs a camera app on the phone. Q-08 weighed DroidCam over USB (seen
as a webcam index) against IP Webcam over Wi-Fi (seen as a URL).
**Decision.** The phone connects over Wi-Fi or USB, and both must work. DroidCam is primary;
over either link the notebook sees it as a webcam index (`CameraSource`). IP Webcam (URL) is
supported through `StreamSource`. The laptop webcam is the development fallback.
**Consequences.** The notebook cannot tell whether DroidCam is on USB or Wi-Fi, so the link
is declared by the user (`--link`, D-012). Manual tests A7/A8 run over Wi-Fi and A8 is
repeated over USB. When the phone drops, the DroidCam client keeps its virtual webcam open
and may send a still placeholder, so a drop can show as `frozen_frames` instead of
`source_lost`; A8 accepts either and the report records which one each link produced.
**Status.** Accepted.

## D-011 · 2026-10-08 · t0 is per run: time.monotonic() when the capture thread starts (closes Q-11)
**Context.** DATA_CONTRACTS says monotonic times are seconds since `t0` but did not define
`t0` (raised by contract-guardian at the phase 00 gate).
**Decision.** `t0 = time.monotonic()` taken when the capture thread starts for a run. Each
run has its own `t0`; times from different runs are not comparable.
**Consequences.** `Frame.t_recv` and `HealthEvent.t_mono` stay raw `time.monotonic()`; the
layer that writes files subtracts the run's `t0`. The wall-clock anchor of `t0` is kept in
memory (`Capture.t0_wall`) but not yet stored in any file; where it goes is a phase 03
decision (BACKLOG).
**Status.** Accepted.

## D-012 · 2026-10-08 · Contract 0.3.0: source_open_failed, source.link, t0 per run
**Context.** Phase 01 reports open failures as `source_open_failed`, which was not an event
kind (BACKLOG). The session needs to record how the phone was connected (D-010), which the
notebook cannot detect. D-011 makes `t0` per run, while the contract said "the session's t0".
**Decision.** Additive changes, so 0.2.0 → 0.3.0 (minor):
- `source_open_failed` added to the `session.json` event kinds.
- `session.json` `source.link`: `"usb" | "wifi" | "builtin" | "file" | null`, from the
  `--link` CLI option; `null` when the option is not given.
- The conventions sentence now says monotonic times are relative to the **run's** `t0` (D-011).
**Consequences.** `SourceInfo` gains `link`. `run.json` changes only its version. No file
was ever written under 0.2.0.
**Status.** Accepted.

## D-013 · 2026-10-08 · Phase 01 capture design
**Context.** Phase 01 implements `FrameSource`, `SourceHealth` and the capture thread.
**Decision.**
- **End of a finite source.** `FrameSource.read()` returns `None` for "no frame this
  attempt"; a source that has ended (end of file) raises `SourceEnded` instead, so the end
  of a file is not reported as `source_lost`. The Protocol signature does not change.
- **seq** counts read attempts, including failed ones, so gaps in seq mark failed reads.
- **Reconnect lives in the source.** After a failed read, camera and stream sources release
  and reopen the device, at most once per second. The capture thread has no reconnect logic.
- **Queue.** `proc_queue(maxsize=1)`; when full, the capture thread discards the oldest
  frame and counts it as dropped. Only the capture thread puts, so no lock is needed.
- **Health.** Runs on the capture thread so it sees failed reads. One event per episode,
  at its start; `source_recovered` on the first good frame after `source_lost`. Dark
  frames reset the frozen streak (a covered lens is DARK, not DARK and FROZEN).
- **Initial thresholds (untuned):** `lost_reads=30`, `frozen_diff=0.5` (mean abs diff of
  consecutive BGR frames), `frozen_secs=2.0`, `dark_level=20` (mean BGR, 0-255),
  `dark_secs=1.0`. On the synthetic fixtures the moving clip's mean abs diff is about 1.2
  and the frozen and black clips' is 0. All are CLI flags and printed at startup; values
  tuned on real footage are recorded in a later entry.
**Consequences.** Phase 03 swaps the console `on_event` for the session writer.
**Status.** Accepted; thresholds to be tuned in the phase 01 manual tests.

## D-014 · 2026-10-08 · Phase 01 gate fixes: time-bounded source_lost, null t_mono before t0
**Context.** At the phase 01 gate, code-reviewer found that `source_lost` counted only
consecutive failed reads. A stalled `StreamSource` read blocks for its read timeout (2 s), and
every following reopen blocks for up to the open timeout (5 s). Reaching 30 reads would take
about 150 s, and all that time the preview would show OK. contract-guardian found that
`source_open_failed` happens before any run's `t0`. The contract did not say that `t_mono` is
then `null`, and `HealthEvent.t_mono` could not be `None`.
**Decision.**
- `source_lost` fires after `lost_reads` consecutive failed reads **or** after failing for
  `lost_secs` (default 2.0 s, CLI `--lost-secs`), whichever comes first. This supersedes
  PHASE_01's "N consecutive failed reads" definition. The time counts from the last good
  frame, so a blocking read's own wait is included; a webcam's fast failures still hit the
  count. (A first draft counted from the first failed read; code-reviewer's simulation with
  blocking fakes showed that adds a read timeout, so the "about 7 s" stated then was wrong.)
- `t_mono` is `null` for events that precede the run's `t0`, e.g. `source_open_failed`.
  `HealthEvent.t_mono` is `float | None`. This clarifies contract 0.3.0, which no released
  build or file uses yet, so it stays 0.3.0.
- `Capture.stop()` waits 8 s by default, longer than the slowest blocking stream read.
- Ctrl+C and main-loop exceptions become `interrupted` / `error` events with non-zero exit
  codes (130 / 1), not a bare message or a traceback.
- `SourceEnded` and `utc_now` move to `capture/types.py`. Generic code no longer imports
  from the concrete sources module, and ARCHITECTURE §4 documents the `SourceEnded` signal.
**Consequences.** The stream values (2 s read timeout, 5 s open timeout) are configuration
only; no stream loss time has been measured on hardware. A8 over IP Webcam will show it.
**Status.** Accepted.

## D-015 · 2026-10-08 · Phase 02 API verification: rfdetr 1.11.2, supervision 0.30.8, torch CPU
**Context.** PHASE_02 requires the `rfdetr` and `supervision` APIs to be checked against the
installed versions before coding. They are not installed yet (installing them is the
dependency approval of this phase). These facts were read from the source of the exact wheels
that would be installed: `rfdetr-1.11.2-py3-none-any.whl`, `supervision-0.30.8-py3-none-any.whl`
and `trackers-2.6.1-py3-none-any.whl`, from PyPI on 2026-10-08. The pip resolve was a dry run.
Re-check after install with `help()`.
**Findings.**
- **GPU.** None. `nvidia-smi` is not present. The notebook has Intel UHD Graphics (no
  CUDA). Phase 02 baseline numbers are CPU numbers.
- **Model class.** `rfdetr.RFDETRNano` (`rfdetr/variants.py`), config `RFDETRNanoConfig`:
  `resolution=384`, `patch_size=16`, `num_windows=2`, `positional_encoding_size=24`,
  `pretrain_weights="rf-detr-nano.pth"`, `num_classes=90`. The constructor takes config fields
  as keyword arguments, e.g. `RFDETRNano(device="cpu")`. `device` defaults to an auto-detected
  value (`rfdetr.config._detect_device`: the available accelerator, else `"cpu"`).
- **Weights.** On construction, `rf-detr-nano.pth` is downloaded once to the model cache
  (`~/.roboflow/models`, or `RF_HOME`) from `storage.googleapis.com/rfdetr/nano_coco/...`
  and checked against an md5 in `rfdetr/assets/model_weights.py`. Loading uses
  `torch.load(weights_only=True)` unless `trust_checkpoint=True` is passed.
- **predict.** `predict(images, threshold=0.5, shape=None, patch_size=None,
  include_source_image=True, **kwargs)` returns a `supervision.Detections` for a single
  image. Images are expected in **RGB**. A uint8 HxWx3 numpy array is accepted, and a
  negative-stride view such as `bgr[:, :, ::-1]` is copied internally. The image is resized
  (stretched, no letterbox, bilinear) to `shape=(h, w)`, or to `(resolution, resolution)` when
  `shape` is None. Both sides must be divisible by `patch_size * num_windows` (32 for Nano),
  otherwise it raises `ValueError`. The backbone interpolates its positional encoding at run
  time (`interpolate_pos_encoding`), so another `shape` works with the 384 weights. Boxes come
  back in source-image pixels (`target_sizes` = original size). Detections are kept when
  `score > threshold` (strict).
- **Person class.** For the pretrained COCO checkpoint, `class_id` is the raw COCO category ID
  (1-90, sparse), not a 0-based index. Person is `class_id == 1`
  (`rfdetr/assets/coco_classes.py`). `detections.data["class_name"]` also carries `"person"`.
- **supervision ByteTrack.** `supervision.ByteTrack(track_activation_threshold=0.25,
  lost_track_buffer=30, minimum_matching_threshold=0.8, frame_rate=30,
  minimum_consecutive_frames=1)`, updated with `update_with_detections(detections) ->
  Detections` (with `tracker_id`). It requires `confidence`. It returns only tracks matched
  to a detection in the current frame. The lost buffer is counted in calls, scaled by
  `frame_rate / 30`. **The class is deprecated since supervision 0.28.0 and is removed in
  0.31.0.** The deprecation notice points to `ByteTrackTracker` in the `trackers` package.
- **trackers ByteTrackTracker** (alternative). `trackers.ByteTrackTracker(lost_track_buffer=30,
  frame_rate=30.0, track_activation_threshold=0.7, minimum_consecutive_frames=2,
  minimum_iou_threshold=0.1, high_conf_det_threshold=0.6)`, with `update(detections,
  frame=None, timestamp=None) -> sv.Detections`. Immature tracks get `tracker_id == -1`.
  `timestamp` (absolute seconds) makes the lost buffer time-based instead of per call.
  Passing `frame` only emits a warning.
- **torch CPU wheel.** `torch 2.14.1+cpu` and `torchvision 0.29.1+cpu` resolve for
  cp311/win_amd64 from `https://download.pytorch.org/whl/cpu`. rfdetr needs `torch>=2.2.0`,
  `torchvision>=0.17.0` and `transformers>=5.1,<6`.
**Decision.** None yet. These are the facts the phase 02 plan is built on. The choices
(tracker package, det-size mechanism, threading) are recorded in a later entry after approval.
**Status.** Facts recorded. Re-verified after install (D-016) with `inspect.signature` and the
config defaults: no difference.

## D-016 · 2026-10-08 · Phase 02 dependencies, pinned; ByteTrack from `trackers`, not `supervision`
**Context.** Phase 02 needs a detector and a tracker. D-015 found that `supervision.ByteTrack`,
the tracker named in PHASE_02 and D-003, is deprecated and is removed in supervision 0.31.0.
The developer approved the dependencies on 2026-10-08, on these conditions: exact pins,
licences recorded, the CPU torch build, and the existing tests passing after the install.
**Decision.**
- Runtime dependencies, pinned exactly in `pyproject.toml`:

  | Package | Version | Licence | Why |
  |---|---|---|---|
  | torch | 2.14.1 (+cpu wheel) | `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT` (wheel metadata) | rfdetr runtime |
  | torchvision | 0.29.1 (+cpu wheel) | BSD | rfdetr runtime |
  | rfdetr | 1.11.2 | Apache-2.0. The Nano config states `license="Apache-2.0"` for the model | detector |
  | supervision | 0.30.8 | MIT | `Detections` type returned by rfdetr and taken by trackers |
  | trackers | 2.6.1 | Apache-2.0 | ByteTrack |

  All five allow use in a private product. torch and torchvision come from
  `https://download.pytorch.org/whl/cpu`, installed **before** `pip install -e ".[dev]"`.
  pyproject cannot name that index, so the order is in README and CLAUDE.md. `torch==2.14.1`
  matches the installed `2.14.1+cpu`, because a pin without a local label ignores it.
- **Tracker: `trackers.ByteTrackTracker`** instead of `supervision.ByteTrack`. This deviates
  from PHASE_02 and D-003 ("ByteTrack from supervision"). It is the same algorithm, from the
  maintained package that the supervision deprecation notice points to. Checked in the
  installed source (`trackers/core/base.py`, `trackers/utils/base_tracklet.py`):
  - With `update(dets, timestamp=t)`, a lost track is kept for `maximum_time_without_update
    = lost_track_buffer / 30.0` **seconds** (default `lost_track_buffer=30`, so 1.0 s),
    measured with `time_since_update_seconds`. This holds at any processing rate. Without
    timestamps it counts calls. Pointr passes `Frame.t_recv`. `frame_rate` (default 30) only
    converts elapsed seconds into Kalman steps.
  - **No observed/predicted state.** `update()` returns the current frame's detections,
    indexed, with `tracker_id` (`-1` for immature or unmatched ones). Coasting tracks are not
    returned and no per-track state is exposed. `TrackObs.state` is therefore `None`, and the
    `tracks.csv` `state` column will be empty, as the contract allows. `TrackObs.confidence`
    is the matched detection's score.
  - Defaults kept and recorded: `lost_track_buffer=30`, `frame_rate=30.0`,
    `track_activation_threshold=0.7`, `minimum_consecutive_frames=2`,
    `minimum_iou_threshold=0.1`, `high_conf_det_threshold=0.6`.
- **Install footprint**, measured: `.venv` grew from 236 MB to 1363 MB (+1127 MB). The largest
  are torch 544 MB, transformers 120 MB and scipy 119 MB. 53 packages were added and
  setuptools was upgraded from 65.5.0 to 78.1.0. The dry run had predicted 84; the real
  install resolved 78.1.0. pip install -e ".[dev]" and the 171 earlier tests passed after it.
- **Transitive packages that are not detection or tracking**, pulled by rfdetr (through
  transformers) and supervision: `transformers` (the DINOv2 backbone code; imported, about
  10 s at import), `huggingface_hub` + `hf-xet` + `httpx`/`anyio` (Hugging Face Hub client),
  `tokenizers`, `regex`, `safetensors` (NLP tokenizer and weight formats), `typer`/`click`/
  `rich`/`shellingham` (CLI tooling), `matplotlib` and its font and plot libraries, and `av`
  (PyAV video I/O). No training or logging SDK is installed: rfdetr's `train`, `loggers`,
  `onnx` and similar extras are not requested.
**Consequences.**
- With the detector threshold at 0.5, a person scored in [0.5, 0.7) is detected but never
  **starts** a track (`track_activation_threshold=0.7`). Scores in [0.5, 0.6) only extend
  existing tracks (the low-confidence stage). The HUD shows people (detections) and tracks
  separately, so A6 shows it if it happens. The values are not tuned in this phase.
- `supervision` stays a direct dependency, because the tracker adapter builds
  `sv.Detections`.
**Status.** Accepted.

## D-017 · 2026-10-08 · Phase 02 perception design
**Context.** Phase 02 adds detection and tracking. On this notebook all inference runs on
the CPU (D-015), so processing is expected to be slower than capture. The developer added six
BACKLOG items to the scope.
**Decision.**
- **Threading.** A `perception` thread (`Processor`) takes frames from `proc_queue`, then
  runs detect and track and measures `t_proc_start`, `t_proc_end` and app delay
  (`t_proc_end − t_recv`). The capture thread is unchanged (drop-oldest, D-013), so when
  processing is slower, frames are skipped and counted, and app delay stays bounded instead
  of a backlog building up. The preview stays on the main thread (OpenCV windows need it).
  It shows the **latest processed frame with its own boxes**, so boxes always match the
  image, and it refreshes the banner and HUD every 30 ms. The image therefore changes at
  processing FPS. The alternative, live frames with the last boxes, is in BACKLOG.
- **Detector input size.** `--det-size` is passed to rfdetr's `predict(shape=(s, s))`, which
  resizes (stretches) the frame to a square for inference. Boxes come back in frame pixels.
  The model keeps its 384 configuration and pretrained weights. The positional encoding is
  interpolated at run time (D-015). Default: the model's resolution (384). The CLI rejects
  values that are not multiples of 32 before the slow model load; `load()` checks that 32
  matches the real config.
- **Person filter.** `class_id == 1` (raw COCO ID, D-015) and `confidence >= threshold`. rfdetr
  already keeps only `score > threshold`. The second check makes "all above threshold" true
  by construction.
- **Warm-up.** The model is loaded and run once on a black frame after the source opens and
  before capture starts, so the first, slower call is not in the measurements. Load and
  warm-up times are printed. A model load failure (e.g. no network for the first weights
  download) is an `error` event with `t_mono` null (before t0, as D-014), exit code 1.
- **Capture size.** Cameras get `CAP_PROP_FRAME_WIDTH/HEIGHT` set after opening, on every
  (re)open. `SourceInfo` reports what `get()` returns, i.e. what the camera accepted. The
  benchmark prints the size of the frames actually processed. Streams and files deliver their
  own size; nothing is requested from them.
- **`--camera-api` removed.** `CAP_ANY` picks MSMF on this notebook and opened DroidCam in
  phase 01. DSHOW could not open by index on opencv 5.0. Opening by device name would be new
  code for a backend nothing needs.
- **HUD.** Phase 01 drew the status text twice (a thick black outline under thin white
  text), which read as doubled text. Now: one white text pass on a filled black strip, on
  two lines, so it fits a 640-wide frame.
- **`--no-detect`.** Runs the same loop without a detector (capture only). Used to re-run
  phase 01 A9/A9b at the new resolution without the CPU load, and to keep CLI tests free of
  model weights. A `conftest.py` guard fails any default test that imports rfdetr.
- **`--benchmark SECONDS`.** Stops after SECONDS (or at end of file, `q`, Ctrl+C) and prints
  run time, frame size, det-size, device, CPU, captured, processed, processing FPS
  (processed / time from first processing start to last end), dropped and drop rate
  (dropped / captured), failed reads, and app delay p50/p95/max over every processed frame.
- **Clean install check.** A fresh clone with the README commands, in a new venv, gives
  `torch 2.14.1+cpu`, `cuda.is_available() False`, and 171 tests passing (at commit
  `3804031`).
**Consequences.** No contract change: phase 02 writes no files. `run.json` needs fields for
det-size and the requested capture size before phase 03 writes it (BACKLOG). Q-02 (numeric
RNF02 target) stays open until the A7 baseline exists.
**Status.** Accepted; the shutdown, load order and threshold points are amended by D-018.

## D-018 · 2026-10-08 · Phase 02 gate fixes: drain at shutdown, model before source, "above" threshold
**Context.** At the phase 02 gate, contract-guardian (MAJOR) and code-reviewer (MINOR) found
that a run stopped mid-stream (`--benchmark` end, `q`, Ctrl+C) left the frame waiting in
`proc_queue` neither processed nor counted, so `captured = processed + dropped + 1`. That
breaks rule 6 and would put wrong counts into `run.json` in phase 03. test-auditor (MAJOR)
showed the A3 tests passed with an adapter that numbered tracks by list position. The fix
round's first version, swapping the detection order on odd frames, still passed that
mutation: the library returns tracks in track order, not detection order. Only a person
leaving the frame exposes it.
**Decision.**
- **Shutdown drains.** `Processor.stop()` now waits for the thread to exit on its own:
  capture stops first, `capture.done` is set, the processor handles the frame still in
  `proc_queue` and finishes. Only past the timeout is it told to stop. Frames still left
  after that, or the frame in hand when the detector raises, are counted in `unprocessed`,
  which is printed in the summary and the benchmark. So `captured = processed + dropped +
  unprocessed` holds whenever both threads stop in time, with `unprocessed = 0` on a normal
  stop. If either thread does not stop in time, the summary warns that counts may be short
  (corrected wording after the code-reviewer re-review; the first version said "always").
  Without a stopped capture the processor is not waited for: there is no last frame to drain.
- **Model loads before the source opens.** `open_source()` still checks the ref first (bad
  files fail fast), then the model loads and warms up (at `--width x --height`), and only
  then does the device open. A stream no longer sits unread for the load time and buffers
  stale frames with fresh `t_recv` stamps. The cost: a camera index that does not exist is
  reported after the model load, not before.
- **Threshold is strict.** The detector keeps `confidence > threshold`, matching the contract
  ("above threshold") and rfdetr's own filter. This supersedes D-017's `>=`.
- **Shutdown guards.** Each stop step and the summary have their own Ctrl+C guard. A
  processing thread that does not stop is reported, like capture. `--benchmark` and other
  float flags reject `nan` and `inf`. The preview receives `latest()` and `done` instead of
  the `Processor`. The benchmark gets det-size and device as values, not from the detector.
  FPS and drop rate are computed by the pure function `rates()`.
- **Correction to D-016.** "about 10 s at import" was one measurement during verification
  (2026-10-08) of importing `rfdetr`, `supervision` and `trackers` together: 10.5 s. It was
  not transformers alone. The phase 02 report records it.
**Consequences.** Tests: a mid-stream stop, the detector failure accounting, model-load
failure (event, null `t_mono`, exit 1, source never opened), the delivered-size CLI line, the
benchmark stopping after its seconds, and the label pixels. A3 now has one person leaving
while the other must keep their ID, and that test fails under the position mutation.
**Status.** Accepted.

## D-019 · 2026-10-08 · Phase 02 CPU baseline
**Context.** PHASE_02 A7 asks for a processing baseline, and Q-02 (the numeric RNF02 target)
waits for it. The developer ran the benchmark matrix on the dev notebook: Dell Latitude 3410,
i7-10510U, 16 GB, Intel UHD (no CUDA), Windows 11 Pro, AC power, "Best performance". The phone
was a Samsung S22 through the DroidCam client, one active source. Software: torch 2.14.1+cpu
with 4 threads, rfdetr 1.11.2 Nano, trackers 2.6.1. Each run was `--benchmark 120`, headless,
with frames delivered at 1280x720 on both links. In every run `captured = processed +
dropped`, with 0 unprocessed and 0 failed reads.
**Measurements.**

| Run | Link | det-size | Proc FPS | App delay p50 / p95 / max (ms) | Dropped (% of captured) |
|---|---|---|---|---|---|
| M1 (A7) | USB | 384 | 1.89 | 547 / 641 / 766 | 93.7% |
| M2 | USB | 320 | 2.42 | 437 / 484 / 625 | 91.9% |
| M3 | Wi-Fi | 384 | 1.78 | 578 / 677 / 938 | 94.0% |
| M4 | Wi-Fi | 320 | 2.44 | 422 / 500 / 547 | 91.8% |

**Decision.** Record this as the phase 02 CPU baseline; it is the input to Q-02, which is not
decided here. Conclusion from the runs:
- The link (USB vs Wi-Fi) makes no measurable difference.
- The detector on the CPU is the whole bottleneck. det-size 320 gives +28% processing FPS
  over 384.
- The pipeline is healthy: app delay stays bounded (p95 < 0.7 s) while about 94% of frames
  are dropped, as the drop-oldest design intends (D-013, D-017).
- About 4x is needed for ~10 fps. That needs a different runtime or model, not tuning of this
  pipeline.
**Consequences.** Next is phase 02b, a detector performance spike: RF-DETR Nano via
OpenVINO/ONNX against YOLOX-Nano/Tiny on a recorded clip, plus ID survival through short
(<1 s) exits at each speed. Those results also feed Q-02. Adding an accelerator or another
model needs its own approval (phase 02 rule). At ~2 fps, ByteTrack's 1.0 s lost-track buffer
is about two processed frames, so IDs do not survive exits or occlusions (A6; BACKLOG).
**Status.** Accepted (measurement). Q-02 stays open.

## D-020 · 2026-10-13 · Phase 03 v0 core: session files, writer thread, contract 0.4.0
**Context.** An urgent v0 must log sessions tonight on a stronger PC with several phones and
people. Phase 03's core (files, writer, final status) is built now, ahead of 02b, on branch
`v0-logging`. Several phase 03 BACKLOG items had to be settled before `run.json` could be
written.
**Decision.**
- **Contract 0.4.0** (minor, additive plus nullability). `run.json` gains `t0_wall`,
  `counts.unprocessed`, `input.requested_width/height`, `detector.det_size`, `health` (the six
  source-health thresholds) and `runtime.packages` (opencv, numpy, torch, supervision).
  `detector`, `tracker` and `runtime.device` are `null` with `--no-detect`; `counts` is `null`
  until the run ends, so a crashed run never shows unmeasured counts. The example's tracker
  package is `trackers` (D-016). `frames.csv` `n_detections`/`n_tracks` are empty with
  detection off; `seq` gaps also mean unprocessed frames; `dropped_total` is the drop count
  when the frame was taken for processing (snapshotted in the processing loop). `source.link`
  must be `file` exactly when `kind` is `file` (or `null`): the CLI rejects a contradiction
  before the model load and the schema enforces it. `user:password@` is stripped from stream
  refs before writing. `sessions/device_id` holds the device's UUIDv4 (one identity per
  `--out` folder). Minor bump although some fields became nullable and `dropped_total`
  was redefined: no file was ever written under 0.3.0 (the writer is new here).
- **Run clock is `time.perf_counter()` (amends D-011).** contract-guardian measured
  `time.monotonic()` on this Windows notebook: `GetTickCount64`, 15.6 ms resolution, so
  `app_delay_ms` took only the values 0 and 16 on the fixture clip. `perf_counter` is
  QueryPerformanceCounter (100 ns, monotonic). Every run time (capture, health, sources,
  processing, writer) switched together so they stay on one clock.
- **Protocol change (D-008 completed).** `SessionWriter.start(meta, run: RunMeta)`,
  `set_t0(t0, t0_wall)`, `close(status, counts: RunCounts)`.
- **Session starts when the source opens.** Failures before that (bad ref, model load,
  `source_open_failed`) print and exit non-zero, leaving no folder. `source_open_failed` stays
  in the contract for when a session starts before its source (phase 06 UI).
- **Writer.** One thread owns all file handles; queue of 4096 items. On a full queue the
  producer waits instead of dropping rows (capture then drops frames, which are counted), and
  one `writer_backlog` event is logged per episode (an episode ends when the queue empties).
  CSVs are flushed every 0.5 s; `session.json` is rewritten when events arrive; JSON writes
  go through a temp file and `os.replace`, retried when Windows/OneDrive holds the file. No
  fsync: survives a process crash, not a power cut. If the writer thread dies, producers do
  not raise; items are counted and `close()` writes `session.json` with status `error` and an
  `error` event from the main thread.
- **Events.** Capture, processing and main-thread events go through the writer queue with
  `t_mono` converted to seconds since the capture thread's `t0`; `null` only before `t0`.
- **Final status.** `ended`, or `interrupted` on Ctrl+C, or `error` on a main-loop exception,
  a capture/processing error, a thread that did not stop in time (also logged as an `error`
  event, so the shortfall is in the data), or a failed writer. `close()` waits on an Event,
  not `Thread.join()` (an interrupted join can make `is_alive()` report a running thread as
  stopped, seen in the test). Once shutdown starts, `main` replaces the Ctrl+C handler with
  a "please wait" message until the session is saved; every wait in the shutdown is
  bounded (capture 8 s, processing 10+1 s, writer 15 s).
- **Gate fixes (reduced gate: code-reviewer, contract-guardian, reliability-reviewer).**
  A failed mid-run JSON rewrite (file held by OneDrive or an editor longer than the
  retries) killed the writer thread and lost every later row (reliability BLOCKER, also
  MAJOR in the other two): it is now printed and retried on the next tick; only CSV and
  final writes are fatal. A dead writer now ends the run with status `error` instead of
  running on unsaved (MAJOR). A third Ctrl+C could escape the shutdown before the final
  write (MAJOR): fixed by the handler above. The coarse clock (MAJOR): fixed above.
  MINOR and NIT findings are in BACKLOG.
**Consequences.** Phase 03 is not closed: test-auditor, A6 (offline) and A7 (10-minute soak)
and `PHASE_03_REPORT.md` are pending, so no `phase-03` tag. 02b stays open. Remaining phase 03
items are in BACKLOG.
**Status.** Accepted.

## D-021 · 2026-10-13 · v0 runbook: device selection, `runtime.gpu`, contract 0.5.0
**Context.** Tonight's recording runs on a stronger PC, probably with an NVIDIA GPU. The device
choice existed (`--device auto|cpu|cuda`, handed to rfdetr), but the notebook never had a GPU,
so the CUDA path was untested, the GPU name was not recorded, and a forced `cuda` without a
GPU would have failed somewhere inside rfdetr.
**Decision.**
- **Pointr resolves the device itself**, before the model load (`main.resolve_device`):
  `auto` is `cuda:0` when `torch.cuda.is_available()`, else `cpu`; `cpu` forces the CPU;
  `cuda` without a usable GPU prints `error: --device cuda but torch <version> cannot use a
  CUDA GPU ...` to stderr and exits 1, before the slow load. The resolved device is passed to
  rfdetr explicitly (`RFDETRNano(device=...)`), so `auto` no longer defers to rfdetr's
  detection, which could pick `mps`/`xpu`. This closes the BACKLOG item about `mps`/`xpu`
  failing the schema. With `--no-detect` the device is not resolved or printed.
- The startup line `device: cuda:0 (<GPU name>)` or `device: cpu (no CUDA GPU in use)` is
  printed before the model load.
- **Contract 0.5.0** (minor, additive): `run.json` `runtime.gpu`, the CUDA GPU's name from
  `torch.cuda.get_device_name(0)`, `null` on cpu and with `--no-detect`. `runtime.device`
  stays `cpu | cuda:N`. Only device 0 is used.
- **Torch wheels for CUDA.** Checked on 2026-10-13 on download.pytorch.org: `torch==2.14.1`
  and `torchvision==0.29.1` exist for cp311 / win_amd64 on `cpu`, `cu126`, `cu130` (and
  `cu132`); `pip install --dry-run` resolves `+cu126` and `+cu130`. `cu118`, `cu121`, `cu124`,
  `cu128` and `cu129` have no `2.14.1` wheels for it. No pin changes: the local label is
  ignored by `torch==2.14.1`. README and the runbook offer `cu130` and `cu126`. **Not
  verified:** a CUDA run (the dev notebook has no GPU); the CUDA path is covered by tests
  with `torch.cuda` mocked only.
- **Startup noise filtered** in `RFDETRDetector.load` by message only: the `torch.jit.script`
  FutureWarning, rfdetr's `plus extras` ImportWarning, and two rfdetr log lines ("not
  loading DINOv2 backbone weights", "Model is not optimized for inference"). Other warnings
  and our own messages are untouched. rfdetr's INFO line about the weights' md5 remains (printed twice per load).
- **Review fixes (code-reviewer).** The CUDA check in the docs runs a real GPU calculation
  (`is_available()` alone does not prove the GPU can run kernels; GTX 9xx/10xx may not be
  supported by the CUDA 13 build). The phone-URL path for a second phone is documented as
  untested on hardware (PHASE_01_REPORT: StreamSource not exercised on a real phone). A
  failing device check of any kind exits 1 with `error: ...`.
**Consequences.** `docs/RUNBOOK_TONIGHT.md` and README "Install on a new PC" are the
operating instructions for the v0 recording. The first real GPU run will show whether
`cuda:0` works with rfdetr 1.11.2 end to end.
**Status.** Accepted.

## D-022 · 2026-10-13 · v0 multi-camera: one process per camera, contract 0.6.0
**Context.** Tonight: one PC, several phones. Real hardware, verified today: a phone URL
(`http://10.10.8.158:4747/video`, DroidCam app over Wi-Fi) opens, delivers 1280x720, reported
25 fps, about 28 fps captured, and the session ended cleanly. A phone serves ONE viewer: with a
browser tab open on the same URL, OpenCV failed with `source_open_failed` ("DroidCam is Busy or
Unavailable" in the browser); closing the tab fixed it.
**Decision.**
- **One process per camera, no cross-camera fusion.** Each camera is a normal `services.edge.main`
  process with its own session, run, clock (`t0`), model and writer. A launcher
  (`scripts/run_cameras.py`) starts them from a JSON config and supervises them. Nothing links
  frames across cameras; `group_id` only says which sessions were recorded together.
- **Contract 0.6.0** (minor, additive): `session.json` `camera_id` (`--camera-id`, 1-32 of
  `A-Za-z0-9_-`) and `group_id` (`--group-id`, 1-64 of `A-Za-z0-9_-`; the launcher writes a
  UUIDv4), both nullable. The session folder is `<camera_id>_<session_id>` (or `<session_id>`
  without a camera id): the id is a safe file-name token, checked in the CLI and again in the
  writer, so a camera id cannot walk out of `--out`. The folder name is never parsed.
- **Default input is the phone URL for every phone, no PC client.** The DroidCam client's virtual
  webcam stays as the fallback for one phone. The launcher refuses two entries with the same
  source (same host and port for URLs, same index for cameras): one viewer per phone.
- **Stop reaches children through their stdin.** The launcher starts each child with
  `--stop-on-stdin`; any input or the end of the pipe makes the child call
  `_thread.interrupt_main()`, i.e. exactly the Ctrl+C path (status `interrupted`, final write).
  The child **polls** stdin (`PeekNamedPipe` on Windows, `select` elsewhere) and never blocks
  in a read: found on this notebook, a thread blocked reading stdin hung `import scipy` (the
  model load) in the main thread, the child never printed its `session:` line, and the launcher
  timed out. A test reproduces it without the model.
  Chosen over `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` because that needs a SIGBREAK
  handler in the child, only works for console children, and the child still has to be told in
  band; stdin works the same on every OS, is testable with fake children, and the end of the
  pipe also stops children when the launcher itself dies. Children are started in their own process
  group and, on Windows, without a console (`CREATE_NO_WINDOW`), POSIX: their own session, so
  no console event (Ctrl+C, Ctrl+Break, closing the window) reaches them: they stop through
  one path, and ignore SIGBREAK as well. A launcher that dies closes the pipes and the cameras
  stop themselves (tested with a hard-killed launcher and real children). Killing is the last resort after
  `--stop-timeout` and is shown in the final table (`killed`).
- **`device_id` race fixed.** `<out>/device_id` is created with an exclusive create (`open(...,
  "x")`); the process that loses the race re-reads the winner's value (retrying while the file is
  still empty). A file that stays unreadable or invalid is replaced with a warning on stderr
  instead of silently.
- **`main.run`: starting the capture and processing threads moved inside the `try`**, so a stop
  request that lands right after the `session:` line (the launcher makes this likelier) still
  ends the session as `interrupted` (BACKLOG item from the phase 03 gate).
- **Setup window.** A stop between the session folder and the main `try` is held back
  (`hold_ctrl_c`) and raised inside the `try`, so the session ends `interrupted`, not
  `running`. Console output that fails (`OSError`: the launcher is gone) never stops a session:
  `print_event` swallows it and the event goes to the writer first. `Capture.stop` and
  `Processor.stop` accept a thread that never started.
- **Launcher output.** Lines are written with `errors=backslashreplace`; a reader thread
  cannot die on an unencodable line (reproduced by reliability-reviewer: a child then blocks on
  a full pipe and is killed). The table adds `errors` (count of `error` events) and rows for
  cameras not started; the exit code is 0 only if every session ended or was interrupted with
  no error event. Relative `--out` and file sources are resolved against the launcher's folder.
  `device_id` is never overwritten when it is merely unreadable (OneDrive lock).
**Gate (code-reviewer, contract-guardian, reliability-reviewer).** contract-guardian: no
BLOCKER/MAJOR; nits fixed or in BACKLOG. code-reviewer: MAJOR Ctrl+Break kills children (fixed:
no console, SIGBREAK ignored); MAJOR "Ctrl+C under mintty not proven": **open, it is the manual
check** (keyboard Ctrl+C in Git Bash, two cameras). reliability-reviewer: MAJOR launcher stdout
encoding kills a reader (fixed, test). MINORs fixed: setup window, broken pipe on exit, launcher
cwd/relative paths, `taskkill` by full path, deadline restart on repeated Ctrl+C, credentials in
launcher output, leading `-` in values, `not started` rows, `error` events; rest in BACKLOG.
**Not decided / out of scope.** Camera fusion, calibration, movement report. Whether several
processes on one GPU is fast enough is not measured here: the manual check records only that the
sessions are valid. RAM per process is measured on the dev notebook (CPU) and written in the
runbook.
**Manual check (2026-10-13, real hardware, passed both runs).** Laptop webcam + phone URL: Ctrl+C
from Git Bash reached all children, both sessions `interrupted` (this closes the open mintty
finding). Wi-Fi off on the phone: `source_lost` about 2 s later (FFmpeg read timeout 2.1 s),
`source_recovered` when it returned, the laptop camera unaffected. CPU contention on the
i7-10510U: 1.5-1.7 fps (laptop) and 0.35-0.57 fps (phone URL) against about 2-2.4 fps alone;
the second model load took 27-30 s. Runbook: CPU-only PC, at most 2 cameras with det_size 320.
**Status.** Accepted; merged to main.

## D-023 · 2026-10-13 · v0 movement report per person, contract 0.7.0
**Context.** Tonight's recordings need a readable result per camera. The processing rate on
the dev CPU is low and uneven (0.35 to about 2.4 fps), so a track has few, unevenly spaced
samples; the report must say what it can and cannot support.
**Decision.**
- **Contract 0.7.0** (minor, additive): new file `runs/<run_id>/report.json`, DATA_CONTRACTS
  section 8 and `contracts/report.schema.json`. Every measurement is `{value, unit}`; a null
  value carries a reason; counts are plain `n_*` integers; a top-level `caveats` list is
  required. Chosen over unit suffixes in key names (`path_length_px`) so that calibration can
  change the unit without renaming keys.
- **Positions go through a function** (`PositionMap`: pixel point to output point, plus the
  unit and default activity thresholds). `PixelPositions` is the only implementation now; part 5
  (calibration) supplies metres without touching the report code.
- **Definitions** (all in section 8): position = box bottom-centre at the frame's `t_recv`
  (tracks.csv has no time, joined on `seq`); per-track moving median of 3 samples inside runs
  of samples at most `max_gap` apart (symmetric, shrinking to 1 at the ends so a two-sample run
  is never flattened into zero speed); only intervals up to `--max-gap` (1.0 s) count for path,
  speed and activity, the rest are counted (`n_gaps_excluded`, `gap_time`); speed is null with
  a reason below 2 valid intervals; activity shares are by interval speed, weighted by interval
  time. The default thresholds, 40 and 400 px/s, are placeholders that depend on camera
  distance (an estimate from typical speeds, not a measurement: a 1280 px wide view of about 8 m
  puts walking near 220 px/s and running near 640 px/s); they are labelled as such in the caveats and configurable.
- **Reuse.** processed fps and app delay percentiles use `perception.loop.rates` and
  `delay_stats`, so the report and the benchmark agree.
- **Placement.** Code in `services/edge/reports/` (ARCHITECTURE section 3); the CLI the phase
  file names, `python -m services.edge.report`, is a one-line module that calls it. The CLI takes
  a session folder, not a session id: a folder is `<camera_id>_<session_id>` (D-022), found by
  path or, in group form, by reading each `session.json`.
- **Automatic.** A live session writes `report.json` and prints a summary after the final
  `session.json`; a report failure is printed and never changes the session's status or exit
  code. The launcher then prints one table with a row per camera, rebuilt from the run's files with
  the default parameters (not read from `report.json`, which may have been rerun with others). Group form (`--group G --out DIR`) prints one section per camera: no fusion.
**Not decided / out of scope.** Calibration, pose, basketball actions, cross-camera fusion,
accuracy against ground truth (PHASE_05 keeps it out), identity.
**Gate (code-reviewer, contract-guardian).** Both PASS, no BLOCKER or MAJOR (the first attempt of
both subagents died on a session rate limit, nothing was reviewed; they were run again).
Fixed from the MINORs: activity share needs the same minimum of valid intervals as speed (it
was built from one interval); malformed CSV rows are skipped and counted; a duplicate
(track, seq) is one sample; one processed frame gives no fps or interval; drop-rate and event
nulls carry the right reason (`event precedes t0`: every null in the report has a reason);
`--run` must be one of the session's runs; one broken camera does not stop a group report;
nonsense thresholds are refused; the console summary lists the 20 longest tracks; Ctrl+C during
the report cannot change the session's exit code; a launcher report failure is printed. The
launcher's table is rebuilt from the files with default parameters, not read from `report.json`.
Rest in BACKLOG.
**Status.** Accepted; merged to main.

## D-024 · 2026-10-13 · Pointr Studio local UI stack
**Context.** Phase 06's local recording UI is pulled forward for v0; camera registration and
identity features remain out of scope.
**Decision.** Close Q-03 with FastAPI/Uvicorn serving a React + Vite + TypeScript frontend.
Commit the built frontend so a Windows PC can run the app without Node; Node is needed only
to develop/build/lint the UI. Bind the app and child preview servers to `127.0.0.1`. Persist
camera configuration under `%LOCALAPPDATA%/pointr`, not in the repository. Camera recording
continues in the backend if the browser tab closes; app shutdown requests the launcher's
clean-stop path. Child previews use an allocated loopback port with fallback to another free
port; the effective port is app status, not session metadata. Keep annotation and JPEG encode
off the detector/processing path, with a bounded drop-oldest preview handoff.
**Consequences.** FastAPI and Uvicorn are runtime dependencies. The UI distribution is
committed; no session data contract changes are intended. `--benchmark` reports preview on/off
alongside processed FPS and app-delay percentiles. Matched 15 s synthetic-clip CPU runs measured
2.61 fps off (41 processed, 186 dropped, p50 app delay 417.9 ms) and 2.57 fps on
(41 processed, 188 dropped, p50 413.2 ms); both used the same 640x360 clip and cached model. This is a pipeline-only
measurement, not a webcam result; one short run each is not enough to attribute the 0.04 fps
difference to preview. The laptop webcam was unavailable in the dev environment, so repeat the
comparison on hardware before accepting the app part.
**Status.** Accepted for v0-app; review and hardware checks pending.

## D-025 · 2026-10-13 · Visual court calibration and contract 0.8.0
**Context.** Part 5b brings phase 10 visual calibration forward into Pointr Studio. The current
report already accepts a `PositionMap`, so calibrated movement can preserve its report algorithm
while changing coordinate units.
**Decision.** Fit an image-to-court homography from at least four calibration points only; at
least two separate check points measure held-out residuals and never participate in fitting.
Coordinates use an origin at a court corner, x follows court length, and y follows court width.
The default model is a 28 x 15 m FIBA court; measured custom dimensions and explicit custom
landmarks are supported. Use installed OpenCV `cv2.findHomography` with RANSAC. Per-point errors
are Euclidean metres; report calibration mean and check mean/max separately. The default allowed
check mean is 0.5 m. “Save anyway” records a forced calibration only when minimum point counts
are met. Calibration JSON and its exact raw audit JPEG are user data outside the repository.

Contract **0.8.0** adds calibration references/check errors to session and run metadata, calibrated
position fields and an `in_court` flag to tracks.csv, provenance to report positions, and a schema
for calibration files. Calibrated reports use metres and m/s, with default activity thresholds
0.5 and 2.5 m/s; uncalibrated reports stay in pixels. The live preview overlays projected court
lines. A capture-size mismatch refuses recording with a clear camera-specific error.

The Calibration screen is redesigned with the feature: clear recording/camera state, a guided
step sequence, a side-by-side image/court workspace, and readable inline errors. A restrained
court-green palette with warm amber actions fits use beside a live camera in a bright gym. No new
UI dependencies.
**Status.** Implementation and automated gates complete on `v0-calibration`; independent reviews
and the hardware acceptance check are pending. D-025 explicitly approves one bounded scope
exception: phase 06 local Studio and phase 10 visual calibration are pulled forward together as
the v0 Studio/calibration deliverable; this does not formally close phase 03 or any intervening
phase.

## D-023 · 2026-10-13 · v0 movement report per person, contract 0.7.0
**Context.** Tonight's recordings need a readable result per camera. The processing rate on
the dev CPU is low and uneven (0.35 to about 2.4 fps), so a track has few, unevenly spaced
samples; the report must say what it can and cannot support.
**Decision.**
- **Contract 0.7.0** (minor, additive): new file `runs/<run_id>/report.json`, DATA_CONTRACTS
  section 8 and `contracts/report.schema.json`. Every measurement is `{value, unit}`; a null
  value carries a reason; counts are plain `n_*` integers; a top-level `caveats` list is
  required. Chosen over unit suffixes in key names (`path_length_px`) so that calibration can
  change the unit without renaming keys.
- **Positions go through a function** (`PositionMap`: pixel point to output point, plus the
  unit and default activity thresholds). `PixelPositions` is the only implementation now; part 5
  (calibration) supplies metres without touching the report code.
- **Definitions** (all in section 8): position = box bottom-centre at the frame's `t_recv`
  (tracks.csv has no time, joined on `seq`); per-track moving median of 3 samples inside runs
  of samples at most `max_gap` apart (symmetric, shrinking to 1 at the ends so a two-sample run
  is never flattened into zero speed); only intervals up to `--max-gap` (1.0 s) count for path,
  speed and activity, the rest are counted (`n_gaps_excluded`, `gap_time`); speed is null with
  a reason below 2 valid intervals; activity shares are by interval speed, weighted by interval
  time. The default thresholds, 40 and 400 px/s, are placeholders that depend on camera
  distance (an estimate from typical speeds, not a measurement: a 1280 px wide view of about 8 m
  puts walking near 220 px/s and running near 640 px/s); they are labelled as such in the caveats and configurable.
- **Reuse.** processed fps and app delay percentiles use `perception.loop.rates` and
  `delay_stats`, so the report and the benchmark agree.
- **Placement.** Code in `services/edge/reports/` (ARCHITECTURE section 3); the CLI the phase
  file names, `python -m services.edge.report`, is a one-line module that calls it. The CLI takes
  a session folder, not a session id: a folder is `<camera_id>_<session_id>` (D-022), found by
  path or, in group form, by reading each `session.json`.
- **Automatic.** A live session writes `report.json` and prints a summary after the final
  `session.json`; a report failure is printed and never changes the session's status or exit
  code. The launcher then prints one table with a row per camera, rebuilt from the run's files with
  the default parameters (not read from `report.json`, which may have been rerun with others). Group form (`--group G --out DIR`) prints one section per camera: no fusion.
**Not decided / out of scope.** Calibration, pose, basketball actions, cross-camera fusion,
accuracy against ground truth (PHASE_05 keeps it out), identity.
**Gate (code-reviewer, contract-guardian).** Both PASS, no BLOCKER or MAJOR (the first attempt of
both subagents died on a session rate limit, nothing was reviewed; they were run again).
Fixed from the MINORs: activity share needs the same minimum of valid intervals as speed (it
was built from one interval); malformed CSV rows are skipped and counted; a duplicate
(track, seq) is one sample; one processed frame gives no fps or interval; drop-rate and event
nulls carry the right reason (`event precedes t0`: every null in the report has a reason);
`--run` must be one of the session's runs; one broken camera does not stop a group report;
nonsense thresholds are refused; the console summary lists the 20 longest tracks; Ctrl+C during
the report cannot change the session's exit code; a launcher report failure is printed. The
launcher's table is rebuilt from the files with default parameters, not read from `report.json`.
Rest in BACKLOG.
**Status.** Accepted; merged to main.

## D-026 · 2026-10-13 · Studio keeps camera errors until the user dismisses them

**Context.** The Studio cleared its error banner on every successful poll (about 1.2 s), so a
camera failure could be gone before it was read, and a refused start gave one message for the
whole group.
**Decision.** Studio holds, per camera and in memory for the current app run, `last_error`
(plain message, technical detail with credentials masked, timestamp) and the last 50 events,
newest first, copied from the session files. `/api/status` serves both, so a reload shows the
same. An error leaves only when the user dismisses it (`DELETE /api/cameras/{id}/error`) or the
camera next starts. A start is validated before any state changes: a refusal names the camera,
is recorded for it (`idle_cameras` when it has no process) and leaves the previous group and the
other cameras as they were. `mask_credentials` (writer.py) hides `user:password@` and secret-looking
query parameters in free text; the launcher applies it to every child line and failure.
**Not done.** The Studio status payload is still not in DATA_CONTRACTS.md (it was not before
this change); no contract version bump because no file or schema changed. The frontend has no
test runner, so the persistence is tested at the status level. The errors are not written to
session files, so they do not survive an app restart.
**After the merge with `v0-calibration` (D-027).** A corrupt or missing calibration no longer
refuses the start: that camera starts uncalibrated, the status carries `calibration_warning`, and
the camera's event log gets a `calibration_not_used` event. A refusal with a per-camera error is
now only possible for other reasons; `idle_cameras` still lists a camera that has an error but no
process.

## D-027 · 2026-10-13 · Review fixes for the calibration branch; commit order broke rule 2

**Process deviation.** CLAUDE.md rule 2 puts the contract and the `DECISIONS.md` entry before the
code. On `v0-calibration` they did not: the calibration code (`e57e266`, which already sets
`CONTRACT_VERSION = "0.8.0"` and the file validator) was committed before the contract change
(`c4a4567`), D-025 was committed last (`3ca2154`), and all seven commits were made within 20
seconds, so the history cannot show contract-first order. The work was built in one sitting and
committed in a batch. D-025 also sat between D-024 and D-023 in this file; the entries are now in
order. From here a contract or format change is written in `DATA_CONTRACTS.md` and recorded here
before the code that needs it.

**Context.** Three subagent reviews of the branch (code-reviewer, reliability-reviewer,
contract-guardian) found data-integrity defects: a dead projection guard, a writer that died on one
bad row, check points that could duplicate fit points, and a calibration that could block or
mislead a recording. Fixed one item per commit, each with a test that fails on the old code.

**Decisions.**
- **0.8.0 stays.** The branch has not been merged or released and nothing reads 0.8.0 files yet,
  so the 0.8.0 documents were corrected in place instead of bumping: an unprojectable point has
  empty `x_m`, `y_m` and `in_court` (never 0); `in_court` is lowercase `true`/`false`;
  `max_check_error_m` is at most 2.0 (schema); `fiba_full` must be 28 x 15 (schema); the hold-out
  and homography rules; the Studio calibration API (DATA_CONTRACTS section 9). Once a 0.8.0 file
  is outside this branch, a change like these needs a bump.
- **Projection.** An explicit homogeneous divide; a point is invalid when w <= 1e-6 or the result
  is not finite. A homography is refused when it is non-finite, singular, has a condition number
  above 1e7, or puts a point on or beyond the horizon; `save_anyway` cannot override this. The
  1e7 limit is above the 2e4 that a synthetic camera trapezoid gives; no real camera fit has been
  measured, so it may need to move.
- **Hold-out.** No two points within 1e-6 m (court) or 1 px (image); fit points need a spread
  (square root of minor to major variance) of at least 0.1 in the image and on the court. These
  thresholds are chosen by reasoning, not measured.
- **Writer.** The session writer receives its projector as an injected `PositionMap` and never
  imports the calibration package. A row's projection error leaves its position empty, counts it
  and records an `error` event (first one at once, then at most one per 30 s, and a final count
  at close).
- **Frame size.** The Studio captures the idle calibration frame with `DEFAULT_CAPTURE_SIZE`, the
  recorder's own default. The recorder compares its first processed frame with the calibration and
  fails that camera, with both sizes, on a mismatch; a later change stops the homography.
- **One bad calibration.** `Studio.start` loads every calibration first; a camera whose file is
  missing or invalid starts uncalibrated with a session event and a status warning, and never
  refuses the group.
- **Court model.** Key depth and width, basket offset and circle radius are fixed lengths on a
  custom court; markings that do not fit are left out. The Studio draws the server's court model.
- **Validator.** `validate_calibration` runs `calibration.schema.json` through `jsonschema`, which
  is therefore a runtime dependency (it was dev-only). `ACCEPTED_VERSIONS` lists the calibration
  versions the loader takes; `CONTRACT_VERSION` lives in `services/edge/contract.py` only.
- **Durability.** Calibration files are fsynced before their rename, and a locked rename is
  retried briefly.

**Not decided / not verified.** Nothing here was run against a real webcam or a real court: the
640x480 default and the recorder's refusal come from reading the code, and the fix is tested with a
fake camera. RANSAC may leave out a good point instead of the bad one (its choice among equal
fits); the Studio now names the point it left out. D-026 is used by the `v0-cameras` branch, so
this branch skips it.

## D-028 · 2026-10-14 · Defer physical calibration acceptance

**Decision.** Complete software fixes and automated tests for the calibration review without
waiting for camera hardware or a tape-measure session. The user will perform the physical checks
when equipment and time are available. Until then, do not describe the calibration as accepted on
real cameras or measured court marks.

**Deferred acceptance.** Capture an idle camera frame and verify its resolution against recording;
fit measured floor marks on a real court and compare held-out check residuals with tape-measure
truth. Record the result in the phase 10 report when performed.

## D-031 · 2026-10-14 · Validate and preserve Studio camera settings

**Decision.** Version the additive Studio camera settings under contract 0.9.0. Keep stable
`camera_id` values for session/calibration identity and add a unique display name, enabled flag,
and optional requested FPS cap. Reject unsafe URL schemes and loopback or link-local hosts.
Preserve the last valid settings file as `.bak`, atomically replace the active file, and surface a
visible warning rather than silently loading damaged settings.

**Reason.** Camera setup errors must be clear before recording; an invalid or interrupted save
must not erase the last usable setup. The FPS cap is a capture request, not an FPS guarantee.

## D-032 · 2026-10-14 · Contract 0.10.0: add a FIBA half-court calibration model

**Context.** Calibration has only `fiba_full` (28 x 15 m) and `custom`. Training sessions may
cover one basket and the near half, so requiring points at both ends of a full court produces a
poorly conditioned fit for the visible floor and makes `in_court` use the wrong length.

**Decision.** Add `fiba_half` as a 14 x 15 m court with x=0 at the basket baseline and x=14 at
the midcourt line. Its landmarks reuse the `fiba_full` constants for all points with x <= 14,
then add both midcourt corners and the midcourt centre. Persist court type and bounds through
calibration, run, session, and report data. Preserve older `fiba_full` and `custom` calibrations,
and keep custom measured courts available. Fit spread remains governed by the existing 0.1
minimum in image and court coordinates. Half-court fits must also cover at least 20% of its 210 m²
area by the fit-point bounding box; explain both thresholds and the physical reason in Studio.
Projected points outside the selected bounds remain unchanged and are flagged out of court.
Report movement remains computed in the position unit, so identical coordinates yield identical
distance and speed regardless of whether the bounds are full or half court.

**Consequences.** Contract version is 0.10.0. Calibration, run, session and report schemas record
court type/bounds. The report diagram follows the stored type. A half-court setup can use baseline
and midcourt points visible from phones placed along the sideline; verify known floor marks with
a tape measure before treating movement values as accepted measurements.
## D-033 · 2026-10-19 · The December test rig is its own track (Track R)

**Context.** Suite stage 2 produced a signed spec (`.scratch/pointr-vision/spec.md`) for a December
test rig: two phones with fusion, a rim sensor, ball and rim detection, shot calls and jersey-number
identity, to decide hypotheses H1 to H4, H3b, H6 and H7 of `.scratch/pointr-vision/decision-record.md`.
It touches D-022 (no fusion across cameras), the person-only detector, athlete assignment (phase 11)
and the recorder (phase 04).

**Decision.** (Owner, 2026-10-19.) Track the rig as its own track, Track R, with its own phase file
`docs/phases/PHASE_R.md` and its own gate, separate from phases 03 to 09. It is not a scope
exception. Phases 03 to 09 keep their scope and order. The decisions the rig forces are proposed as
`docs/adr/0001` to `0006` and are recorded here as D-0NN entries when the owner accepts each.

**Consequences.** `docs/PHASES.md` gets a Track R row and no phase pointer changes. The rig needs
recording and replay, which are phase 04 deliverables: whether Track R builds them or waits for
phase 04 is an open owner decision in the phase file. Contracts change first: slice R0 writes the new
files and fields into `DATA_CONTRACTS.md` and bumps the version before any code reads or writes them.
## D-034 · 2026-10-19 · Cross-camera fusion is a post-session step (ADR 0001)

**Context.** Spec FR-004 needs one record per player from two phones. D-022 runs one process per
camera with no fusion across cameras, and the cameras of a group are not aligned (BACKLOG).

**Decision.** (Owner, 2026-10-19.) Fusion is a separate post-session step that reads the per-camera
session folders of one group and writes its own outputs under the group. It matches by court-plane
distance and time inside the overlap zone, then by player number and colour, keeps both cameras'
readings and writes a difference report. The capture and perception processes are unchanged, so
D-022 still holds on the live path. Fusion results are trusted only after the clock test of D-035.
Near-live fusion waits until this works; no fusion with a manual merge is the fallback.

**Consequences.** A new contract section for the fusion outputs, and a version bump from 0.10.0,
defined in DATA_CONTRACTS.md before the code. Gap periods (FR-014) are marked and left out of the H3b
and H6 scoring. Accuracy evidence is low; H6 is decided in the first two-phone session.

## D-035 · 2026-10-19 · One PC clock domain with measured per-camera latency (ADR 0002)

**Context.** Spec FR-005 needs frames and sensor events on one timeline. Every camera process runs
on the same PC and Frame.t_recv is perf_counter on that PC; phones give no timestamps.

**Decision.** (Owner, 2026-10-19.) All timing uses the PC perf_counter domain (Windows, Python 3.10
or later). The sensor stamps events with its own timer and its offset to the PC clock is estimated by
ping-pong with a minimum-RTT filter and a drift fit, re-estimated every 10 to 30 seconds. Each
camera's capture-to-arrival latency is measured with the LED test at session start and checked again
at the end. The run records median, 95th percentile and standard deviation per camera.

**Consequences.** run.json gets a clock block (contract bump). FR-005's drift limit of 1.2 ms per
minute is replaced by the periodic offset estimate (spec CR-2). If per-frame stream jitter exceeds
about 10 ms per camera the phone-to-phone limit of 33 ms may fail; the fallbacks are USB capture, no
fusion, or the custom phone app (phase 13).

## D-036 · 2026-10-19 · Rim sensor link: ESP-NOW with a USB gateway (ADR 0003)

**Context.** Spec FR-009 and FR-015 need make events and outage detection from a rim sensor. The PC's
distance to the rim is not known yet.

**Decision.** (Owner, 2026-10-19.) The rim ESP32 sends over ESP-NOW to a gateway ESP32 on the PC's
USB port, with sequence numbers, repeats and an application-level acknowledgement. If the PC stands
about 5 m or less from the rim, a direct USB serial cable replaces the radio link. Wi-Fi UDP and BLE
are rejected for v1. The make-detection hardware itself is not decided here.

**Consequences.** A new EventSource Protocol, a new events.csv, outage events and a firmware folder
(contract and this log first). The distance is still to be given by the owner; ESP-NOW is assumed
until then. A dry run with rim hits, net sway and hand passes counts false triggers (spec CR-4).

## D-037 · 2026-10-19 · Ball and rim detection: one multi-class detector, rim fixed per session (ADR 0004)

**Context.** Spec FR-008 needs ball and rim boxes. The detector keeps only the COCO person class and
changing a Protocol needs an entry here (ARCHITECTURE section 4).

**Decision.** (Owner, 2026-10-19.) Fine-tune the existing RF-DETR as one detector for person, ball and
rim, and store the rim as a median box over the first frames of a session, re-detected periodically with
a drift flag. ByteTrack stays person-only; ball and rim boxes go to the shot layer. Measure first: ball
pixel size and a subsample test at 2, 5, 10 and 15 fps before any fine-tuning. A separate temporal ball
model is the fallback if ball recall is too low.

**Consequences.** A new objects.csv for ball and rim boxes (contract bump). A labelling and
fine-tuning workflow is approved as a dependency (D-040). Person quality is re-checked after
fine-tuning. Dataset licences must be read before use.

## D-038 · 2026-10-19 · Shot inference is a separate layer over the logged streams (ADR 0005)

**Context.** Spec FR-010 to FR-012 and FR-013 need attempts, calls and scoring against hand labels,
at 2 to 15 fps.

**Decision.** (Owner, 2026-10-19.) A separate layer reads the logged streams (person, ball and rim
boxes, sensor events, timestamps). It runs live by tailing the log and afterwards by replay. A
post-session full-rate pass on recorded video decides H1. The rules are those of the decision record and
spec FR-010 and FR-011.

**Consequences.** A new shots.csv (contract bump). Live calls lag the shot by about 1 to 2 seconds and
are outside the December pass criteria. Recording and replay are needed first (D-040).

## D-039 · 2026-10-19 · Identity layer: number voting, then colour and position gating (ADR 0006)

**Context.** Spec FR-006 and FR-007 need the track ID to follow the jersey number, and NFR-003 needs a
replaceable method. athlete_id is empty until the assignment phase.

**Decision.** (Owner, 2026-10-19.) An IdentityResolver interface after the tracker returns a player
number with a confidence. Build number voting over the legible frames of a track first, add team colour
and position-and-time gating as the target, and keep operator correction at the end of a drill as the
fallback. The method is chosen by IDENTITY_METHOD. The 80% target of H3 is read per track after voting,
not per player frame (spec CR-3).

**Consequences.** tracks.csv gains player_number and id_source (contract bump); athlete_id stays empty.
H3b (8 of 10 returns) is unproven for same-kit players and is met by construction only with the
fallback.

## D-040 · 2026-10-19 · Track R: recording in R1, spec amendments, new dependencies

**Decision.** (Owner, 2026-10-19.) (1) Recording and replay are built inside Track R as slice R1,
following the phase 04 contract so they merge into phase 04 later. (2) Spec changes CR-2 (FR-005),
CR-3 (FR-006) and CR-4 (FR-009) are accepted and the spec is amended in place. (3) These dependencies
are approved by category: a labelling and fine-tuning workflow (R2), a number-recognition model (R5),
ESP32 firmware tooling in a firmware folder (R4). Each slice's phase file names the exact packages or
models before they are installed.

**Consequences.** PHASE_R.md records the decisions. The PC-to-rim distance (D-036) and spec CR-1 stay open.
