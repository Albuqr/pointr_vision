"""Build a report from a run folder (D-023, DATA_CONTRACTS section 8).

Only files are read: runs/<run_id>/{run.json,frames.csv,tracks.csv} and the session's
session.json. Nothing here touches live state, so a finished (or crashed) run can be reported
again at any time.
"""

import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from services.edge.calibration.homography import CalibrationPositions
from services.edge.capture.types import utc_now
from services.edge.perception.loop import delay_stats, rates
from services.edge.reports.movement import (
    Params,
    PixelPositions,
    PositionMap,
    Sample,
    TrackMetrics,
    track_metrics,
)
from services.edge.session.writer import CONTRACT_VERSION, write_json

LOW_FPS = 5.0  # processed fps below this: say that samples are sparse
MAX_TRACK_ROWS = 20  # tracks printed in the console summary (report.json has them all)
FRAME_NUMBERS = ("t_recv", "t_proc_start", "t_proc_end", "app_delay_ms")


@dataclass(frozen=True)
class Q:
    """A measurement: a value and its unit. A None value must say why."""

    value: float | None
    unit: str
    reason: str | None = None

    def as_dict(self) -> dict:
        if self.value is None:
            return {"value": None, "unit": self.unit, "reason": self.reason or "not available"}
        return {"value": self.value, "unit": self.unit}


@dataclass(frozen=True)
class SessionStats:
    status: str
    detection: bool
    duration: Q
    n_captured: int | None
    n_processed: int
    n_dropped: int | None
    n_unprocessed: int | None
    processed_fps: Q
    drop_rate: Q
    coverage: Q
    n_tracks: int
    n_short_tracks: int
    frame_interval_median: Q
    frame_interval_max: Q
    app_delay_p50: Q
    app_delay_p95: Q
    app_delay_max: Q
    events: list[dict]


@dataclass(frozen=True)
class Report:
    run_id: str
    session_id: str
    camera_id: str | None
    group_id: str | None
    generated_at: str
    court: dict | None
    unit: str
    calibrated: bool
    calibration_id: str | None
    check_error_m: float | None
    params: Params  # thresholds resolved: never None here
    session: SessionStats
    tracks: list[TrackMetrics]
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        p, s, u = self.params, self.session, self.unit
        speed = f"{u}/s"
        return {
            "contract_version": CONTRACT_VERSION,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "camera_id": self.camera_id,
            "group_id": self.group_id,
            "generated_at": self.generated_at,
            "court": self.court,
            "positions": {
                "unit": u,
                "point": "bottom_centre",
                "calibrated": self.calibrated,
                "calibration_id": self.calibration_id,
                "check_error_m": self.check_error_m,
            },
            "params": {
                "max_gap": Q(p.max_gap, "s").as_dict(),
                "smooth_window": Q(p.smooth_window, "samples").as_dict(),
                "min_valid_intervals": Q(p.min_valid_intervals, "intervals").as_dict(),
                "short_track": Q(p.short_track, "s").as_dict(),
                "stationary_below": Q(p.stationary_below, speed).as_dict(),
                "walking_below": Q(p.walking_below, speed).as_dict(),
            },
            "session": {
                "status": s.status,
                "detection": s.detection,
                "duration": s.duration.as_dict(),
                "n_captured": s.n_captured,
                "n_processed": s.n_processed,
                "n_dropped": s.n_dropped,
                "n_unprocessed": s.n_unprocessed,
                "processed_fps": s.processed_fps.as_dict(),
                "drop_rate": s.drop_rate.as_dict(),
                "coverage": s.coverage.as_dict(),
                "n_tracks": s.n_tracks,
                "n_short_tracks": s.n_short_tracks,
                "frame_interval_median": s.frame_interval_median.as_dict(),
                "frame_interval_max": s.frame_interval_max.as_dict(),
                "app_delay_p50": s.app_delay_p50.as_dict(),
                "app_delay_p95": s.app_delay_p95.as_dict(),
                "app_delay_max": s.app_delay_max.as_dict(),
                "events": s.events,
            },
            "tracks": [self._track(t) for t in self.tracks],
            "caveats": self.caveats,
        }

    def _track(self, t: TrackMetrics) -> dict:
        u, speed = self.unit, f"{self.unit}/s"
        act = t.activity or {}
        return {
            "track_id": t.track_id,
            "first_seen": Q(t.first_seen, "s").as_dict(),
            "last_seen": Q(t.last_seen, "s").as_dict(),
            "visible": Q(t.visible, "s").as_dict(),
            "n_samples": t.n_samples,
            "median_sample_interval": Q(t.median_interval, "s", "single sample").as_dict(),
            "n_valid_intervals": t.n_valid_intervals,
            "n_gaps_excluded": t.n_gaps_excluded,
            "gap_time": Q(t.gap_time, "s").as_dict(),
            "valid_time": Q(t.valid_time, "s").as_dict(),
            "path_length": Q(t.path_length, u, t.speed_reason).as_dict(),
            "mean_speed": Q(t.mean_speed, speed, t.speed_reason).as_dict(),
            "max_speed": Q(t.max_speed, speed, t.speed_reason).as_dict(),
            "activity": {
                k: Q(act.get(k), "percent", t.activity_reason).as_dict()
                for k in ("stationary", "walking", "running")
            },
            "short": t.visible < self.params.short_track,
        }


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def run_dirs(session_dir: Path) -> list[Path]:
    """The session's run folders, in the order session.json lists them."""
    ids = load_json(session_dir / "session.json")["runs"]
    return [session_dir / "runs" / r for r in ids]


