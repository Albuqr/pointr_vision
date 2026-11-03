"""The run both entry points share (D-071): services.edge.main (one camera, or --replay of a
group) and services.edge.group_main (the launcher's process, one camera or several) parse their
arguments and hand the cameras here. It plans the run, executes it and ends a stop that comes
before the sessions exist. One camera is a group of one: its lines are untagged and, with
--preview, it gets the preview window; a group of several has no window (Studio shows each
camera's preview)."""

from services.edge.run.execute import execute
from services.edge.run.perception import (
    create_tracker,
    load_perception,
    resolve_device,
    start_perception,
)
from services.edge.run.plan import PlanError, plan_from_args
from services.edge.run.report import Reporter, print_event
from services.edge.run.stop import StopRequest, stop_before_session, stop_on_stdin
from services.edge.run.wait import benchmark, plain, preview


def run_cameras(cams: list) -> int:
    """The group's settings (device, threshold, detection and recording on or off, out, group)
    come from the first camera: the launcher passes every camera the same ones. det-size is per
    camera in Studio, so a disagreement is a warning."""
    stop = StopRequest()
    try:
        if any(a.stop_on_stdin for a in cams):
            stop_on_stdin(stop)
        try:
            plan = plan_from_args(cams)
        except PlanError as e:
            return e.report(Reporter(tagged=len(cams) > 1))
        reporter = Reporter(tagged=not plan.solo)  # a group tags each camera's lines
        wants_window = any(a.preview for a in cams)
        if wants_window and not plan.solo:
            print("warning: no preview window in a group; Studio shows each camera's preview")
        if wants_window and plan.solo:  # the window shows one camera
            camera_id = plan.cameras[0].camera_id
            title = f"Pointr {camera_id} (q to quit)" if camera_id else None
            waiter = preview(title, plan.benchmark)
        else:
            waiter = benchmark(plan.benchmark) if plan.benchmark else plain
        return execute(
            plan,
            stop,
            perception=lambda a: start_perception(
                a,
                resolve_device=resolve_device,
                load_perception=load_perception,
                emit=lambda ev, t0: reporter.event(None, ev, t0),
            ),
            make_tracker=create_tracker,
            reporter=reporter,
            waiter=waiter,
        ).exit_code
    except KeyboardInterrupt:  # Ctrl+C before execute (a slow stream open while planning)
        return stop_before_session(stop, print_event)
