"""Scripted fake FrameSource for capture tests. No camera, no files."""

import time

import numpy as np

from services.edge.capture.types import Frame, SourceEnded, SourceInfo


def image(i: int) -> np.ndarray:
    """Mid-grey, alternating so consecutive frames differ (not dark, not frozen)."""
    return np.full((8, 8, 3), 100 + 20 * (i % 2), np.uint8)


class FakeSource:
    """Each script item is an image (a frame) or None (a failed read); then SourceEnded.
    An exception item is raised from read(). `delay` seconds pass before each read returns."""

    def __init__(self, script, delay: float = 0.0):
        self._script = iter(script)
        self._seq = 0
        self.delay = delay
        self.closed = False

    def open(self) -> SourceInfo:
        return SourceInfo("file", "fake", 8, 8, None)

    def read(self) -> Frame | None:
        if self.delay:
            time.sleep(self.delay)
        item = next(self._script, SourceEnded)
        if item is SourceEnded:
            raise SourceEnded("fake")
        if isinstance(item, Exception):
            raise item
        seq, self._seq = self._seq, self._seq + 1
        if item is None:
            return None
        return Frame(seq, time.monotonic(), "2026-10-08T12:00:00Z", item, "fake")

    def close(self) -> None:
        self.closed = True