def build_report(
    run_dir: Path, params: Params | None = None, positions: PositionMap | None = None
) -> Report:
    """The report of one run folder. Raises OSError/ValueError if its files are missing or
    unreadable; a run that never finished (no counts, no end time) still reports."""
    run_dir = Path(run_dir)
    params = params or Params()
    run = load_json(run_dir / "run.json")
    calibration = run.get("calibration")
    positions = positions or (
        CalibrationPositions(calibration) if calibration else PixelPositions()
    )
    params = replace(
        params,
        stationary_below=positions.stationary_below
        if params.stationary_below is None
        else params.stationary_below,
        walking_below=positions.walking_below
        if params.walking_below is None
        else params.walking_below,
    )
    if params.walking_below <= params.stationary_below:
        raise ValueError("walking threshold must be greater than stationary threshold")
    session = load_json(run_dir.parent.parent / "session.json")
    bad = 0  # rows that do not parse (a truncated last line): skipped and said
    frames = []
    for r in read_csv(run_dir / "frames.csv"):
        try:
            int(r["seq"])
            [float(r[k]) for k in FRAME_NUMBERS]
        except (TypeError, ValueError, KeyError):
            bad += 1
        else:
            frames.append(r)
    frames.sort(key=lambda r: int(r["seq"]))
    time_of = {int(r["seq"]): float(r["t_recv"]) for r in frames}

    by_track: dict[int, dict[int, Sample]] = defaultdict(dict)  # per seq: one sample each
    no_time = 0
    no_position = 0
    for r in read_csv(run_dir / "tracks.csv"):
        try:
            seq, tid = int(r["seq"]), int(r["track_id"])
            if calibration and positions.calibrated and "x_m" in r:
                # The writer leaves these cells empty when the frame size changed or the
                # homography could not project the point. Re-projecting the pixel box here
                # would turn an intentionally invalid position back into a valid one.
                if not r.get("x_m") or not r.get("y_m"):
                    no_position += 1
                    continue
                x_m, y_m = float(r["x_m"]), float(r["y_m"])
                xy = (x_m, y_m) if math.isfinite(x_m) and math.isfinite(y_m) else None
            else:
                xy = positions((float(r["x1"]) + float(r["x2"])) / 2, float(r["y2"]))
        except (TypeError, ValueError, KeyError):
            bad += 1
            continue
        if xy is None:  # no valid position: not a path point, said in the notes
            no_position += 1
            continue
        x, y = xy
        if seq not in time_of:
            no_time += 1
            continue
        by_track[tid][seq] = Sample(time_of[seq], x, y)
    tracks = [
        track_metrics(i, list(s.values()), params, positions) for i, s in sorted(by_track.items())
    ]

    stats = session_stats(run, session, frames, tracks, params)
    notes = []
    if bad:
        notes.append(f"{bad} malformed CSV row(s) were skipped")
    if no_position:
        notes.append(
            f"{no_position} track row(s) could not be projected to {positions.unit} (on or beyond "
            "the horizon of the calibration) and were excluded from path length and speeds"
        )
    if no_time:
        notes.append(f"{no_time} track row(s) had no matching processed frame and were skipped")
    if seconds_between(run.get("t0_wall"), run.get("ended_at")) is None:
        notes.append(
            "The run has no end time: duration is the last processed frame's time, a lower bound"
        )
    return Report(
        run["run_id"],
        run["session_id"],
        session.get("camera_id"),
        session.get("group_id"),
        utc_now(),
        (
            {
                "type": calibration.get("court", {}).get(
                    "type", calibration.get("court", {}).get("kind")
                ),
                "length_m": calibration["court"]["length_m"],
                "width_m": calibration["court"]["width_m"],
            }
            if calibration and calibration.get("court")
            else None
        ),
        positions.unit,
        positions.calibrated,
        getattr(positions, "calibration_id", None),
        getattr(positions, "check_error_m", None),
        params,
        stats,
        tracks,
        caveats(positions, params, stats, notes),
    )


