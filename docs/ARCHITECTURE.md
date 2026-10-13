# Pointr architecture

Version 1, 7 October 2026. Based on `Pointr_Escopo_v2.pdf` (17/09/2026) and the agreed
requirements in `REQUIREMENTS.md`.

## 1. Overview

```
 ┌──────────────┐   USB (or Wi-Fi)   ┌──────────────────────────── NOTEBOOK ─────────────────────────────┐
 │ Android phone│ ─────────────────▶ │  EDGE RUNTIME (pointr-vision)                     SYNC AGENT       │
 │ camera app   │   video stream     │                                                                     │
 └──────────────┘                    │  capture ─▶ perception ─▶ session writer ─▶ sessions/<id>/*         │
                                     │     │        (detect+track)      │                  │               │
                                     │     └──▶ recorder ─▶ video.mp4   └──▶ SQLite ◀──────┘ outbox        │
                                     │                                     (pointr.db)  ─▶ sync agent ──┐  │
                                     │  local UI (preview, registrations, reports)                      │  │
                                     └───────────────────────────────────────────────────────────────── │ ─┘
                                                                                                        │ HTTPS, when reachable
                                     ┌──────────────────────── SERVER (VPS) ──────────────────────────┐ │
                                     │  cloud API (FastAPI) ─▶ PostgreSQL     object storage (video)   │◀┘
                                     │        └─ entitlements (plans)  └─ later: analytics (pointr-data)│
                                     └──────────────────────────────────────────────────────────────────┘
```

The phone only supplies video. All computer vision runs on the notebook. Everything is
written locally first; the network is never on the critical path of a session.

## 2. Process boundaries: services where the boundary is real

The project is built as **independent layers**, each added in its own phase behind a stable
interface. Only some of them are separate processes.

| Unit | Kind | Why |
|---|---|---|
| Edge runtime (capture, perception, session, recorder, reports) | **One process, layered modules** | Frames move at camera rate. Passing them between local HTTP services would add copies and delay for no gain, and would make RNF02 harder to meet. Layers are still isolated by Protocols and tested alone. |
| Sync agent | **Separate process** | Runs whether or not a session is live; must survive the edge runtime crashing; talks to the network. |
| Cloud API | **Separate service (container)** | Different machine, different lifecycle, multiple devices. |
| Object storage | **Separate service** | Video lane, see section 7. |
| Analytics (pointr-data) | **Separate service, later** | Batch jobs over synced data. |
| Phone app (custom) | **Optional, late** | Phase 0 uses an existing camera app. Scope v2 excludes a native app from the first delivery. |

Recorded in `DECISIONS.md` as D-001.

## 3. Repository layout

```
pointr/
  CLAUDE.md
  DECISIONS.md
  docs/                      architecture, contracts, requirements, phases, gates
  contracts/                 JSON Schemas written from DATA_CONTRACTS.md, checked by tests
  services/
    edge/
      capture/               FrameSource implementations + health monitor
      perception/            Detector, Tracker implementations
      session/               session lifecycle, writers
      recording/             raw video recorder
      replay/                file replay runner
      reports/               post-session coverage and failure reports
      store/                 SQLite access (registrations, session index, outbox)
      ui/                    preview window (phase 1-5), local web UI (phase 6+)
      main.py                CLI entry point
    sync_agent/
    api/                     cloud API (FastAPI)
    data/                    analytics, later
  tests/
    edge/ sync_agent/ api/ e2e/
    fixtures/                synthetic clips, sample sessions
  .claude/agents/            review subagents used by the gates
```

## 4. Edge interfaces (Python Protocols)

These are the seams between layers. A phase may add a Protocol; changing an existing one
needs a `DECISIONS.md` entry.

```python
@dataclass(frozen=True)
class Frame:
    seq: int  # monotonically increasing per source, gaps = capture failures
    t_recv: float  # time.monotonic() when the frame was read
    t_wall: str  # UTC ISO-8601 wall clock at read time
    image: np.ndarray  # BGR, HxWx3
    source_id: str


class FrameSource(Protocol):
    def open(self) -> SourceInfo: ...  # width, height, reported fps, kind, raises on failure
    def read(self) -> Frame | None: ...  # None = no frame this attempt;
    # raises SourceEnded when a finite source (file) has ended (D-013)
    def close(self) -> None: ...


class SourceHealth(Protocol):
    def assess(self, frame: Frame | None) -> list[HealthEvent]: ...  # lost, frozen, dark, recovered


class Detector(Protocol):
    def detect(self, frame: Frame) -> Detections: ...  # boxes xyxy, confidence, class = person


class Tracker(Protocol):
    def update(
        self, dets: Detections, frame: Frame
    ) -> list[TrackObs]: ...  # track_id, box, conf, state


class SessionWriter(Protocol):  # run metadata, t0 and counts added by D-020
    def start(self, meta: SessionMeta, run: RunMeta) -> None: ...
    def set_t0(self, t0: float, t0_wall: str) -> None: ...
    def frame(self, rec: FrameRecord) -> None: ...
    def tracks(self, seq: int, obs: list[TrackObs]) -> None: ...
    def event(self, ev: SessionEvent) -> None: ...
    def close(self, status: str, counts: RunCounts) -> None: ...


class Recorder(Protocol):
    def start(self, path: Path, info: SourceInfo) -> None: ...
    def write(self, frame: Frame) -> None: ...
    def stop(self) -> RecordingInfo: ...  # path, frames written, frames dropped, sha256
```

