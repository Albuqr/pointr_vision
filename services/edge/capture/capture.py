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
        on_frame: Callable[[Frame], None] | None = None,
        lossless: bool = False,
    ):
        self.source = source
        self.health = health
        self.on_event = on_event  # called on the capture thread
        self.on_frame = on_frame  # every captured frame, before proc_queue; must not block
        self.lossless = lossless  # a replay waits for the consumer instead of dropping (A3)
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
        self._latest_lock = threading.Lock()
        self._latest_frame: Frame | None = None
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def raw_snapshot(self):
        """Copy the latest unannotated capture frame only when a client requests one."""
        with self._latest_lock:
            frame = self._latest_frame
        return None if frame is None else frame.image.copy()

    # longer than the slowest blocking read: a stream reopen (5 s) after a read timeout (2 s)
    def stop(self, timeout: float = 8.0) -> bool:
        """Ask the thread to stop and join it. False if it is still running (e.g. stuck in
        a blocking read); the caller must then not close the source under it."""
        self._stop.set()
        if self._thread.ident is None:  # never started: a stop request came before start()
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _put(self, frame: Frame) -> None:
        if self.lossless:
            while not self._stop.is_set():
                try:
                    self.proc_queue.put(frame, timeout=0.1)
                    return
                except queue.Full:
                    continue
            self.dropped += 1  # stopped while waiting: this frame was captured and never processed
            return
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
        self.t0 = time.perf_counter()
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
                with self._latest_lock:
                    self._latest_frame = frame
                self.captured += 1
                self._times.append(frame.t_recv)
                span = self._times[-1] - self._times[0]
                self.fps = (len(self._times) - 1) / span if span > 0 else None
                if self.on_frame is not None:  # the recorder sees every frame, not only the kept
                    self.on_frame(frame)
                self._put(frame)
        except Exception as e:  # any failure ends capture as an event, never silently
            self.error = e
            self.on_event(
                HealthEvent("error", utc_now(), time.perf_counter(), f"capture stopped: {e!r}")
            )
        finally:
            self.done.set()
