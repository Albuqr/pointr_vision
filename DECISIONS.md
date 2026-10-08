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