`Detections` and `TrackObs` are plain dataclasses defined in `perception/types.py`. The
`supervision` and `rfdetr` objects never leave the perception layer.

## 5. Edge concurrency

```
capture thread ──▶ proc_queue (maxsize=1, drop oldest, count drops) ──▶ processing loop
      │                                                                   (detect → track)
      └──▶ rec_queue (bounded, larger) ──▶ recorder thread                       │
                                                                                 ▼
                                                     write_queue (bounded) ──▶ writer thread
                                                                                 (CSV/JSON, flush)
```

- **Capture never blocks on processing.** The processing queue holds one frame; when it is
  full the old frame is discarded and `frames_dropped` incremented. This keeps the pipeline
  real-time instead of building a backlog (scope v2, section 2).
- **Recording is fed from capture, not from processing**, so the recorded video contains
  every captured frame, not only the processed ones. If the recorder queue overflows, those
  drops are counted separately as `rec_frames_dropped`.
- **Disk I/O is off the hot path.** The writer thread owns all file handles. Its queue is
  bounded; if it fills, that is logged as an event, never silently ignored.
- **Order.** The processing loop handles frames in increasing `seq`. Tracker state is
  advanced only with in-order frames.
- **Processing thread and preview (D-017).** The processing loop runs on its own thread. The
  preview, on the main thread, shows the latest processed frame with its own boxes; it never
  takes from `proc_queue`.
- **Shutdown.** q, Ctrl+C, source end or exception all go through one shutdown path: stop
  capture, drain queues with a timeout, close writer, write final `session.json` in a
  `finally` block.

## 6. Local storage

Two stores with different jobs:

| Store | Holds | Why |
|---|---|---|
| `sessions/<session_id>/` files | `session.json`, `frames.csv`, `tracks.csv`, `video.mp4`, `report.json` | Append-only raw record of a run. Readable without the app, easy to replay and diff. |
| `pointr.db` (SQLite) | players, teams, session index, outbox, entitlement cache | Relational data edited by the user, and the durable send queue. |

Files are the source of truth for frame and track data; SQLite indexes them. A replay
creates a **new run** (new `run_id`) under the same session and never overwrites an earlier
one.

## 7. Sync design

Inspired by Linear's sync engine, adapted to a workload that is almost entirely append-only
and produced by a single device per session. See `DECISIONS.md` D-004.

**Taken from Linear**
- A **persistent local outbox**: every change to sync is a row in SQLite before anything is
  sent. It survives app close and reboot (RNF09).
- **The server orders changes.** Each accepted change gets a monotonically increasing
  `server_seq`. A client keeps a cursor and pulls only what it has not seen.
- **Last-writer-wins** for the only data more than one device can edit: registrations.

**Changed for Pointr**
- **Client-generated UUIDs plus an idempotency key on every request.** Linear documents a
  weak point where a transaction resent after a crash may fail because not all transactions
  are idempotent. Here the server stores processed keys, so a resend is a no-op (RNF08).
- **No WebSocket or live broadcast in v1.** Sessions are written by one device and do not
  conflict. The agent polls with exponential backoff.
- **Two lanes.**

| Lane | Carries | Plans | Mechanism |
|---|---|---|---|
| Data | registrations, session metadata, frames, tracks, reports | all | outbox → `POST /v1/sync/batches` (idempotency key = outbox id) → `server_seq`; pull via `GET /v1/sync/changes?since=` |
| Video | session video | video plan, global setting on | resumable chunked upload, sha256 verified on completion; only then is the video marked synced and the local copy eligible for removal |

Session data is uploaded in parts after the session closes (`session_id`, `part_no`), not
streamed live. The cloud is a backup and analysis target, not part of the live loop.

## 8. Plans and entitlements

- The account's plan lives on the server. **Entitlement checks are enforced server-side**;
  the client caches the last known entitlement only to decide what to show.
- Basic plan: data lane only. Video is still recorded locally but locked (RF17).
- Video plan: data lane + video lane when the account-level setting is on (RF18).
- Locked videos must not be playable outside the app (RNF11). Proposed mechanism: each
  video is encrypted at rest with its own data key; the key is wrapped by the server and
  released to the device only when the entitlement allows playback. Open question Q-05.
- Downgrade: cloud videos are retained for a period still to be defined (RN12, Q-04).

## 9. Server

- FastAPI + PostgreSQL, Docker Compose on the existing VPS behind Easypanel.
- Object storage: S3-compatible (MinIO on the VPS or a hosted bucket). Q-06.
- Auth: account login issues a device token; each device has a `device_id`.
- The API is versioned under `/v1`. Contracts in `DATA_CONTRACTS.md`.

## 10. User interface

| Phases | UI |
|---|---|
| 1-5 | OpenCV preview window with a status HUD (FPS, app delay, people, drops, source state) |
| 6+ | Local web UI served by the edge runtime (FastAPI on localhost + a small frontend): registrations, session start/stop, reports, plan status |

Screens marked "(tela)" in the requirements are listed against phases in `REQUIREMENTS.md`.

## 11. What the architecture does not promise

- No FPS or latency target until a baseline is measured on the actual notebook (RNF02).
- Track IDs are temporary. Linking a track to a registered player (Athlete ID) is a separate
  later phase; registering players does not make the system recognise them.
- Movement recognition (jumps, shots) needs pose estimation and validation. It is a late
  phase, not something derived from box displacement.
