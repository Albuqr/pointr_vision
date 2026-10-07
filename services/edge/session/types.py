"""Session layer types and Protocol (ARCHITECTURE.md section 4). No implementations.

Fields follow DATA_CONTRACTS.md sections 2 and 4. SessionMeta is provisional: it does not
yet carry run metadata or end-of-run counts for run.json; phase 03 completes it (D-007).
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
class FrameRecord:
    """One frames.csv row: one per processed frame, including frames with 0 detections."""

    seq: int
    t_recv: float  # s since t0
    t_proc_start: float  # s since t0
    t_proc_end: float  # s since t0
    n_detections: int
    n_tracks: int
    dropped_total: int  # cumulative frames dropped before processing

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
    def start(self, meta: SessionMeta) -> None: ...

    def frame(self, rec: FrameRecord) -> None: ...

    def tracks(self, seq: int, obs: list[TrackObs]) -> None: ...

    def event(self, ev: SessionEvent) -> None: ...

    def close(self, status: str) -> None:
        """status: ended | interrupted | error."""
        ...
