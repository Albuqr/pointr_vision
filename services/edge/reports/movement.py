"""Movement metrics of one track from sparse, uneven samples (D-023, DATA_CONTRACTS section 8).

Pure functions: no files, no live state. Positions come in through a PositionMap, so the same
code reports pixels today and metres once calibration supplies a map.
"""

import math
import statistics
from dataclasses import dataclass
from typing import Protocol


class PositionMap(Protocol):
    """Pixel point -> output point. `unit` names the output; the thresholds are the default
    activity limits in `unit`/s (they depend on the map: metres need other numbers than pixels)."""

    unit: str
    calibrated: bool
    stationary_below: float
    walking_below: float

    def __call__(self, x: float, y: float) -> tuple[float, float] | None:
        """None when the point has no valid position (calibrated maps only)."""
        ...


@dataclass(frozen=True)
class PixelPositions:
    """The v0 map: the pixel point itself. The default thresholds are placeholders: how many
    pixels a walking person covers per second depends on camera distance and angle."""

    unit: str = "px"
    calibrated: bool = False
    stationary_below: float = 40.0
    walking_below: float = 400.0

    def __call__(self, x: float, y: float) -> tuple[float, float]:
        return x, y


@dataclass(frozen=True)
class Sample:
    t: float  # s since t0
    x: float  # output unit
    y: float


@dataclass(frozen=True)
class Params:
    max_gap: float = 1.0  # s: longer intervals do not count for path, speed or activity
    smooth_window: int = 3  # samples, odd
    min_valid_intervals: int = 2  # fewer: speed is null
    short_track: float = 1.0  # s: a track visible for less is a likely fragment
    stationary_below: float | None = None  # unit/s; None: the PositionMap's default
    walking_below: float | None = None


@dataclass(frozen=True)
class TrackMetrics:
    track_id: int
    first_seen: float
    last_seen: float
    n_samples: int
    median_interval: float | None  # over all consecutive pairs, gaps included
    n_valid_intervals: int
    n_gaps_excluded: int
    gap_time: float
    valid_time: float
    path_length: float | None
    mean_speed: float | None
    max_speed: float | None
    speed_reason: str | None  # why the speeds are None
    activity: dict[str, float] | None  # stationary / walking / running, % of valid_time
    activity_reason: str | None

    @property
    def visible(self) -> float:
        return self.last_seen - self.first_seen


def runs(samples: list[Sample], max_gap: float) -> list[list[Sample]]:
    """Split into runs of consecutive samples at most max_gap apart (samples sorted by t)."""
    out: list[list[Sample]] = []
    for s in samples:
        if out and 0 < s.t - out[-1][-1].t <= max_gap:
            out[-1].append(s)
        else:
            out.append([s])
    return out


def smooth(run: list[Sample], window: int) -> list[Sample]:
    """Moving median of x and y. The window is symmetric and shrinks to 1 at the ends, so a
    short run keeps its motion (a two-sample run is not averaged into a standstill)."""
    half = window // 2
    out = []
    for i, s in enumerate(run):
        h = min(half, i, len(run) - 1 - i)
        part = run[i - h : i + h + 1]
        out.append(
            Sample(s.t, statistics.median(p.x for p in part), statistics.median(p.y for p in part))
        )
    return out


def track_metrics(
    track_id: int, samples: list[Sample], params: Params, positions: PositionMap
) -> TrackMetrics:
    """Metrics of one track. `samples` are in the output unit, any order, distinct times."""
    samples = sorted(samples, key=lambda s: s.t)
    stationary = (
        positions.stationary_below if params.stationary_below is None else params.stationary_below
    )
    walking = positions.walking_below if params.walking_below is None else params.walking_below
    deltas = [b.t - a.t for a, b in zip(samples, samples[1:], strict=False)]
    # intervals inside a run are valid; every other consecutive pair is a gap
    distances: list[tuple[float, float]] = []  # (dt, distance) of the valid intervals
    for run in runs(samples, params.max_gap):
        sm = smooth(run, params.smooth_window)
        distances += [
            (b.t - a.t, math.hypot(b.x - a.x, b.y - a.y)) for a, b in zip(sm, sm[1:], strict=False)
        ]
    gaps = [d for d in deltas if not 0 < d <= params.max_gap]
    valid_time = sum(dt for dt, _ in distances)
    path = sum(d for _, d in distances) if distances else None
    mean = max_ = reason = None
    if len(samples) == 1:
        reason = "single sample"
    elif not distances:
        reason = f"no two samples within {params.max_gap:g} s of each other"
    elif len(distances) < params.min_valid_intervals:
        reason = f"{len(distances)} valid interval(s), fewer than {params.min_valid_intervals}"
    else:
        mean = path / valid_time
        max_ = max(d / dt for dt, d in distances)
    activity = None
    if len(distances) >= params.min_valid_intervals:  # one interval is not a share
        share = dict.fromkeys(("stationary", "walking", "running"), 0.0)
        for dt, d in distances:
            v = d / dt
            share["stationary" if v < stationary else "walking" if v < walking else "running"] += dt
        activity = {k: 100 * v / valid_time for k, v in share.items()}
    return TrackMetrics(
        track_id,
        samples[0].t,
        samples[-1].t,
        len(samples),
        statistics.median(deltas) if deltas else None,
        len(distances),
        len(gaps),
        sum(gaps),
        valid_time,
        path,
        mean,
        max_,
        reason,
        activity,
        None if activity else (reason or "no valid interval"),
    )
