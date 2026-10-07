"""Capture layer types and Protocols (ARCHITECTURE.md section 4). No implementations."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True, eq=False)  # ndarray field: no value equality or hash
class Frame:
    seq: int  # monotonically increasing per source, gaps = capture failures
    t_recv: float  # time.monotonic() when the frame was read
    t_wall: str  # UTC ISO-8601 wall clock at read time
    image: np.ndarray  # BGR, HxWx3
    source_id: str


@dataclass(frozen=True)
class SourceInfo:
    kind: str  # camera | stream | file, as session.json source.kind
    ref: str
    width: int | None  # None when unknown (OpenCV reports 0), never 0
    height: int | None
    reported_fps: float | None  # None when the source does not report one


@dataclass(frozen=True)
class HealthEvent:
    kind: str  # an event kind from DATA_CONTRACTS.md section 2, e.g. source_lost
    t_wall: str  # UTC ISO-8601
    t_mono: float  # time.monotonic(); the session layer converts it to s since t0
    detail: str | None = None


@runtime_checkable
class FrameSource(Protocol):
    def open(self) -> SourceInfo:
        """Open the source. Raises on failure."""
        ...

    def read(self) -> Frame | None:
        """Next frame, or None when no frame was obtained this attempt."""
        ...

    def close(self) -> None: ...


@runtime_checkable
class SourceHealth(Protocol):
    def assess(self, frame: Frame | None) -> list[HealthEvent]:
        """Events (lost, frozen, dark, recovered) caused by this read attempt."""
        ...
