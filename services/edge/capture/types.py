"""Capture layer types and Protocols (ARCHITECTURE.md section 4). No source implementations."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True, eq=False)  # ndarray field: no value equality or hash
class Frame:
    seq: int  # monotonically increasing per source, gaps = capture failures
    t_recv: float  # time.perf_counter() when the frame was read
    t_wall: str  # UTC ISO-8601 wall clock at read time
    image: np.ndarray  # BGR, HxWx3
    source_id: str
    t_video: float | None = None  # s in the video file, from its first frame; files only


@dataclass(frozen=True)
class SourceInfo:
    kind: str  # camera | stream | file, as session.json source.kind
    ref: str
    width: int | None  # None when unknown (OpenCV reports 0), never 0
    height: int | None
    reported_fps: float | None  # None when the source does not report one
    link: str | None = None  # usb | wifi | builtin | file, declared by --link (D-012)


@dataclass(frozen=True)
class HealthEvent:
    kind: str  # an event kind from DATA_CONTRACTS.md section 2, e.g. source_lost
    t_wall: str  # UTC ISO-8601
    t_mono: float | None  # time.perf_counter(); None if the event precedes the run's t0 (D-014)
    detail: str | None = None


class SourceEnded(Exception):
    """Raised by FrameSource.read() when a finite source (a file) has no more frames (D-013)."""


def utc_now() -> str:
    """UTC ISO-8601 with milliseconds and a Z suffix, as DATA_CONTRACTS wall times."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@runtime_checkable
class FrameSource(Protocol):
    def open(self) -> SourceInfo:
        """Open the source. Raises on failure."""
        ...

    def read(self) -> Frame | None:
        """Next frame, or None when no frame was obtained this attempt.

        Raises SourceEnded when a finite source has ended, so the end of a file is not
        mistaken for a lost source (D-013)."""
        ...

    def close(self) -> None: ...


@runtime_checkable
class SourceHealth(Protocol):
    def assess(self, frame: Frame | None) -> list[HealthEvent]:
        """Events (lost, frozen, dark, recovered) caused by this read attempt."""
        ...