def session_stats(
    run: dict, session: dict, frames: list[dict], tracks: list[TrackMetrics], params: Params
) -> SessionStats:
    counts = run.get("counts")
    detection = run.get("detector") is not None
    starts = [float(r["t_proc_start"]) for r in frames]
    ends = [float(r["t_proc_end"]) for r in frames]
    fps, drop = rates(
        counts["captured"] if counts else 0,
        counts["dropped"] if counts else 0,
        len(frames),
        min(starts) if starts else None,
        max(ends) if ends else None,
    )
    no_counts = "run has no counts (it did not end)"
    duration = seconds_between(run.get("t0_wall"), run.get("ended_at"))
    duration_q = (
        Q(duration, "s")
        if duration is not None
        else Q(max(ends), "s")
        if ends
        else Q(None, "s", "no end time and no processed frames")
    )
    delays = delay_stats([float(r["app_delay_ms"]) for r in frames])
    arrivals = [float(r["t_recv"]) for r in frames]
    intervals = [b - a for a, b in zip(arrivals, arrivals[1:], strict=False)]
    seen = [r["n_detections"] for r in frames]
    if not detection:
        coverage = Q(None, "percent", "detection was off")
    elif not frames:
        coverage = Q(None, "percent", "no processed frames")
    else:
        coverage = Q(100 * sum(int(n or 0) >= 1 for n in seen) / len(frames), "percent")
    none_frames = "no processed frames"
    few_frames = "fewer than 2 processed frames"
    return SessionStats(
        status=session["status"],
        detection=detection,
        duration=duration_q,
        n_captured=counts["captured"] if counts else None,
        n_processed=len(frames),
        n_dropped=counts["dropped"] if counts else None,
        n_unprocessed=counts["unprocessed"] if counts else None,
        processed_fps=Q(
            fps if len(frames) >= 2 else None, "frames/s", "fewer than 2 processed frames"
        ),
        drop_rate=Q(
            100 * drop if drop is not None else None,
            "percent",
            no_counts if counts is None else "no frames captured",
        ),
        coverage=coverage,
        n_tracks=len(tracks),
        n_short_tracks=sum(t.visible < params.short_track for t in tracks),
        frame_interval_median=Q(
            statistics.median(intervals) if intervals else None, "s", few_frames
        ),
        frame_interval_max=Q(max(intervals) if intervals else None, "s", few_frames),
        app_delay_p50=Q(delays["p50"] if delays else None, "ms", none_frames),
        app_delay_p95=Q(delays["p95"] if delays else None, "ms", none_frames),
        app_delay_max=Q(delays["max"] if delays else None, "ms", none_frames),
        events=[
            {
                "kind": e["kind"],
                "t_wall": e["t_wall"],
                "t_since_t0": Q(e["t_mono"], "s", "event precedes t0").as_dict(),
                "detail": e["detail"],
            }
            for e in session["events"]
        ],
    )


def caveats(positions: PositionMap, params: Params, s: SessionStats, notes: list[str]) -> list[str]:
    out = [
        f"Positions are the bottom-centre of the box in {positions.unit}"
        + (
            ": uncalibrated pixels, so distances and speeds depend on camera distance and angle"
            " and are not metres"
            if positions.unit == "px"
            else ""
        ),
        f"Speed uses only intervals of at most {params.max_gap:g} s between consecutive samples,"
        f" after a {params.smooth_window}-sample moving median; path length excludes the gaps and"
        " underestimates a curved path (and box jitter adds path even to a person standing still);"
        " max speed is the fastest single interval and is noisy",
        (
            f"Activity thresholds ({params.stationary_below:g} and {params.walking_below:g} m/s) "
            "are configurable; check-point residual is a quality indicator, not a guarantee of "
            "ground-truth accuracy"
            if positions.calibrated
            else f"Activity thresholds ({params.stationary_below:g} and "
            f"{params.walking_below:g} {positions.unit}/s) are placeholders: uncalibrated pixels, "
            "thresholds depend on camera distance"
        ),
        "Track IDs are temporary and not people: a person who leaves the frame or is occluded"
        " gets a new ID, and short tracks may be false positives",
        "Detections and tracks are not validated against ground truth",
    ]
    if positions.calibrated:
        error = getattr(positions, "check_error_m", None)
        out.insert(
            1,
            f"Calibration {getattr(positions, 'calibration_id', None) or 'unknown'}: mean error "
            f"on held-out check points "
            f"{f'{error:.3f} m' if error is not None else 'not recorded'}; points on or beyond "
            "the camera's horizon have no position and are excluded",
        )
    fps = s.processed_fps.value
    if fps is not None and fps < LOW_FPS:
        median = s.frame_interval_median.value
        out.append(
            f"Low processing rate in this run ({fps:.2f} frames/s, median interval"
            + (f" {median:.2f} s" if median is not None else " n/a")
            + "): samples per track are sparse and uneven"
        )
    unprojectable = any("could not be projected" in note for note in notes)
    if s.n_tracks == 0 and s.coverage.value and unprojectable:
        out.append("Track rows were present, but none had a valid projected position")
    elif s.n_tracks == 0 and s.coverage.value:
        slow = (
            ", which a low processing rate rarely gives"
            if fps is not None and fps < LOW_FPS
            else ""
        )
        out.append(
            "People were detected but no track formed: a track needs 2 consecutive detections"
            " and a score of at least 0.7" + slow
        )
    out += notes
    if s.status == "running":
        out.append("The session did not end (status running): counts and end time are missing")
    return out


