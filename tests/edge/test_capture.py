"""A2: capture never blocks and drops oldest; A4 end to end through the capture thread."""

import itertools
import queue
import time

from fakes import FakeSource, image

from services.edge.capture.capture import Capture
from services.edge.capture.health import HealthConfig, HealthMonitor


def run_capture(source, **kwargs) -> tuple[Capture, list]:
    events = []
    capture = Capture(source, HealthMonitor(HealthConfig()), events.append, **kwargs)
    capture.start()
    return capture, events


def test_never_blocks_and_keeps_newest():
    """No consumer at all: capture still reads everything, keeping only the newest frame."""
    n = 200
    capture, events = run_capture(FakeSource(image(i) for i in range(n)))
    assert capture.done.wait(5), "capture blocked on a full queue"
    assert capture.proc_queue.maxsize == 1
    assert capture.captured == n
    assert capture.dropped == n - 1
    assert capture.proc_queue.qsize() == 1
    assert capture.proc_queue.get_nowait().seq == n - 1  # oldest dropped, newest kept
    assert events == []
    assert capture.stop()


def test_slow_consumer_accounting():
    """Consumer slower than producer: queue never above 1, every frame consumed or counted."""
    n = 150
    capture, _ = run_capture(FakeSource((image(i) for i in range(n)), delay=0.001))
    consumed, sizes = [], []
    deadline = time.perf_counter() + 30
    while not (capture.done.is_set() and capture.proc_queue.empty()):
        assert time.perf_counter() < deadline, "capture never finished"
        sizes.append(capture.proc_queue.qsize())
        try:
            consumed.append(capture.proc_queue.get(timeout=0.1).seq)
        except queue.Empty:
            continue
        time.sleep(0.01)
    assert capture.stop()
    assert max(sizes) <= 1
    assert capture.captured == n
    assert capture.dropped > 0
    assert len(consumed) + capture.dropped == n
    assert all(a < b for a, b in zip(consumed, consumed[1:], strict=False))
    assert consumed[-1] == n - 1


def test_fake_source_lost_and_recovered():
    lost_reads = HealthConfig().lost_reads
    script = [image(i) for i in range(5)] + [None] * lost_reads + [image(i) for i in range(3)]
    capture, events = run_capture(FakeSource(script), fail_backoff=0)
    assert capture.done.wait(5)
    assert capture.stop()
    assert [e.kind for e in events] == ["source_lost", "source_recovered"]
    assert capture.captured == 8
    assert capture.failed_reads == lost_reads
    assert capture.error is None
    assert capture.t0 is not None and events[0].t_mono >= capture.t0


def test_source_exception_becomes_error_event():
    capture, events = run_capture(FakeSource([image(0), RuntimeError("usb gone")]))
    assert capture.done.wait(5)
    assert capture.stop()
    assert [e.kind for e in events] == ["error"]
    assert "usb gone" in events[0].detail
    assert isinstance(capture.error, RuntimeError)


def test_stop_ends_an_endless_source():
    capture, _ = run_capture(FakeSource(image(i) for i in itertools.count()))  # never ends
    deadline = time.perf_counter() + 5
    while capture.captured == 0:
        assert time.perf_counter() < deadline, "capture thread never read"
        time.sleep(0.01)
    assert capture.stop(timeout=2)
    assert capture.done.is_set()
    assert capture.captured > 0


class RacingQueue(queue.Queue):
    """Full on the first put; the consumer takes the frame before capture's get_nowait."""

    def __init__(self):
        super().__init__(maxsize=1)
        self.first = True

    def put_nowait(self, item):
        if self.first:
            self.first = False
            raise queue.Full
        super().put_nowait(item)

    def get_nowait(self):
        raise queue.Empty


def test_put_race_is_not_counted_as_a_drop():
    capture = Capture(FakeSource([]), HealthMonitor(), lambda ev: None)
    capture.proc_queue = RacingQueue()
    frame = FakeSource([image(0)]).read()
    capture._put(frame)
    assert capture.dropped == 0
    assert capture.proc_queue.get(timeout=1) is frame
