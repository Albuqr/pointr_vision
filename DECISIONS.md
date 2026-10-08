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
  PHASE_01's "N consecutive failed reads" definition. Worst case for a stalled stream: about
  one read timeout plus one reopen (about 7 s); a webcam's fast failures still hit the count.
- `t_mono` is `null` for events that precede the run's `t0`, e.g. `source_open_failed`.
  `HealthEvent.t_mono` is `float | None`. This clarifies contract 0.3.0, which no released
  build or file uses yet, so it stays 0.3.0.
- `Capture.stop()` waits 8 s by default, longer than the slowest blocking stream read.
- Ctrl+C and main-loop exceptions become `interrupted` / `error` events with non-zero exit
  codes (130 / 1), not a bare message or a traceback.
- `SourceEnded` and `utc_now` move to `capture/types.py`. Generic code no longer imports
  from the concrete sources module, and ARCHITECTURE §4 documents the `SourceEnded` signal.
**Consequences.** The stream values (2 s read timeout, 5 s open timeout) are configuration
only; no stream loss time has been measured. A8 over IP Webcam will show the real figure.
**Status.** Accepted.
