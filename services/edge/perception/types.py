"""Perception layer types and Protocols (ARCHITECTURE.md section 4). No implementations.

rfdetr and supervision objects never leave the perception layer; these plain types do.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from services.edge.capture.types import Frame


@dataclass(frozen=True, eq=False)  # ndarray fields: no value equality or hash
class Detections:
    """Person detections above threshold for one frame. N may be 0."""

    xyxy: np.ndarray  # float, shape (N, 4), pixels
    confidence: np.ndarray  # float, shape (N,)
    class_id: np.ndarray  # int, shape (N,); person only


@dataclass(frozen=True)
class TrackObs:
    track_id: int  # temporary tracker ID, valid only within one run
    xyxy: tuple[float, float, float, float]  # pixels
    confidence: float | None  # None when the tracker does not expose it
    state: str | None  # "observed" | "predicted", None when the tracker does not expose it


@runtime_checkable
class Detector(Protocol):
    def detect(self, frame: Frame) -> Detections: ...


@runtime_checkable
class Tracker(Protocol):
    def update(self, dets: Detections, frame: Frame) -> list[TrackObs]: ...
