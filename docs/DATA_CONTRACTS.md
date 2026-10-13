# Data contracts

Contract version: **0.5.0**. Any change bumps the version (minor for additive fields, major
for removals or meaning changes) and needs a `DECISIONS.md` entry. JSON Schemas in
`contracts/` are written from this file and tests check them against it (D-009).

Conventions: UUIDv4 for every ID generated on the device. Wall times are UTC ISO-8601.
Durations and offsets in seconds as floats. Monotonic times are seconds relative to the
run's `t0`, the `time.perf_counter()` value taken when the run's capture thread starts (D-011;
the clock is `perf_counter` since D-020, as `time.monotonic()` ticks every 15.6 ms on
Windows), and only comparable within one run. Missing values are empty in CSV and
`null` in JSON, never `0`.

## 1. Session folder

```
sessions/device_id          one UUIDv4, created on first use, reused by every session
sessions/<session_id>/
  session.json
  runs/<run_id>/
    run.json
    frames.csv
    tracks.csv
    report.json          (phase 5)
  video.mp4              (phase 4, raw, no annotations)
```

A live session produces one run. Each replay adds a run. Nothing is overwritten.
The session folder is created once the source has opened (D-020). Failures before that (bad
ref, model load, `source_open_failed`) are printed and exit non-zero; they leave no folder.

**Durability (D-020).** One writer thread owns every file. CSV rows are flushed and
`session.json` is rewritten (temp file, then replace) within a second of each new event, so
after a crash the CSVs are readable up to the last flush and `session.json` stays valid with
status `running`. The final status, `ended_at` and counts are written in a `finally` block.

## 2. `session.json`

```json
{
  "contract_version": "0.5.0",
  "session_id": "uuid",
  "device_id": "uuid",
  "started_at": "2026-10-07T18:00:00Z",
  "ended_at": "2026-10-07T18:45:00Z",
  "status": "running | ended | interrupted | error",
  "source": {"kind": "camera | stream | file", "ref": "1", "width": 1280, "height": 720,
             "reported_fps": 30.0, "link": "usb | wifi | builtin | file"},
  "registration": {"date": "2026-10-07", "team_ids": ["uuid"]},
  "recording": {"enabled": true, "path": "video.mp4", "sha256": null, "locked": true},
  "runs": ["uuid"],
  "events": [{"t_wall": "...", "t_mono": 12.3, "kind": "source_lost", "detail": "..."}]
}
```

`registration` is filled from phase 6 and is `null` before that. `ended_at` is `null` while
the session is running. `source.link` is how the source reaches the notebook, declared by
the user with `--link` (the notebook cannot detect it, D-010); `null` when not given.
`link` and `kind` must agree: `link` is `file` exactly when `kind` is `file` (or `link` is
`null`); the CLI rejects a contradiction and the schema enforces it (D-020).
`source.ref` and `run.json` `input.ref` never hold credentials: `user:password@` is removed
from stream URLs before writing (D-020). `recording` is `{"enabled": false, "path": null,
"sha256": null, "locked": false}` until phase 4.
Event `t_mono` is `null` for events that precede the run's `t0`, such as
`source_open_failed` (D-014).
Event kinds: `source_open_failed`, `source_lost`, `source_recovered`,
`frozen_frames`, `dark_frames`, `writer_backlog`, `recorder_backlog`, `interrupted`, `error`.

## 3. `run.json`

```json
{
  "contract_version": "0.5.0",
  "run_id": "uuid",
  "session_id": "uuid",
  "mode": "live | replay",
  "input": {"kind": "camera | stream | file", "ref": "...", "sha256": null,
            "requested_width": 1280, "requested_height": 720},
  "detector": {"name": "rfdetr", "variant": "nano", "weights": "coco-pretrained",
               "package_version": "x.y.z", "threshold": 0.5, "det_size": 384},
  "tracker": {"name": "bytetrack", "package": "trackers", "package_version": "x.y.z",
              "params": {}},
  "health": {"lost_reads": 30, "lost_secs": 2.0, "frozen_diff": 0.5, "frozen_secs": 2.0,
             "dark_level": 20.0, "dark_secs": 1.0},
  "runtime": {"python": "3.11.x", "platform": "...", "device": "cpu | cuda:0",
              "gpu": "NVIDIA ... | null",
              "packages": {"opencv": "x.y.z", "numpy": "x.y.z", "torch": "x.y.z",
                           "supervision": "x.y.z"}},
  "started_at": "...", "t0_wall": "...", "ended_at": "...",
  "counts": {"captured": 0, "processed": 0, "dropped": 0, "unprocessed": 0, "rec_dropped": 0}
}
```

