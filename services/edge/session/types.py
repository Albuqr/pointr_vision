"""Session layer types and Protocol (ARCHITECTURE.md section 4).

Fields follow DATA_CONTRACTS.md sections 2-4. RunMeta and RunCounts carry what run.json
needs (D-008, completed by D-020).
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from services.edge.capture.types import SourceInfo
from services.edge.perception.types import TrackObs


@dataclass(frozen=True)
class SessionMeta:
    session_id: str  # UUIDv4
    device_id: str  # UUIDv4
    started_at: str  # UTC ISO-8601
    source: SourceInfo
    recording_enabled: bool


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


@dataclass(frozen=True)
class RunCounts:
    captured: int
    processed: int
    dropped: int
    unprocessed: int
    rec_dropped: int | None = None  # None when recording is disabled


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
class SessionWriter(Protocol):
    def start(self, meta: SessionMeta, run: RunMeta) -> None: ...

    def set_t0(self, t0: float, t0_wall: str) -> None:
        """The run's t0 (time.monotonic()) and its wall clock, once capture has started."""
        ...

    def frame(self, rec: FrameRecord) -> None: ...

    def tracks(self, seq: int, obs: list[TrackObs]) -> None: ...

    def event(self, ev: SessionEvent) -> None: ...

    def close(self, status: str, counts: RunCounts) -> None:
        """status: ended | interrupted | error."""
        ...
