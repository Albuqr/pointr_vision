"""FrameSource implementations and the open_source factory (PHASE_01, D-013).

read() returns None when no frame was obtained this attempt. A finite source that has
ended raises SourceEnded instead, so the end of a file is not reported as source_lost.
"""

import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import cv2

from services.edge.capture.types import Frame, FrameSource, SourceEnded, SourceInfo, utc_now

FILE_SUFFIXES = (".mp4", ".mov")
STREAM_SCHEMES = ("http://", "https://", "rtsp://")
# What the recorder requests from a camera. Anything that must see the recorder's frames (the
# Studio's calibration frame) opens the camera with this size too.
DEFAULT_CAPTURE_SIZE = (1280, 720)
_FFMPEG_OPTIONS_LOCK = threading.Lock()


def _disable_http_redirects() -> None:
    """Keep FFmpeg from following an unvalidated camera stream redirect."""
    with _FFMPEG_OPTIONS_LOCK:
        current = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS", "")
        options = [item for item in current.split("|") if item]
        options = [item for item in options if item.partition(";")[0] != "max_redirects"]
        options.append("max_redirects;0")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "|".join(options)


class SourceOpenError(Exception):
    """The source could not be opened. The message is the reason shown to the user."""


def _positive(value: float) -> float | None:
    """OpenCV reports 0 for unknown properties; the contract wants null, never 0."""
    return value if value > 0 else None


class _CvSource:
    """Shared cv2.VideoCapture handling. Subclasses say how to open the capture."""

    kind = ""

    def __init__(self, ref: str, fps_cap: float | None = None):
        self.ref = ref
        self.fps_cap = fps_cap
        self._next_read: float | None = None
        self._cap: cv2.VideoCapture | None = None
        self._seq = 0  # counts read attempts, so gaps mark failed reads (D-013)

    def _new_capture(self) -> cv2.VideoCapture:
        raise NotImplementedError

    def open(self) -> SourceInfo:
        self.close()  # reopening must not leak the previous capture
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
        if self._cap is None:
            raise RuntimeError(f"{self.kind} {self.ref!r} read before open()")
        if self.fps_cap is not None:
            now = time.perf_counter()
            if self._next_read is not None and self._next_read > now:
                time.sleep(self._next_read - now)
            self._next_read = time.perf_counter() + 1 / self.fps_cap
        ok, image = self._cap.read()
        t_recv = time.perf_counter()
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

    def __init__(self, ref: str, fps_cap: float | None = None):
        super().__init__(ref, fps_cap)
        self._next_reopen: float | None = None

    def read(self) -> Frame | None:
        frame = self._grab()
        if frame is not None:
            self._next_reopen = None
            return frame
        now = time.perf_counter()
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

    def __init__(
        self, index: int, size: tuple[int, int] | None = None, fps_cap: float | None = None
    ):
        super().__init__(str(index), fps_cap)
        self.index = index
        self.size = size  # requested (width, height); open() reports what the camera gives

    def _new_capture(self) -> cv2.VideoCapture:
        # CAP_ANY picks MSMF on Windows (phase 01 A7); DSHOW cannot open by index on opencv 5.0
        cap = cv2.VideoCapture(self.index, cv2.CAP_ANY)
        if self.size and cap.isOpened():  # on every reopen too, so a recovery keeps the size
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        if self.fps_cap is not None and cap.isOpened():
            cap.set(cv2.CAP_PROP_FPS, self.fps_cap)
        return cap


class StreamSource(_LiveSource):
    """A stream URL, e.g. IP Webcam's http://<phone-ip>:8080/video (D-010)."""

    kind = "stream"
    open_timeout_ms = 5000
    read_timeout_ms = 2000

    def _new_capture(self) -> cv2.VideoCapture:
        _disable_http_redirects()
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

    def __init__(self, path: str | Path, realtime: bool = True, fps_cap: float | None = None):
        super().__init__(str(path), fps_cap)
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
            now = time.perf_counter()
            self._next_due = now if self._next_due is None else self._next_due
            time.sleep(max(0.0, self._next_due - now))
            self._next_due += self._period
        frame = self._grab()
        if frame is None:  # a file has no transient failures: a failed read is the end
            raise SourceEnded(self.ref)
        # the container timestamp of the frame just read (OpenCV: 0.0 for the first)
        return replace(frame, t_video=self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000)


def open_source(ref: str, size: tuple[int, int] | None = None) -> FrameSource:
    """Pick the source for a ref; the caller calls open(). Raises SourceOpenError.

    size (width, height) is requested from cameras only; streams and files deliver their own."""
    ref = ref.strip()
    if ref.isdigit():
        return CameraSource(int(ref), size)
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
