"""Capture thread feeding proc_queue (ARCHITECTURE.md section 5, D-013).

Capture never blocks on the consumer: proc_queue holds one frame, and when it is full the
oldest frame is discarded and counted in `dropped`.
"""

import queue
import threading
import time
from collections import deque
from collections.abc import Callable

from services.edge.capture.types import (
    Frame,
    FrameSource,
    HealthEvent,
    SourceEnded,
    SourceHealth,
    utc_now,
)


class Capture:
    def __init__(
        self,
        source: FrameSource,
        health: SourceHealth,
        on_event: Callable[[HealthEvent], None],
        fail_backoff: float = 0.01,  # pause after a failed read, so a dead device is not spun on
    ):
        self.source = source
        self.health = health
        self.on_event = on_event  # called on the capture thread
        self.fail_backoff = fail_backoff
        self.proc_queue: queue.Queue[Frame] = queue.Queue(maxsize=1)
        # written by the capture thread only; other threads read them for display
        self.captured = 0
        self.dropped = 0
        self.failed_reads = 0
        self.fps: float | None = None  # capture rate over the last 30 frames; None while failing
        self.t0: float | None = None  # run's t0 (D-011), set when the thread starts
        self.t0_wall: str | None = None
        self.error: Exception | None = None
        self.done = threading.Event()  # set when the thread has stopped for any reason
        self._stop = threading.Event()
        self._times: deque[float] = deque(maxlen=30)
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    # longer than the slowest blocking read: a stream reopen (5 s) after a read timeout (2 s)
    def stop(self, timeout: float = 8.0) -> bool:
        """Ask the thread to stop and join it. False if it is still running (e.g. stuck in
        a blocking read); the caller must then not close the source under it."""
        self._stop.set()
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _put(self, frame: Frame) -> None:
        # single producer: only this thread puts, so after a get the put cannot fail
        try:
            self.proc_queue.put_nowait(frame)
        except queue.Full:
            try:
                self.proc_queue.get_nowait()
                self.dropped += 1
            except queue.Empty:  # the consumer took it meanwhile
                pass
            self.proc_queue.put_nowait(frame)

    def _run(self) -> None:
        self.t0 = time.monotonic()
        self.t0_wall = utc_now()
        try:
            while not self._stop.is_set():
                try:
                    frame = self.source.read()
                except SourceEnded:
                    break
                for ev in self.health.assess(frame):
                    self.on_event(ev)
                if frame is None:
                    self.failed_reads += 1
                    self.fps = None
                    self._times.clear()
                    self._stop.wait(self.fail_backoff)
                    continue
                self.captured += 1
                self._times.append(frame.t_recv)
                span = self._times[-1] - self._times[0]
                self.fps = (len(self._times) - 1) / span if span > 0 else None
                self._put(frame)
        except Exception as e:  # any failure ends capture as an event, never silently
            self.error = e
            self.on_event(
                HealthEvent("error", utc_now(), time.monotonic(), f"capture stopped: {e!r}")
            )
        finally:
            self.done.set()
