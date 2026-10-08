"""Processing loop on its own thread: proc_queue -> detect -> track (ARCHITECTURE.md section 5).

Capture never waits for it: proc_queue holds one frame and capture drops the oldest, so when
processing is slower than capture, frames are skipped and app delay stays bounded.
App delay is t_proc_end - t_recv: frame received to processing done, not camera-to-screen.
"""

import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from services.edge.capture.types import Frame, HealthEvent, utc_now
from services.edge.perception.types import Detections, Detector, Tracker, TrackObs

NO_DETECTIONS = Detections(
    np.empty((0, 4), np.float32), np.empty(0, np.float32), np.empty(0, np.int64)
)


@dataclass(frozen=True)
class Processed:
    frame: Frame
    dets: Detections
    tracks: list[TrackObs]
    t_proc_start: float  # time.monotonic()
    t_proc_end: float

    @property
    def app_delay_ms(self) -> float:
        return (self.t_proc_end - self.frame.t_recv) * 1000


class Processor:
    """Takes frames in seq order and runs detector then tracker. detector=None runs no
    perception (capture-only mode): frames are still taken, timed and counted."""

    def __init__(
        self,
        proc_queue: "queue.Queue[Frame]",
        source_done: threading.Event,
        detector: Detector | None,
        tracker: Tracker | None,
        on_event: Callable[[HealthEvent], None],
    ):
        self.proc_queue = proc_queue
        self.source_done = source_done  # set when capture has stopped: drain, then finish
        self.detector = detector
        self.tracker = tracker
        self.on_event = on_event  # called on the processing thread
        # written by the processing thread only; other threads read them for display
        self.latest: Processed | None = None
        self.processed = 0
        self.unprocessed = 0  # left in proc_queue at stop: only after an error or a timeout
        self.delays_ms: list[float] = []  # one per processed frame, for p50/p95/max
        self.first_start: float | None = None
        self.last_end: float | None = None
        self.fps: float | None = None  # processing rate over the last 30 frames
        self.error: Exception | None = None
        self.done = threading.Event()
        self._stop = threading.Event()
        self._ends: deque[float] = deque(maxlen=30)
        self._thread = threading.Thread(target=self._run, name="perception", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> bool:
        """Finish and join; call it after capture has stopped. The thread then processes the
        frame still in proc_queue and exits on its own (shutdown drains the queues,
        ARCHITECTURE section 5), so every captured frame ends up processed or dropped. Past
        `timeout` it is told to stop; frames left in the queue then (also after a processing
        error) are counted in `unprocessed`. False if the thread is still running."""
        self._thread.join(timeout)
        if self._thread.is_alive():
            self._stop.set()
            self._thread.join(1.0)
        if self._thread.is_alive():
            return False
        while True:
            try:
                self.proc_queue.get_nowait()
            except queue.Empty:
                return True
            self.unprocessed += 1

    def _process(self, frame: Frame) -> Processed:
        t_start = time.monotonic()
        if self.detector is None:
            dets, tracks = NO_DETECTIONS, []
        else:
            dets = self.detector.detect(frame)
            tracks = self.tracker.update(dets, frame)
        return Processed(frame, dets, tracks, t_start, time.monotonic())

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    frame = self.proc_queue.get(timeout=0.1)
                except queue.Empty:
                    if self.source_done.is_set() and self.proc_queue.empty():
                        break
                    continue
                try:
                    result = self._process(frame)
                except Exception:
                    self.unprocessed += 1  # the frame in hand is counted, not lost
                    raise
                self.processed += 1
                self.delays_ms.append(result.app_delay_ms)
                if self.first_start is None:
                    self.first_start = result.t_proc_start
                self.last_end = result.t_proc_end
                self._ends.append(result.t_proc_end)
                span = self._ends[-1] - self._ends[0]
                self.fps = (len(self._ends) - 1) / span if span > 0 else None
                self.latest = result
        except Exception as e:  # a failure ends processing as an event, never silently
            self.error = e
            self.on_event(
                HealthEvent("error", utc_now(), time.monotonic(), f"processing stopped: {e!r}")
            )
        finally:
            self.done.set()


def rates(
    captured: int, dropped: int, processed: int, first_start: float | None, last_end: float | None
) -> tuple[float | None, float | None]:
    """(processing FPS, drop rate). FPS is processed frames over the time from the first
    processing start to the last end; drop rate is dropped / captured. None when undefined."""
    span = (last_end - first_start) if first_start is not None and last_end is not None else 0
    fps = processed / span if span > 0 else None
    return fps, (dropped / captured if captured else None)


def delay_stats(delays_ms: list[float]) -> dict[str, float] | None:
    """p50, p95 and max of app delays in ms; None when nothing was processed."""
    if not delays_ms:
        return None
    p50, p95 = np.percentile(delays_ms, [50, 95])
    return {"p50": float(p50), "p95": float(p95), "max": float(max(delays_ms))}