def write_report(run_dir: Path, **kw) -> Report:
    """Build the report and write runs/<run_id>/report.json (replaces an older one)."""
    report = build_report(run_dir, **kw)
    write_json(Path(run_dir) / "report.json", report.to_dict())
    return report


# -- text ------------------------------------------------------------------------------------


def n(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def event_text(e: dict) -> str:
    v = e["t_since_t0"]["value"]
    return f"{e['kind']} {'-' if v is None else format(v, '+.1f') + ' s'}"


def format_summary(r: Report) -> str:
    """Console text of one report: session lines, one row per track, caveats."""
    s, u = r.session, r.unit
    name = r.camera_id or r.session_id[:8]
    calibration_note = (
        f", check error {r.check_error_m:.3f} m" if r.check_error_m is not None else ""
    )
    lines = [
        f"report {name} (run {r.run_id[:8]}, session {s.status}, positions in {u},"
        f" {'calibrated' if r.calibrated else 'uncalibrated'}{calibration_note})",
        f"  duration {n(s.duration.value)} s | processed {s.n_processed} frames at"
        f" {n(s.processed_fps.value, 2)} fps | dropped {n(s.drop_rate.value)}% |"
        f" app delay p50 {n(s.app_delay_p50.value, 0)} / p95 {n(s.app_delay_p95.value, 0)} ms",
        f"  frame interval median {n(s.frame_interval_median.value, 2)} s,"
        f" max {n(s.frame_interval_max.value, 2)} s",
        f"  coverage {n(s.coverage.value)}% of processed frames have >= 1 detection |"
        f" tracks {s.n_tracks}, {s.n_short_tracks} shorter than {r.params.short_track:g} s",
    ]
    if s.events:
        shown = ", ".join(event_text(e) for e in s.events[:8])
        more = f" (+{len(s.events) - 8} more)" if len(s.events) > 8 else ""
        lines.append(f"  events ({len(s.events)}): {shown}{more}")
    else:
        lines.append("  events: none")
    if r.tracks:
        lines.append(f"  tracks ({u}, {u}/s; intervals over {r.params.max_gap:g} s excluded):")
        lines.append(
            f"    {'id':>4} {'first':>7} {'last':>7} {'seen':>6} {'n':>4} {'med dt':>7}"
            f" {'path':>9} {'mean':>8} {'max':>8}  stat/walk/run %"
        )
        top = sorted(r.tracks, key=lambda t: -t.visible)[:MAX_TRACK_ROWS]
        shown = sorted(top, key=lambda t: t.track_id)
        for t in shown:
            a = t.activity
            share = "n/a" if a is None else "/".join(f"{a[k]:.0f}" for k in a)
            lines.append(
                f"    {t.track_id:>4} {t.first_seen:>7.1f} {t.last_seen:>7.1f} {t.visible:>6.1f}"
                f" {t.n_samples:>4} {n(t.median_interval, 2):>7} "
                f"{n(t.path_length):>9} {n(t.mean_speed):>8}"
                f" {n(t.max_speed):>8}  {share}"
            )
        if len(shown) < len(r.tracks):
            lines.append(
                f"    ... {len(r.tracks) - len(shown)} shorter track(s) not shown"
                " (report.json has all)"
            )
        for t in shown:
            if t.speed_reason:
                lines.append(f"    track {t.track_id}: speed n/a ({t.speed_reason})")
    lines.append("  caveats:")
    lines += [f"    - {c}" for c in r.caveats]
    return "\n".join(lines)


TABLE_HEADER = ("camera", "duration s", "proc fps", "coverage %", "tracks", "short", "events")


def table_row(r: Report) -> tuple[str, ...]:
    """The cells of one camera's row in the launcher's report table."""
    s = r.session
    return (
        r.camera_id or r.session_id[:8],
        n(s.duration.value),
        n(s.processed_fps.value, 2),
        n(s.coverage.value),
        str(s.n_tracks),
        str(s.n_short_tracks),
        str(len(s.events)),
    )
