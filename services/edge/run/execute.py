"""Run a plan (R2a follow-up T11, D-071, ADR 0007): the one place a run starts and ends, for one
camera or a group, live or replaying. One process, one detector shared by the cameras, a capture
thread per camera (group_runner.run_group does the running); this module does what surrounds it:
loads the perception, says the lines of each camera, starts the HTTP previews, and ends the run
the same way whatever stopped it.

Every session that was opened gets a final status on every path (run_group's shutdown), and the
outcome says each one. A stop before any session exists is the one end with no status to give."""

import argparse
import dataclasses
import sys
import threading
from collections import Counter
from collections.abc import Callable

import cv2
import numpy as np

from services.edge.capture.sources import CameraSource, SourceOpenError
from services.edge.capture.types import HealthEvent
from services.edge.child_protocol import PreviewListening, SessionOpened, StartFailed, Summary
from services.edge.group_runner import run_group
from services.edge.run.meta import RunSettings, health_config, run_meta
from services.edge.run.perception import Perception
from services.edge.run.plan import RunPlan
from services.edge.run.preview import start_http_preview
from services.edge.run.report import Reporter, format_benchmark
from services.edge.run.stop import (
    EXIT_CAPTURE_ERROR,
    EXIT_INTERRUPTED,
    EXIT_OPEN_FAILED,
    StopRequest,
    stop_before_session,
    stop_end,
)
from services.edge.run.wait import Waiter, plain


@dataclasses.dataclass(frozen=True)
class RunOutcome:
    exit_code: int
    statuses: dict[str | None, str]  # each opened session's final status, by camera id


def execute(
    plan: RunPlan,
    stop: StopRequest,
    *,
    perception: Callable[[argparse.Namespace], Perception | None],
    make_tracker: Callable[[argparse.Namespace], object],
    reporter: Reporter,
    waiter: Waiter = plain,
) -> RunOutcome:
    """Run `plan` to its end. `perception` loads the detector for the run's settings (None: it
    failed and said so); `make_tracker` makes a camera's tracker from its arguments; `reporter`
    says the lines; `waiter` is how this thread waits meanwhile (the preview window needs the main
    thread). A stop is `stop` (Studio's or Ctrl+C), ended by one table (run/stop.py)."""
    pipelines: dict = {}
    try:
        return _run(plan, stop, perception, make_tracker, reporter, waiter, pipelines)
    except KeyboardInterrupt:
        if pipelines:  # the sessions already ended; only the lines after them were cut short
            return RunOutcome(
                stop_end(ui=stop.ui, session=True).exit_code,
                {c: p.status for c, p in pipelines.items()},
            )
        # a stop before any session (model load, slow source open): no status to give
        return RunOutcome(
            stop_before_session(stop, lambda ev, t0: reporter.event(None, ev, t0)), {}
        )


