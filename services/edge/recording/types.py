"""Recording layer types and Protocol (ARCHITECTURE.md section 4). No implementations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from services.edge.capture.types import Frame, SourceInfo


@dataclass(frozen=True)
class RecordingInfo:
    path: Path
    frames_written: int
    frames_dropped: int  # rec_queue overflows; run.json counts.rec_dropped
    sha256: str


@runtime_checkable
class Recorder(Protocol):
    def start(self, path: Path, info: SourceInfo) -> None: ...

    def write(self, frame: Frame) -> None: ...

    def stop(self) -> RecordingInfo: ...