`counts.rec_dropped` is `null` when recording is disabled. `ended_at` is `null` while the
run is in progress; `counts` is `null` until the run ends, so a crashed run never shows
counts that were not measured. `t0_wall` is the UTC wall clock taken with the run's `t0`
(D-011), `null` until capture starts; `t0_wall + t_mono` aligns frames.csv to wall time.
`counts.unprocessed` is frames taken for processing but never finished (detector error or
shutdown timeout, D-018); `captured = processed + dropped + unprocessed` on a clean stop.
`requested_width/height` are the size asked of a camera (`--width/--height`), `null` for
streams and files. `detector.det_size` is the square side the image is resized to for
detection. `detector` and `tracker` are `null` and `runtime.device` is `null` when detection
is off (`--no-detect`). `runtime.device` is `cpu` or `cuda:N`; `runtime.gpu` is the CUDA GPU's name
(`torch.cuda.get_device_name`), `null` on `cpu` and with `--no-detect`. `runtime.packages` holds
installed versions, `null` when a package is not installed. `health` holds the source-health
thresholds of the run (`--lost-reads` ... `--dark-secs`). The tracker is fed `Frame.t_recv`
as its timestamp (D-016).

## 4. `frames.csv`

One row per **processed** frame, including frames with zero detections.

| column | type | meaning |
|---|---|---|
| seq | int | capture sequence number; gaps between rows = dropped, unprocessed frames or failed reads |
| t_recv | float | monotonic receive time, s since t0 |
| t_proc_start | float | processing start, s since t0 |
| t_proc_end | float | processing end, s since t0 |
| app_delay_ms | float | (t_proc_end − t_recv) × 1000 |
| n_detections | int/empty | person detections above threshold; empty when detection is off |
| n_tracks | int/empty | tracks output by the tracker; empty when detection is off |
| dropped_total | int | capture's drop count when this frame was taken for processing |

## 5. `tracks.csv`

| column | type | meaning |
|---|---|---|
| seq | int | frame seq |
| track_id | int | temporary tracker ID, valid only within this run |
| x1, y1, x2, y2 | float | box in pixels |
| confidence | float/empty | detector confidence if the tracker exposes it |
| state | str | `observed` or `predicted`, when the tracker exposes it, else empty |
| athlete_id | uuid/empty | empty until the assignment phase |

## 6. SQLite (`pointr.db`), from phase 6

```sql
team(id TEXT PK, name TEXT NOT NULL, coach TEXT, updated_at TEXT, device_id TEXT, deleted INT DEFAULT 0)
player(id TEXT PK, name TEXT NOT NULL, birth_date TEXT, height_cm REAL, weight_kg REAL,
       team_id TEXT REFERENCES team(id), shirt_number INT, position TEXT,
       updated_at TEXT, device_id TEXT, deleted INT DEFAULT 0,
       UNIQUE(team_id, shirt_number))                       -- RN06
session(id TEXT PK, date TEXT NOT NULL, started_at TEXT, ended_at TEXT, status TEXT,
        folder TEXT, updated_at TEXT)
session_team(session_id TEXT, team_id TEXT, PRIMARY KEY(session_id, team_id))  -- 1 or 2 teams, RN07
outbox(id TEXT PK, lane TEXT CHECK(lane IN ('data','video')), kind TEXT, entity_id TEXT,
       payload_ref TEXT, status TEXT, attempts INT DEFAULT 0, next_attempt_at TEXT,
       last_error TEXT, created_at TEXT)
sync_state(key TEXT PK, value TEXT)                          -- pull cursor, last success
entitlement_cache(account_id TEXT PK, plan TEXT, cloud_video INT, fetched_at TEXT)
```

Duration is computed from `started_at` and `ended_at`, never stored.

## 7. Sync API (v1), from phase 7

All requests carry `Authorization: Bearer <device token>`. Write requests carry
`Idempotency-Key: <outbox id>`. A repeated key returns the original response.

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/sync/batches` | upload a batch of changes (registrations, session metadata, session data parts) |
| GET | `/v1/sync/changes?since=<server_seq>` | pull registration changes after a cursor |
| GET | `/v1/entitlements` | current plan and cloud-video setting |
| PUT | `/v1/settings/cloud-video` | toggle the account-level setting (video plan only) |
| POST | `/v1/videos` | start a video upload: session_id, size, sha256 → upload_id, chunk_size |
| PUT | `/v1/videos/{upload_id}/chunks/{n}` | upload one chunk |
| GET | `/v1/videos/{upload_id}` | received chunks, so an interrupted upload resumes (RNF10) |
| POST | `/v1/videos/{upload_id}/complete` | server verifies sha256; returns verified or mismatch |

Batch body:

```json
{"device_id": "uuid", "changes": [
  {"kind": "player.upsert", "id": "uuid", "updated_at": "...", "data": {}},
  {"kind": "session.upsert", "id": "uuid", "data": {}},
  {"kind": "session.part", "session_id": "uuid", "run_id": "uuid", "part_no": 0,
   "frames": "base64 gzip csv", "tracks": "base64 gzip csv", "sha256": "..."}
]}
```

Response: `{"accepted": [{"id": "...", "server_seq": 123}], "rejected": [{"id": "...", "reason": "..."}]}`.

Conflict rule for registrations: highest `updated_at` wins; ties broken by `device_id`.
Session data is append-only; a repeated `(session_id, run_id, part_no)` with the same sha256
is accepted as a no-op, with a different sha256 is rejected.
