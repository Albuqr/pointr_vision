"""File Recorder (PHASE_04): raw frames to the session video on its own thread (RF08, RF09, RNF04).

The capture thread calls write(); it only puts the frame on a bounded rec_queue and never
waits. A full queue drops the frame and counts it (frames_dropped). The video is a constant
frame rate file, so the time of a frame in it is its position / fps: t_video(seq) is the key
that joins hand labels and frames.csv to the recording. Only frames that really went into the
file have a t_video: a frame of another size, or one left in the queue by a failed writer, has none.
"""

import hashlib
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2

from services.edge.capture.types import Frame, SourceInfo
from services.edge.recording.types import RecordingInfo

DEFAULT_FPS = 30.0  # when the source does not report one
QUEUE_SIZE = 64  # about 2 s of 30 fps video of slack for a slow disk; a frame is up to 6 MB
INDEX_MAX = 4096  # seq -> position entries kept for t_video(); frames capture drops never leave
STOP_TIMEOUT = 10.0  # seconds stop() waits for the writer to drain


class _CvWriter:
    def __init__(self, path: Path, fps: float, size: tuple[int, int]):
        self._w = cv2.VideoWriter()
        if not self._w.open(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, size):
            raise OSError(f"OpenCV could not open a video writer for {path}")

    def write(self, image) -> None:
        self._w.write(image)

    def release(self) -> None:
        self._w.release()


class FileRecorder:
    """Implements Recorder. Producer methods never raise or block; a failure of the writer
    thread is in `error` and every later frame counts as dropped. One lock guards the state the
    capture, processing and writer threads share (the queue put, the index, the counters)."""

    def __init__(
        self,
        max_queue: int = QUEUE_SIZE,
        writer_factory: Callable[[Path, float, tuple[int, int]], object] = _CvWriter,
        stop_timeout: float = STOP_TIMEOUT,
    ):
        self._q: queue.Queue = queue.Queue(max_queue)
        self._factory = writer_factory
        self._stop_timeout = stop_timeout
        self.error: BaseException | None = None  # why recording failed, if it did
        self._lock = threading.Lock()
        self._dropped = 0
        self._accepted = 0  # frames put on the queue; also the next frame's index in the video
        self._index: dict[int, int] = {}  # seq -> index in the video, popped by t_video
        self._size: tuple[int, int] | None = None  # (width, height) of the first frame
        self.size_dropped = 0  # frames of another size than the first (not recorded)
        self.first_size_drop: tuple[int, tuple[int, int]] | None = None  # (seq, (width, height))
        self._written = 0
        self._fps = DEFAULT_FPS
        self._path: Path | None = None
        self._thread: threading.Thread | None = None

    @property
    def frames_dropped(self) -> int:
        return self._dropped

    @property
    def frame_size(self) -> tuple[int, int] | None:
        return self._size

    def start(self, path: Path, info: SourceInfo) -> None:
        self._path = Path(path)
        self._fps = info.reported_fps or DEFAULT_FPS
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    def write(self, frame: Frame) -> None:
        h, w = frame.image.shape[:2]
        with self._lock:
            if self._size is None:
                self._size = (w, h)
            if self.error is None:
                if self._size != (w, h):  # OpenCV drops such a frame silently: count it here
                    self.size_dropped += 1
                    self.first_size_drop = self.first_size_drop or (frame.seq, (w, h))
                else:
                    try:
                        self._q.put_nowait(frame)
                    except queue.Full:
                        pass
                    else:
                        self._index[frame.seq] = self._accepted
                        self._accepted += 1
                        if len(self._index) > INDEX_MAX:
                            del self._index[next(iter(self._index))]
                        return
            self._dropped += 1

    def t_video(self, seq: int) -> float | None:
        """Time of frame `seq` in the video, s from its first frame; None if it was not
        recorded. Call once per seq: the entry is released."""
        with self._lock:
            index = self._index.pop(seq, None)
        return None if index is None else index / self._fps

    def stop(self) -> RecordingInfo:
        """Write what is queued, close the file and hash it, waiting at most stop_timeout for the
        writer. A recording of no frames leaves no file and sha256 ''. If the writer does not
        finish in time, `error` says so and sha256 is '': the file is not known to be complete."""
        deadline = time.monotonic() + self._stop_timeout  # one budget for the put and the join
        try:
            self._q.put(None, timeout=self._stop_timeout)
        except queue.Full:
            self._fail(TimeoutError("recorder queue stayed full at stop"))
        self._thread.join(max(0.0, deadline - time.monotonic()))
        sha = ""
        extra = 0
        if self._thread.is_alive():
            self._fail(TimeoutError(f"recorder did not stop in {self._stop_timeout} s"))
            extra = self._q.qsize()  # still queued: they will not be in a file known to be whole
        elif self._written and self._path.is_file():
            try:
                sha = self._hash()
            except OSError as e:  # a locked file (OneDrive, an antivirus): the video itself is fine
                self._fail(e)
        return RecordingInfo(self._path, self._written, self._dropped + extra, sha)

    def _fail(self, error: BaseException) -> None:
        with self._lock:
            self.error = self.error or error

    def _hash(self) -> str:
        h = hashlib.sha256()
        with open(self._path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _run(self) -> None:
        writer = None
        frame = None
        try:
            while (frame := self._q.get()) is not None:
                if writer is None:
                    h, w = frame.image.shape[:2]
                    writer = self._factory(self._path, self._fps, (w, h))
                writer.write(frame.image)
                self._written += 1
                frame = None
        except BaseException as e:  # disk full, no codec: recorded, later frames are dropped
            with self._lock:  # write() puts nothing once `error` is set, so the drain is final
                self.error = self.error or e
                lost = 0 if frame is None else 1  # the frame in hand was not written
                while True:  # what is queued is never written; also unblocks stop()
                    try:
                        if self._q.get_nowait() is not None:
                            lost += 1
                    except queue.Empty:
                        break
                self._dropped += lost
                # only frames that are in the file have a time in it
                self._index = {s: i for s, i in self._index.items() if i < self._written}
        finally:
            if writer is not None:
                writer.release()
