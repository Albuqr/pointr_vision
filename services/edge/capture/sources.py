"""FrameSource implementations and the open_source factory (PHASE_01, D-013).

read() returns None when no frame was obtained this attempt. A finite source that has
ended raises SourceEnded instead, so the end of a file is not reported as source_lost.
"""

import time
from datetime import UTC, datetime
from pathlib import Path

import cv2

from services.edge.capture.types import Frame, FrameSource, SourceInfo

FILE_SUFFIXES = (".mp4", ".mov")
STREAM_SCHEMES = ("http://", "https://", "rtsp://")


class SourceOpenError(Exception):
    """The source could not be opened. The message is the reason shown to the user."""


class SourceEnded(Exception):
    """A finite source (file) has no more frames. Not a failure."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _positive(value: float) -> float | None:
    """OpenCV reports 0 for unknown properties; the contract wants null, never 0."""
    return value if value > 0 else None


class _CvSource:
    """Shared cv2.VideoCapture handling. Subclasses say how to open the capture."""

    kind = ""

    def __init__(self, ref: str):
        self.ref = ref
        self._cap: cv2.VideoCapture | None = None
        self._seq = 0  # counts read attempts, so gaps mark failed reads (D-013)

    def _new_capture(self) -> cv2.VideoCapture:
        raise NotImplementedError

    def open(self) -> SourceInfo:
        cap = self._new_capture()
        if not cap.isOpened():
            cap.release()
            raise SourceOpenError(f"{self.kind} {self.ref!r} did not open")
        self._cap = cap
        width = _positive(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = _positive(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return SourceInfo(
            kind=self.kind,
            ref=self.ref,
            width=int(width) if width else None,
            height=int(height) if height else None,
            reported_fps=_positive(cap.get(cv2.CAP_PROP_FPS)),
        )

    def _grab(self) -> Frame | None:
        ok, image = self._cap.read()
        t_recv = time.monotonic()
        seq = self._seq
        self._seq += 1
        if not ok or image is None:
            return None
        return Frame(seq, t_recv, utc_now(), image, f"{self.kind}:{self.ref}")

    def read(self) -> Frame | None:
        return self._grab()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class _LiveSource(_CvSource):
    """Camera or stream: after failing for reopen_after seconds, reopen the device, at
    most once per reopen_after, so a device that comes back recovers (D-013)."""

    reopen_after = 1.0

    def __init__(self, ref: str):
        super().__init__(ref)
        self._next_reopen: float | None = None

    def read(self) -> Frame | None:
        frame = self._grab()
        if frame is not None:
            self._next_reopen = None
            return frame
        now = time.monotonic()
        if self._next_reopen is None:
            self._next_reopen = now + self.reopen_after
        elif now >= self._next_reopen:
            self._next_reopen = now + self.reopen_after
            self._cap.release()
            self._cap = self._new_capture()
        return None


class CameraSource(_LiveSource):
    """A webcam index: the laptop webcam, or DroidCam over USB or Wi-Fi (D-010)."""

    kind = "camera"

    def __init__(self, index: int, api: int = cv2.CAP_ANY):
        super().__init__(str(index))
        self.index = index
        self.api = api

    def _new_capture(self) -> cv2.VideoCapture:
        return cv2.VideoCapture(self.index, self.api)


class StreamSource(_LiveSource):
    """A stream URL, e.g. IP Webcam's http://<phone-ip>:8080/video (D-010)."""

    kind = "stream"
    open_timeout_ms = 5000
    read_timeout_ms = 2000

    def _new_capture(self) -> cv2.VideoCapture:
        params = [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            self.open_timeout_ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            self.read_timeout_ms,
        ]
        return cv2.VideoCapture(self.ref, cv2.CAP_FFMPEG, params)


class FileSource(_CvSource):
    """An MP4 or MOV file. realtime=True paces reads to the file's fps, like a live source."""

    kind = "file"

    def __init__(self, path: str | Path, realtime: bool = True):
        super().__init__(str(path))
        self.realtime = realtime
        self._period = 0.0
        self._next_due: float | None = None

    def _new_capture(self) -> cv2.VideoCapture:
        return cv2.VideoCapture(self.ref)

    def open(self) -> SourceInfo:
        info = super().open()
        if self.realtime and info.reported_fps:
            self._period = 1.0 / info.reported_fps
        return info

    def read(self) -> Frame | None:
        if self._period:
            now = time.monotonic()
            self._next_due = now if self._next_due is None else self._next_due
            time.sleep(max(0.0, self._next_due - now))
            self._next_due += self._period
        frame = self._grab()
        if frame is None:  # a file has no transient failures: a failed read is the end
            raise SourceEnded(self.ref)
        return frame


def open_source(ref: str, camera_api: int = cv2.CAP_ANY) -> FrameSource:
    """Pick the source for a ref; the caller calls open(). Raises SourceOpenError."""
    ref = ref.strip()
    if ref.isdigit():
        return CameraSource(int(ref), camera_api)
    if ref.lower().startswith(STREAM_SCHEMES):
        return StreamSource(ref)
    path = Path(ref)
    if path.suffix.lower() in FILE_SUFFIXES:
        if not path.is_file():
            raise SourceOpenError(f"file not found: {ref}")
        return FileSource(path)
    if path.is_file():
        raise SourceOpenError(f"unsupported file type {path.suffix!r} (use .mp4 or .mov): {ref}")
    raise SourceOpenError(
        f"not a camera index, stream URL (http, https, rtsp) or .mp4/.mov file: {ref!r}"
    )
