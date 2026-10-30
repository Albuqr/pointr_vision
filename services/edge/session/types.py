"""Session layer types and Protocol (ARCHITECTURE.md section 4).

Fields follow DATA_CONTRACTS.md sections 2-4. RunMeta and RunCounts carry what run.json
needs (D-008, completed by D-020).
"""

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from services.edge.capture.types import SourceInfo
from services.edge.perception.types import TrackObs

# DATA_CONTRACTS.md section 2; the patterns are also in session.schema.json (a test compares)
CAMERA_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
GROUP_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True)
class SessionMeta:
    session_id: str  # UUIDv4
    device_id: str  # UUIDv4
    started_at: str  # UTC ISO-8601
    source: SourceInfo
    recording_enabled: bool
    camera_id: str | None = None  # label of this camera in a multi-camera recording (D-022)
    group_id: str | None = None  # shared by the sessions recorded together
    calibration: dict | None = None


@dataclass(frozen=True)
class RunMeta:
    """run.json fields known when the run starts; values are the contract's JSON objects."""

    run_id: str  # UUIDv4
    mode: str  # live | replay
    input: dict  # kind, ref, sha256, requested_width, requested_height
    detector: dict | None  # None when detection is off
    tracker: dict | None
    health: dict  # source-health thresholds
    runtime: dict  # python, platform, device, packages
    started_at: str  # UTC ISO-8601
    calibration: dict | None = None
    checks: list | None = None  # startup check results, null until they have run (0.11.0)
    clock: dict | None = None  # sensor offset and per-camera latency, null without them (0.11.0)
    objects: dict | None = None  # ball and rim layer settings, null when it is off (0.11.0)
    gaps: list | None = None  # null = not measured; SessionWriter.set_final fills it at the end
    outages: list | None = None  # same for the rim sensor outages (0.11.0)
    group: dict | None = None  # the group run sharing track IDs; null when run-scoped (0.14.0)
    ready: dict | None = None  # steps already reached at run start, e.g. model_loaded (0.15.0)
    power_start: dict | None = None  # power state read at run start; the end comes via set_final


@dataclass(frozen=True)
class RunCounts:
    captured: int
    processed: int
    dropped: int
    unprocessed: int
    rec_dropped: int | None = None  # None when recording is disabled
    failed_reads: int = 0  # read attempts returning no frame; normal source end excluded


@dataclass(frozen=True)
class FrameRecord:
    """One frames.csv row: one per processed frame, including frames with 0 detections."""

    seq: int
    t_recv: float  # s since t0
    t_proc_start: float  # s since t0
    t_proc_end: float  # s since t0
    n_detections: int | None  # None when detection is off
    n_tracks: int | None
    dropped_total: int  # capture's drop count when this frame was taken for processing
    t_video: float | None = None  # s in the source video, None when unknown (0.11.0)

    @property
    def app_delay_ms(self) -> float:
        """Frame received to processing done. Not camera-to-screen latency."""
        return (self.t_proc_end - self.t_recv) * 1000


@dataclass(frozen=True)
class SessionEvent:
    t_wall: str  # UTC ISO-8601
    t_mono: float | None  # s since t0; None if the event precedes t0
    kind: str  # an event kind from DATA_CONTRACTS.md section 2
    detail: str | None = None


@runtime_checkable
class PositionMap(Protocol):
    """Image point -> court metres for the rows of a calibrated run. Injected into the writer,
    which does not import the calibration package. A map may return None for a point that
    cannot be projected, and may raise: the writer leaves the position empty either way."""

    calibration_id: str

    def __call__(self, x: float, y: float) -> tuple[float, float] | None: ...

    def in_court(self, x: float, y: float) -> bool: ...


@runtime_checkable
class SessionWriter(Protocol):
    dir: Path | None  # None before start
    status: str | None  # None before close
    done: threading.Event

    @property
    def run_dir(self) -> Path: ...

    def start(self, meta: SessionMeta, run: RunMeta, positions: PositionMap | None = None) -> None:
        """positions is required exactly when run.calibration is set."""
        ...

    def start_run(
        self, session_dir: Path | str, run: RunMeta, positions: PositionMap | None = None
    ) -> None:
        """A replay: add `run` to the session in session_dir instead of starting a session."""
        ...

    def set_t0(self, t0: float, t0_wall: str) -> None:
        """The run's t0 (time.perf_counter()) and its wall clock, once capture has started."""
        ...

    def set_final(self, **blocks) -> None:
        """run.json blocks known only at the end: gaps, outages, clock. Call before close()."""
        ...

    def set_ready(self, step: str, t_wall: str, t_pc: float) -> None:
        """run.json ready[step] (model_loaded | first_frame | first_preview), when it happens."""
        ...

    def set_recording_sha256(self, sha256: str) -> None:
        """session.json recording.sha256, once the recorder has stopped. Call before close()."""
        ...

    def frame(self, rec: FrameRecord) -> None: ...

    def tracks(self, seq: int, obs: list[TrackObs], no_positions: str | None = None) -> None: ...

    def event(self, ev: SessionEvent) -> None: ...

    def close(self, status: str, counts: RunCounts) -> None:
        """status: ended | interrupted | error."""
        ...
