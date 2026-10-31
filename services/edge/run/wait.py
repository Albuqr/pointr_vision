"""How the main thread waits while a run goes on (R2a follow-up T11, D-071). A waiter returns when
every camera is done, `stop` is set, or its own end comes first: a benchmark's deadline, or the
operator closing the preview window. `tick` is the run's own check, called about every 0.1 s; it
raises when a failure in shared code has to end the run."""

import threading
import time
from collections.abc import Callable, Sequence

from services.edge.camera_pipeline import CameraPipeline
from services.edge.ui.preview import run_preview

Waiter = Callable[[Sequence[CameraPipeline], threading.Event, Callable[[], None]], None]


def plain(pipelines, stop, tick) -> None:
    """Until every camera is done."""
    while not all(p.done.is_set() for p in pipelines) and not stop.wait(0.1):
        tick()


def benchmark(seconds: float) -> Waiter:
    """Until every camera is done or `seconds` after the wait began."""

    def wait(pipelines, stop, tick) -> None:
        until = time.perf_counter() + seconds
        while not all(p.done.is_set() for p in pipelines) and not stop.wait(0.1):
            tick()
            if time.perf_counter() >= until:
                break

    return wait


def preview(title: str | None = None, seconds: float | None = None) -> Waiter:
    """The cv2 window of one camera, on the main thread (cv2 windows need it), until the camera is
    done, `q` is pressed or `seconds` have passed. A window shows one camera: a group has none."""

    def wait(pipelines, stop, tick) -> None:
        [p] = pipelines
        until = None if seconds is None else time.perf_counter() + seconds
        run_preview(p.latest, p.done, p.hud, p.health_state, until, title)

    return wait
