"""Shared test fakes: a scripted FrameSource (no camera, no files), a scripted detector and
tracker, and sample SessionMeta / RunMeta builders."""

import time
import uuid

import numpy as np

from services.edge.capture.types import Frame, SourceEnded, SourceInfo
from services.edge.perception.loop import NO_DETECTIONS
from services.edge.perception.types import Detections, TrackObs
from services.edge.session.types import RunMeta, SessionMeta


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
        return Frame(seq, time.perf_counter(), "2026-10-08T12:00:00Z", item, "fake")

    def close(self) -> None:
        self.closed = True


class EvenFrameDetector:
    """One person on even seq, none on odd: both kinds of frames must get a row."""

    threshold, det_size, device = 0.5, 384, "cuda"  # "cuda" must be written as cuda:0

    def __init__(self, fail_at: int | None = None):
        self.fail_at = fail_at

    def detect(self, frame):
        if frame.seq == self.fail_at:
            raise RuntimeError("inference exploded")
        if frame.seq % 2:
            return NO_DETECTIONS
        box = np.array([[10.0, 20.0, 110.0, 220.0]], np.float32)
        return Detections(box, np.array([0.9], np.float32), np.array([1], np.int64))


class OneTrackPerDetection:
    params = {"lost_track_buffer": 30}

    def update(self, dets, frame):
        return [
            TrackObs(i + 1, tuple(float(v) for v in box), float(c), None)
            for i, (box, c) in enumerate(zip(dets.xyxy, dets.confidence, strict=True))
        ]


def meta(ref: str = "fake", kind: str = "file", link: str | None = "file") -> SessionMeta:
    info = SourceInfo(kind, ref, 8, 8, None, link)
    return SessionMeta(str(uuid.uuid4()), str(uuid.uuid4()), "2026-10-13T12:00:00Z", info, False)


def sample_run_meta(
    ref: str = "fake",
    kind: str = "file",
    *,
    run_id: str | None = None,
    mode: str = "live",
    sha256: str | None = None,
) -> RunMeta:
    packages = {"opencv": "5.0.0", "numpy": "2.0.0", "torch": None, "supervision": None}
    return RunMeta(
        run_id or str(uuid.uuid4()),
        mode,
        {"kind": kind, "ref": ref, "sha256": sha256, "requested_width": None,
         "requested_height": None},
        None,
        None,
        {"lost_reads": 30, "lost_secs": 2.0, "frozen_diff": 0.5, "frozen_secs": 2.0,
         "dark_level": 20.0, "dark_secs": 1.0},
        {"python": "3.11.9", "platform": "test", "device": None, "gpu": None,
         "packages": packages},
        "2026-10-13T12:00:00Z",
    )  # fmt: skip
