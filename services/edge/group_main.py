"""The one process of a group (R2a 04, ADR 0007): what services.edge.main does for one camera,
for every camera of a group. It parses the cameras' arguments, plans the run and executes it
(services/edge/run/). The launcher starts it:

    python -m services.edge.group_main CAMERA_ARGS [CAMERA_ARGS ...]

Each CAMERA_ARGS is a JSON list: the arguments services.edge.main would get for that camera
(launcher.camera_args). The settings of the one detector (device, threshold, det-size) and the
stop channel come from the cameras' arguments. Every output line about one camera starts with
"[camera_id] ", so the launcher can tell the cameras apart; lines about the group (device, model
load, a failure to start) have no prefix. One camera is a group of one (D-071): its lines are
untagged and its files are a single camera's. --benchmark SECONDS ends the group after SECONDS and
prints every camera's block; the preview window is for a single camera, not a group.
"""

import json
import sys

from services.edge.run.args import parse_args
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
from services.edge.run.wait import benchmark, plain


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cams = [parse_args(json.loads(text)) for text in argv]
    stop = StopRequest()
    try:
        if any(a.stop_on_stdin for a in cams):
            stop_on_stdin(stop)
        return run(cams, stop)
    except KeyboardInterrupt:  # a stop before the sessions (model load, slow stream open)
        return stop_before_session(stop, print_event)


def run(cams: list, stop: StopRequest) -> int:
    """The group's settings (device, threshold, detection and recording on or off, out, group)
    come from the first camera: the launcher passes every camera the same ones. det-size is per
    camera in Studio, so a disagreement is a warning. One camera is a group of one: its lines
    carry no tag."""
    if any(a.preview for a in cams):
        print("warning: no preview window in a group; Studio shows each camera's preview")
    reporter = Reporter(tagged=len(cams) > 1)
    try:
        plan = plan_from_args(cams)
    except PlanError as e:
        return e.report(reporter)
    return execute(
        plan,
        stop,
        perception=lambda args: start_perception(
            args,
            resolve_device=resolve_device,
            load_perception=load_perception,
            emit=lambda ev, t0: reporter.event(None, ev, t0),
        ),
        make_tracker=lambda args: create_tracker(args),
        reporter=reporter,
        waiter=benchmark(plan.benchmark) if plan.benchmark else plain,
    ).exit_code


if __name__ == "__main__":
    sys.exit(main())
