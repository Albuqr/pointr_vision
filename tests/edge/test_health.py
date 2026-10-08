"""A3: dark/frozen/normal fixtures give the right events; A4: lost then recovered."""

import dataclasses

import pytest
from fakes import image

from fixtures.make_clips import FPS
from services.edge.capture.health import DARK, FROZEN, LOST, OK, HealthConfig, HealthMonitor
from services.edge.capture.sources import FileSource
from services.edge.capture.types import Frame, SourceEnded

# The fixture clips last 2 s (30 frames at 15 fps), so the episodes must be shorter.
SHORT = HealthConfig(frozen_secs=1.0, dark_secs=1.0)


def fixture_frames(path) -> list[Frame]:
    """Real fixture images, re-stamped t_recv = seq / fps so timing is deterministic."""
    source = FileSource(path, realtime=False)
    source.open()
    frames = []
    try:
        while True:
            try:
                frame = source.read()
            except SourceEnded:
                return frames
            frames.append(dataclasses.replace(frame, t_recv=frame.seq / FPS))
    finally:
        source.close()


def assess_all(monitor, frames) -> list:
    return [ev for f in frames for ev in monitor.assess(f)]


@pytest.mark.parametrize(
    "name,kinds,state",
    [("black", ["dark_frames"], DARK), ("frozen", ["frozen_frames"], FROZEN), ("moving", [], OK)],
)
def test_fixture_events(clips, name, kinds, state):
    monitor = HealthMonitor(SHORT)
    events = assess_all(monitor, fixture_frames(clips[name]))
    assert [e.kind for e in events] == kinds
    assert monitor.state == state
    for e in events:  # fires the first frame at which the episode has lasted 1.0 s
        assert e.t_mono == pytest.approx(1.0)


def test_frozen_shorter_than_threshold_is_not_reported(clips):
    """Default frozen_secs is 2.0 s; the frozen clip lasts 29/15 s."""
    monitor = HealthMonitor()
    assert assess_all(monitor, fixture_frames(clips["frozen"])) == []
    assert monitor.state == OK


def frame(seq: int, t: float, img=None) -> Frame:
    return Frame(seq, t, "2026-10-08T12:00:00Z", image(seq) if img is None else img, "test")


def test_lost_then_recovered():
    monitor = HealthMonitor(HealthConfig(lost_reads=30), clock=lambda: 42.0)
    assert monitor.assess(frame(0, 1.0)) == []
    for _ in range(29):
        assert monitor.assess(None) == []
    assert monitor.state == OK
    [lost] = monitor.assess(None)  # the 30th consecutive failure
    assert (lost.kind, lost.t_mono) == ("source_lost", 42.0)
    assert monitor.state == LOST
    for _ in range(50):  # one event per episode
        assert monitor.assess(None) == []
    [recovered] = monitor.assess(frame(81, 50.0))
    assert (recovered.kind, recovered.t_mono) == ("source_recovered", 50.0)
    assert "80 failed reads" in recovered.detail
    assert monitor.state == OK


def test_short_failure_is_not_lost():
    monitor = HealthMonitor(HealthConfig(lost_reads=30))
    for _ in range(3):  # failure counter resets on every good frame
        assert monitor.assess(frame(0, 0.0)) == []
        for _ in range(29):
            assert monitor.assess(None) == []
    assert monitor.state == OK


def test_dark_then_light_returns_to_ok(clips):
    monitor = HealthMonitor(SHORT)
    dark = fixture_frames(clips["black"])
    assert [e.kind for e in assess_all(monitor, dark)] == ["dark_frames"]
    t = dark[-1].t_recv
    light = [frame(i, t + (i + 1) / FPS) for i in range(3)]
    assert assess_all(monitor, light) == []
    assert monitor.state == OK


class Clock:
    """Settable clock for failed reads."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_lost_after_lost_secs_with_few_slow_reads():
    """A blocking stream read can take seconds: lost must not wait for 30 reads (D-014)."""
    clock = Clock(10.0)
    monitor = HealthMonitor(HealthConfig(lost_reads=30, lost_secs=2.0), clock=clock)
    assert monitor.assess(None) == []  # failing since 10.0
    clock.t = 11.9
    assert monitor.assess(None) == []
    clock.t = 12.0
    [lost] = monitor.assess(None)
    assert (lost.kind, lost.t_mono) == ("source_lost", 12.0)
    clock.t = 20.0
    assert monitor.assess(None) == []  # still one event per episode


def test_frozen_clears_and_fires_again(clips):
    monitor = HealthMonitor(SHORT)
    frozen = fixture_frames(clips["frozen"])
    assert [e.kind for e in assess_all(monitor, frozen)] == ["frozen_frames"]
    t = frozen[-1].t_recv
    moving = [frame(i, t + (i + 1) / FPS) for i in range(3)]
    assert assess_all(monitor, moving) == []
    assert monitor.state == OK
    t = moving[-1].t_recv
    again = [dataclasses.replace(f, t_recv=t + f.t_recv + 1 / FPS) for f in frozen]
    assert [e.kind for e in assess_all(monitor, again)] == ["frozen_frames"]  # a new episode


def test_no_frozen_comparison_across_a_gap():
    """The first frame after a gap is not compared with the last one before it."""
    clock = Clock(1.0)
    monitor = HealthMonitor(HealthConfig(lost_reads=30, frozen_secs=1.0), clock=clock)
    img = image(0)
    assert monitor.assess(frame(0, 1.0, img)) == []
    for _ in range(30):
        monitor.assess(None)
    assert monitor.state == LOST
    events = monitor.assess(frame(31, 5.0, img.copy()))  # same image, 4 s later
    assert [e.kind for e in events] == ["source_recovered"]
    assert monitor.state == OK


def test_lost_has_priority_over_dark(clips):
    monitor = HealthMonitor(SHORT, clock=Clock(100.0))
    assess_all(monitor, fixture_frames(clips["black"]))
    assert monitor.state == DARK
    for _ in range(SHORT.lost_reads):
        monitor.assess(None)
    assert monitor.state == LOST
