# Data contracts

Contract version: **0.10.0**. Any change bumps the version (minor for additive fields, major
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
sessions/<folder>/         <camera_id>_<session_id>, or <session_id> without a camera_id
  session.json
  runs/<run_id>/
    run.json
    frames.csv
    tracks.csv
    report.json          (section 8)
  video.mp4              (phase 4, raw, no annotations)
%LOCALAPPDATA%/pointr/calibrations/<camera_id>/<calibration_id>/calibration.json
%LOCALAPPDATA%/pointr/calibrations/<camera_id>/<calibration_id>/frame.jpg (audit frame)
%LOCALAPPDATA%/pointr/calibrations/<camera_id>/active.json  ({"calibration_id": "uuid"}: the
                         calibration the next recording of that camera uses; replaced atomically)
```

The calibrations root is the folder of the Studio's `cameras.json` (`%LOCALAPPDATA%/pointr` by
default) plus `calibrations/`. A missing `active.json` means the camera records uncalibrated; an
unreadable one, or one that points at a missing or invalid calibration, starts that camera
uncalibrated with a session event (`calibration not used: ...`) and a warning in the Studio status.

A live session produces one run. Each replay adds a run. Nothing is overwritten.
`device_id` is created with an exclusive create: processes that start together on a fresh
folder (one per camera, D-022) end up with the same id; a file that is not a UUIDv4 is
replaced with a warning.
The session folder is created once the source has opened (D-020). Failures before that (bad
ref, model load, `source_open_failed`) are printed and exit non-zero; they leave no folder.

**Durability (D-020).** One writer thread owns every file. CSV rows are flushed and
`session.json` is rewritten (temp file, then replace) within a second of each new event, so
after a crash the CSVs are readable up to the last flush and `session.json` stays valid with
status `running`. The final status, `ended_at` and counts are written in a `finally` block.

## 2. `session.json`

```json
{
  "contract_version": "0.10.0",
  "session_id": "uuid",
  "device_id": "uuid",
  "camera_id": "cam1 | null",
  "group_id": "token | null",
  "started_at": "2026-10-07T18:00:00Z",
  "ended_at": "2026-10-07T18:45:00Z",
  "status": "running | ended | interrupted | error",
  "source": {"kind": "camera | stream | file", "ref": "1", "width": 1280, "height": 720,
             "reported_fps": 30.0, "link": "usb | wifi | builtin | file"},
  "registration": {"date": "2026-10-07", "team_ids": ["uuid"]},
  "recording": {"enabled": true, "path": "video.mp4", "sha256": null, "locked": true},
  "runs": ["uuid"],
  "events": [{"t_wall": "...", "t_mono": 12.3, "kind": "source_lost", "detail": "..."}],
  "calibration": {"calibration_id": "uuid", "check_error_m": 0.12}
}
```

`camera_id` and `group_id` (0.6.0) identify one camera inside a multi-camera recording
(D-022): `camera_id` is a label chosen by the user (`--camera-id`, 1-32 characters of
`A-Za-z0-9_-`), `group_id` is shared by every session started together (`--group-id`, 1-64
characters of `A-Za-z0-9_-`; the launcher writes a UUIDv4). Both are `null` when not given. Each
camera is its own session with its own clock; nothing links frames across cameras. The folder is
`<camera_id>_<session_id>` when `camera_id` is set, else `<session_id>`; the folder name is
never parsed, `session_id` inside the file is the identity.
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
`calibration` is `null` when no calibration was active; otherwise it identifies the immutable
calibration used by this session and records its mean held-out check residual in metres.

## 3. `run.json`

```json
{
  "contract_version": "0.10.0",
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
  "counts": {"captured": 0, "processed": 0, "dropped": 0, "unprocessed": 0, "rec_dropped": 0},
  "calibration": {"calibration_id": "uuid", "check_error_m": 0.12,
                  "homography_image_to_court": [[0.01,0,0],[0,0.01,0],[0,0,1]],
                  "court": {"length_m": 28.0, "width_m": 15.0},
                  "image_size": {"width": 1280, "height": 720}}
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
as its timestamp (D-016). `tracker.params` records the effective installed tracker arguments.
`calibration` is `null` when uncalibrated. Otherwise it records the calibration ID, mean held-out
check residual, court type and bounds, projection matrix and image size used by this run. Keeping the
projection in `run.json` permits offline report regeneration after later recalibration. The
loaded calibration is rejected before processing if saved image dimensions differ from the opened
capture dimensions. If a later frame has another size, the run logs an `error` event and writes
empty calibrated positions for its tracks; the homography is used again only when frames return to
the saved dimensions. The HTTP preview also suppresses the court overlay on a differently sized
frame.
For ByteTrack timestamp mode, `lost_track_buffer` is a count of 30 FPS frames and the
effective lost-track duration is `lost_track_buffer / 30` seconds, rounded to the nearest
frame when configured with `--track-lost-secs`.

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
| x_m, y_m | float/empty | projected box bottom-centre in court metres; empty without calibration, and empty when the point cannot be projected (on or beyond the horizon, or not finite): never 0 |
| calibration_id | uuid/empty | calibration used for the projection; empty without calibration |
| position_method | str/empty | `box_bottom_center` when calibrated; empty without calibration |
| in_court | bool/empty | `true` or `false`, lowercase: whether projected point is within court bounds; empty without calibration and for a point that cannot be projected |

Out-of-court points are retained, with `in_court=false`; they are not clamped to court bounds.
A point that cannot be projected (on or beyond the camera's horizon, or not finite) keeps its
pixel box and its `calibration_id`, with `x_m`, `y_m` and `in_court` empty; the writer records
an `error` event with the count (the first time, then at most every 30 s, and a final count when
the run closes). `position_method` is spelled `box_bottom_center` in this file; `report.json`
`positions.point` spells the same estimate `bottom_centre` (section 8): two fields, two spellings,
both fixed in 0.10.0.
The image point is `((x1 + x2) / 2, y2)`. The position method describes the box estimate,
not a measured anatomical foot point.

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

## 8. `report.json`

Written to `runs/<run_id>/report.json` at the end of a session and by
`python -m services.edge.report` (v0 report, D-023). It is computed only from the run's own
files (`session.json`, `run.json`, `frames.csv`, `tracks.csv`); rerunning it replaces the file.
One report per run, one per camera: there is no fusion across cameras.

```json
{
  "contract_version": "0.10.0",
  "run_id": "uuid",
  "session_id": "uuid",
  "camera_id": "cam1 | null",
  "group_id": "token | null",
  "generated_at": "2026-10-13T18:46:00Z",
  "positions": {"unit": "px", "point": "bottom_centre", "calibrated": false,
                 "calibration_id": null, "check_error_m": null},
  "params": {
    "max_gap": {"value": 1.0, "unit": "s"},
    "smooth_window": {"value": 3, "unit": "samples"},
    "min_valid_intervals": {"value": 2, "unit": "intervals"},
    "short_track": {"value": 1.0, "unit": "s"},
    "stationary_below": {"value": 40.0, "unit": "px/s"},
    "walking_below": {"value": 400.0, "unit": "px/s"}
  },
  "session": {
    "status": "running | ended | interrupted | error",
    "detection": true,
    "duration": {"value": 31.2, "unit": "s"},
    "n_captured": 120, "n_processed": 59, "n_dropped": 61, "n_unprocessed": 0,
    "processed_fps": {"value": 1.9, "unit": "frames/s"},
    "drop_rate": {"value": 50.8, "unit": "percent"},
    "coverage": {"value": 96.6, "unit": "percent"},
    "n_tracks": 5, "n_short_tracks": 2,
    "frame_interval_median": {"value": 0.52, "unit": "s"},
    "frame_interval_max": {"value": 1.4, "unit": "s"},
    "app_delay_p50": {"value": 520.0, "unit": "ms"},
    "app_delay_p95": {"value": 640.0, "unit": "ms"},
    "app_delay_max": {"value": 700.0, "unit": "ms"},
    "events": [{"kind": "interrupted", "t_wall": "2026-10-13T18:45:59Z",
                "t_since_t0": {"value": 30.9, "unit": "s"}, "detail": "Ctrl+C"}]
  },
  "tracks": [
    {
      "track_id": 3, "first_seen": {"value": 2.0, "unit": "s"},
      "last_seen": {"value": 9.5, "unit": "s"}, "visible": {"value": 7.5, "unit": "s"},
      "n_samples": 12, "median_sample_interval": {"value": 0.5, "unit": "s"},
      "n_valid_intervals": 10, "n_gaps_excluded": 1, "gap_time": {"value": 2.0, "unit": "s"},
      "valid_time": {"value": 5.0, "unit": "s"},
      "path_length": {"value": 800.0, "unit": "px"},
      "mean_speed": {"value": 160.0, "unit": "px/s"},
      "max_speed": {"value": 300.0, "unit": "px/s"},
      "activity": {"stationary": {"value": 10.0, "unit": "percent"},
                   "walking": {"value": 90.0, "unit": "percent"},
                   "running": {"value": 0.0, "unit": "percent"}},
      "short": false
    }
  ],
  "caveats": ["positions are pixels, not calibrated"]
}
```

**Every measurement is `{"value", "unit"}`.** The unit comes from the position function
(pixels now, metres once calibration supplies one): speeds are `<unit>/s`, so the report code
does not change with calibration. A `value` of `null` (never `0`) carries a `reason`, for example
`single sample` or `fewer than 2 valid intervals`. Counts are plain integers named `n_*`.
Percentages are 0-100 with unit `percent`.

Contract 0.10.0 adds `fiba_half` (14 x 15 m, basket baseline x=0, midcourt x=14) alongside
`fiba_full` (28 x 15 m) and `custom`. Calibration and run/session/report metadata record the
selected court type and dimensions. Its landmarks are the `fiba_full` landmarks at x <= 14 m,
with identical coordinates, plus corners and centre on x=14 m. Out-of-bounds projected points
remain in metres and have `in_court=false`. The existing fit spread threshold remains 0.1 in
image and court coordinates.

- **Position** of a person in a frame is the bottom-centre of the track's box,
  `((x1 + x2) / 2, y2)`, in the position function's unit. A sample is that point at the frame's
  `t_recv` (frames.csv, joined on `seq`; tracks.csv has no time of its own).
  For calibrated runs, the report uses the `x_m` and `y_m` values written in `tracks.csv`; an
  empty position remains invalid and is never reconstructed from the pixel box.
- **Smoothing.** Per track, positions are smoothed with a moving median of `smooth_window`
  samples (default 3), applied separately to x and y, within runs of consecutive samples at most
  `max_gap` apart. The window is symmetric and shrinks to 1 at the ends of a run, so the first and
  last sample of a run stay raw.
- **Intervals.** An interval is a pair of consecutive samples of one track. It is valid when
  its length is at most `max_gap` seconds (default 1.0; `--max-gap`). Longer ones are excluded
  from path length, speed and activity and counted in `n_gaps_excluded` / `gap_time`.
  `path_length` is the sum of the valid intervals' straight-line distances (so it excludes the
  gaps and underestimates a curved path), `null` when there is no valid interval.
  `mean_speed` is `path_length / valid_time`; `max_speed` is the largest interval speed. Both are
  `null` with a reason when there are fewer than `min_valid_intervals` (default 2) valid intervals.
- **Activity** is the share of `valid_time` spent below `stationary_below` (stationary), below
  `walking_below` (walking) or at or above it (running), by interval speed. The thresholds are in the
  position unit per second; the defaults for metres are 0.5 m/s (stationary) and 2.5 m/s
  (walking); the defaults for pixels, 40 and 400 px/s, are placeholders that depend on camera
  distance and angle, hence the caveat. `null` with a reason when there are fewer than `min_valid_intervals` valid intervals (a share
  of one interval is not a share).
- **Other definitions.** `median_sample_interval` is the median time between all consecutive
  samples of the track, gaps included (`null`: single sample). `frame_interval_median` and
  `frame_interval_max` are the time between consecutive processed frames' `t_recv`. A track is
  `short` when `visible` (first to last sample) is below `short_track`. The caveat about a low
  processing rate is added when `processed_fps` is below 5. An event's `t_since_t0` is its `t_mono`;
  an event that precedes the run's `t0` has `null` with the reason `event precedes t0`.
- **Session level.** `duration` is `run.json` `t0_wall` to `ended_at` (else the last processed
  frame's time). `processed_fps` and the app delay use the benchmark's definitions (D-019,
  D-020); `drop_rate = n_dropped / n_captured`; `coverage` is the share of processed frames with
  at least one detection (`null` when detection was off); `n_short_tracks` counts tracks
  visible (first to last sample) for less than `short_track` seconds, likely fragments or false
  positives. `n_captured`, `n_dropped` and `n_unprocessed` are `null` while `run.json` has no
  counts (a run that did not end). `events` lists every `session.json` event, `t_since_t0`
  being its `t_mono`.
- **`caveats`** (at least one) states what is uncalibrated or not validated; it always includes
  that positions are pixels when uncalibrated and that detections and tracks are not validated
  against ground truth, plus the processing rate of this run when it is low. Calibrated reports
  include a caveat naming the calibration ID and its mean held-out check error in metres, and
  `positions.calibration_id` / `positions.check_error_m`; text summaries print the check error
  once, in the header line, as a quality indicator, not a per-measurement uncertainty.
  `calibration_id` is the UUID the run recorded and `null` otherwise, so a report rebuilt from a
  hand-made `run.json` may be calibrated with a `null` ID. Track rows whose point cannot be
  projected are excluded from path length, speeds and activity and counted in a note; they are
  never counted as malformed CSV rows.

## 9. Camera calibration file

Calibration JSON and its raw JPEG audit frame live under the user's local application data,
never in the repository or session folder. The JPEG filename is `frame.jpg` next to the JSON.
Coordinates use an origin at the near-left corner of the court diagram: court `x` runs
along court length and `y` runs across court width. Custom courts specify
their measured length and width; named or user-entered landmarks are stored as explicit metres.

The calibration file records contract version, UUID calibration ID, camera ID and creation time;
court kind/dimensions/landmarks; capture image width/height; the image-to-court 3x3 homography;
all image/court points and their `calibration` or `check` role; each point's Euclidean residual in
metres; separate calibration/check means and maximum check residual; the configured maximum
check mean; and whether the user forced saving above that error. At least four fit points and two
held-out check points are required. Check points never participate in fitting. No two points may
mark the same place (within 1e-6 m on the court or 1 px in the image), so a check point is a
different floor mark from every fit point; the fit points must not be collinear or bunched (the
square root of the ratio of their minor to major variance is at least 0.1, in the image and on the
court). The configured maximum check mean is at most 2.0 m. Saving anyway can override the
check-mean threshold only, not these minimums, the point rules or the homography checks
(finite, invertible, condition number at most 1e7, every point in front of the horizon). A loader
recomputes the residuals, the mean errors and `forced` from the homography and the points and
refuses a file where they disagree. The audit frame is the JPEG-encoded copy (lossy, no
overlays, at the capture size) of the frame the user saw when placing the image points; the
Studio's later comparison decodes that JPEG, so it is the frame as shown, not the sensor's raw
pixels.

### Studio calibration API (local, not synced; no contract version of its own)

All paths are served on loopback by `python -m services.app`.

- `GET /api/court?kind=custom|fiba_full&length_m=&width_m=` returns `{kind, length_m, width_m,
  landmarks: {name: [x, y]}, lines: [[[x, y], ...], ...]}` in metres: the landmarks the fit and
  the saved file use and the lines the diagram draws. Markings with a fixed size (key 5.8 x 4.9 m,
  basket 1.575 m from the baseline, centre circle radius 1.8 m) keep it on a custom court and are
  left out when the court is too small for them. `422` for an invalid court.
- `GET /api/cameras/{id}/calibration/frame` returns `image/jpeg` with headers `X-Frame-Token`
  (send it back with fit and save), `X-Frame-Width` and `X-Frame-Height` (the real size of the
  frame). A camera that is recording is read from its recording process; an idle camera is
  opened with the recorder's own capture size (`DEFAULT_CAPTURE_SIZE`, 1280 x 720). `502` when no
  frame arrives.
- `POST /api/cameras/{id}/calibration/fit` and `PUT /api/cameras/{id}/calibration` take
  `{frame_token, court_kind, length_m, width_m, custom_landmarks?, max_check_error_m (<= 2.0),
  save_anyway?, points: [{image_px, court_m, role}]}`. `fit` previews and needs only four fit
  points; `PUT` needs two check points, applies the error limit unless `save_anyway`, and saves.
  Both return `homography_image_to_court`, `calibration_errors_m`, `check_errors_m`,
  `calibration_mean_m`, `check_mean_m`, `check_max_m`, `forced`, `point_errors_m` (in the order
  of the points sent), `projected_court_lines`, `court`, `ransac_threshold_m` and
  `ransac_dropped_points` (indices of fit points RANSAC left out); `PUT` adds `calibration` (the
  saved document) and `path`. A refusal is `422` with `{"detail": message}`: too few points, a
  check point on a fit point, collinear or bunched fit points, a singular homography, a limit
  above 2.0 m, a point outside the frame or court. `409` when the frame token is stale.
- `GET /api/cameras/{id}/calibration` returns the active document, `null` when there is none, or
  `422` when it cannot be read;
  `GET /api/cameras/{id}/calibration/compare` returns `{audit_frame, fresh_frame,
  difference_score, warning}` (base64 JPEGs) for the saved audit frame against a fresh one.
- `GET /api/status` cameras carry `calibration` (`{calibration_id, check_error_m}` or `null`) and
  `calibration_warning` (why a saved calibration was not used, or `null`). A camera whose frame
  size differs from the calibration at its first frame fails with both sizes in `error`.

## 10. Studio camera settings (`%LOCALAPPDATA%/pointr/cameras.json`)

The settings file is a JSON list. Each entry contains a stable `camera_id`, a unique display
`name`, `source` (a camera index, local file path for file testing, or an `http`, `https` or
`rtsp` URL), `link`, `det_size`, optional `fps_cap`, and `enabled`. Existing `camera_id` values
remain the identity used by sessions and calibrations; omitted `name`, `enabled`, and `fps_cap`
load as `camera_id`, `true`, and `null`. The Studio defaults are model-default detection size,
no FPS cap, and enabled. Allowed detection sizes are 320, 352, 384, 416, 448, 480, 512, 544,
576, 608, 640, 672, 704, 736, 768, 800, 832, 864, 896, 928, 960, 992, 1024, 1056, 1088,
1120, 1152, 1184, 1216, 1248, and 1280. FPS cap is an optional positive number no greater than
60; for camera indices it is requested from the capture backend. It is not a measured or
guaranteed frame rate. Only enabled cameras start. Names must be unique without case
distinctions. URL credentials are accepted for camera streams but masked in all Studio output.
Loopback and link-local URL hosts and schemes other than HTTP, HTTPS, and RTSP are refused.

Writes use a temporary file and atomic replacement. Before replacement, the prior valid file is
preserved as `cameras.json.bak`. An unreadable or invalid settings file loads as an empty camera
list and produces a visible warning; it is not silently replaced with the backup. The camera
configuration is a local Studio setting and does not alter session, run, report, or calibration
field meanings. This additive settings contract is recorded under contract version 0.10.0.
