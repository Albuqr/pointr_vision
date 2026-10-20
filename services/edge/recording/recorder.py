"""File Recorder (PHASE_04): raw frames to video.mp4 on its own thread (RF08, RF09, RNF04).

The capture thread calls write(); it only puts the frame on a bounded rec_queue and never
waits. A full queue drops the frame and counts it (frames_dropped). The video is a constant
frame rate file, so the time of a frame in it is its position / fps: t_video(seq) is the key
that joins hand labels and frames.csv to the recording.
"""

import hashlib
import queue
import threading
from collections.abc import Callable
from pathlib import Path

import cv2

from services.edge.capture.types import Frame, SourceInfo
from services.edge.recording.types import RecordingInfo

DEFAULT_FPS = 30.0  # when the source does not report one
QUEUE_SIZE = 256  # about 8 s of 30 fps video of slack for a slow disk


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
    thread is in `error` and every later frame counts as dropped."""

    def __init__(
        self,
        max_queue: int = QUEUE_SIZE,
        writer_factory: Callable[[Path, float, tuple[int, int]], object] = _CvWriter,
    ):
        self._q: queue.Queue = queue.Queue(max_queue)
        self._factory = writer_factory
        self.frames_dropped = 0
        self.error: BaseException | None = None  # why the writer thread stopped, if it failed
        self._accepted = 0  # frames put on the queue; also the next frame's index in the video
        self._index: dict[int, int] = {}  # seq -> index in the video, popped by t_video
        self._written = 0
        self._fps = DEFAULT_FPS
        self._path: Path | None = None
        self._thread: threading.Thread | None = None

    def start(self, path: Path, info: SourceInfo) -> None:
        self._path = Path(path)
        self._fps = info.reported_fps or DEFAULT_FPS
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    def write(self, frame: Frame) -> None:
        if self.error is None:
            try:
                self._q.put_nowait(frame)
            except queue.Full:
                pass
            else:
                self._index[frame.seq] = self._accepted
                self._accepted += 1
                return
        self.frames_dropped += 1

    def t_video(self, seq: int) -> float | None:
        """Time of frame `seq` in the video, s from its first frame; None if it was not
        recorded. Call once per seq: the entry is released."""
        index = self._index.pop(seq, None)
        return None if index is None else index / self._fps

    def stop(self) -> RecordingInfo:
        """Write what is queued, close the file and hash it. A recording of no frames leaves
        no file and sha256 ''."""
        self._q.put(None)  # blocks only while the writer drains a full queue
        self._thread.join()
        sha = ""
        if self._written and self._path.is_file():
            h = hashlib.sha256()
            with open(self._path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            sha = h.hexdigest()
        return RecordingInfo(self._path, self._written, self.frames_dropped, sha)

    def _run(self) -> None:
        writer = None
        try:
            while (frame := self._q.get()) is not None:
                if writer is None:
                    h, w = frame.image.shape[:2]
                    writer = self._factory(self._path, self._fps, (w, h))
                writer.write(frame.image)
                self._written += 1
        except BaseException as e:  # disk full, no codec: recorded, later frames are dropped
            self.error = e
            while not self._q.empty():  # unblock stop(); what is left was never written
                try:
                    if self._q.get_nowait() is not None:
                        self.frames_dropped += 1
                except queue.Empty:
                    break
        finally:
            if writer is not None:
                writer.release()