def _run(plan, stop, perception, make_tracker, reporter, waiter, pipelines) -> RunOutcome:
    settings = plan.settings
    config = health_config(settings)
    for cam in plan.cameras:
        if cam.replay and not cam.replay.target.verified:
            reporter.unverified(cam.camera_id)
    loaded = perception(settings)
    if loaded is None:
        return RunOutcome(EXIT_CAPTURE_ERROR, {})
    detector = loaded.detector
    cameras = {c.camera_id: c for c in plan.cameras}
    counts = {camera_id: Counter() for camera_id in cameras}
    counts_lock = threading.Lock()  # called from the capture, processing and main threads
    run_settings = {camera_id: RunSettings.from_args(a) for camera_id, a in plan.args.items()}

    def make_run(camera_id, info):
        tracker = None if detector is None else make_tracker(plan.args[camera_id])
        replay = cameras[camera_id].replay
        return run_meta(
            run_settings[camera_id],
            info,
            config,
            detector,
            tracker,
            loaded.gpu,
            replay.target if replay else None,
            loaded.model_loaded,
        )

    def on_event(camera_id, ev: HealthEvent, t0) -> None:
        with counts_lock:
            counts[camera_id][ev.kind] += 1
            reporter.event(camera_id, ev, t0)

    previews = []

    def on_session(camera_id, pipeline) -> None:
        a, info = plan.args[camera_id], pipeline.info
        pipelines[camera_id] = pipeline
        reporter.line(camera_id, f"source: {info}")
        if isinstance(cameras[camera_id].source, CameraSource):  # streams and files deliver theirs
            reporter.line(
                camera_id,
                f"requested {a.width}x{a.height}, camera delivers {info.width}x{info.height}",
            )
        reporter.line(camera_id, f"health: {config}")
        py = sys.version.split()[0]
        reporter.line(
            camera_id, f"versions: python {py}, opencv {cv2.__version__}, numpy {np.__version__}"
        )
        reporter.tell(camera_id, SessionOpened(str(pipeline.session_dir)))
        if a.http_preview is not None:
            previews.append(start_http_preview(a.http_preview, pipeline))
            reporter.tell(camera_id, PreviewListening(previews[-1].port))

    code, statuses = 0, {}
    try:
        statuses = run_group(
            plan.group_id,
            plan.cameras,
            detector,
            lambda camera_id: make_tracker(plan.args[camera_id]),
            plan.out,
            config,
            make_run,
            record=plan.record,
            matcher=plan.matcher,
            on_event=on_event,
            on_session=on_session,
            ui_stop=lambda: stop.ui,  # Studio's stop is a normal end (D-049)
            wait=waiter,
        )
        if any(s != "ended" for s in statuses.values()):
            code = EXIT_CAPTURE_ERROR
    except KeyboardInterrupt:  # every session already ended `interrupted`
        if not pipelines:  # a stop before any session: execute's pre-session end
            raise
        code = stop_end(ui=stop.ui, session=True).exit_code
    except Exception as e:  # every session already ended `error`, with the failure as an event
        code = _failed(e, plan, bool(pipelines), reporter)
    finally:
        for preview in previews:
            preview.close()

    try:  # the sessions are saved: a stop now only cuts the lines short
        for camera_id, p in pipelines.items():
            snapshot = p.stats()
            reporter.line(camera_id, f"session {p.status}: {p.session_dir}")
            reporter.tell(
                camera_id,
                Summary(
                    f"t0_wall={snapshot.t0_wall} captured={snapshot.captured} "
                    f"dropped={snapshot.dropped} failed_reads={snapshot.failed_reads} "
                    f"processed={snapshot.processed} unprocessed={snapshot.unprocessed} "
                    f"events={dict(counts[camera_id])}"
                ),
            )
            if plan.benchmark:
                a = plan.args[camera_id]
                reporter.line(
                    camera_id,
                    format_benchmark(
                        plan.benchmark,
                        p.info.link,
                        "off" if detector is None else detector.det_size,
                        "-" if detector is None else detector.device,
                        snapshot,
                        preview=a.http_preview is not None or a.preview,
                    ),
                )
            reporter.report(camera_id, p.run_dir)
    except KeyboardInterrupt:
        print("warning: reports interrupted; run python -m services.edge.report", file=sys.stderr)
        code = code or EXIT_INTERRUPTED
    return RunOutcome(code, {c: statuses.get(c) or p.status for c, p in pipelines.items()})


def _failed(e: Exception, plan: RunPlan, started: bool, reporter: Reporter) -> int:
    """Say how the run failed, and the exit code. `started`: a session was opened, so it already
    ended `error` with the failure as an event."""
    [first, *_] = plan.cameras
    if not started and isinstance(e, SourceOpenError | cv2.error) and plan.solo:
        a = plan.args[first.camera_id]
        reporter.source_open_failed(first.camera_id, a.replay or a.source, str(e).strip())
        return EXIT_OPEN_FAILED
    if not started and isinstance(e, OSError) and plan.solo:
        reporter.tell(
            first.camera_id,
            StartFailed("exited", f"cannot write session data under {plan.out!r}: {e}"),
        )
        return EXIT_CAPTURE_ERROR
    replay = " replay" if any(c.replay for c in plan.cameras) else ""
    if not plan.solo:  # a group of one has nothing to add to the failure event in its session
        reporter.tell(
            None,
            StartFailed(
                "source_open_failed" if isinstance(e, SourceOpenError) else "exited",
                f"the group{replay} did not run: {e}",
            ),
        )
    return EXIT_OPEN_FAILED if isinstance(e, SourceOpenError) else EXIT_CAPTURE_ERROR
