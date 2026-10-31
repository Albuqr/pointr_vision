"""CLI entry point of one camera (PHASE_01, PHASE_02, PHASE_03): its arguments (run/args.py) are
planned and executed as a group of one (D-071, services/edge/run/). --replay of a group id replays
the group.

    python -m services.edge.main --source <ref> | --replay <target> [options]

See `python -m services.edge.main --help` for the options.
"""

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
from services.edge.run.wait import benchmark, plain, preview


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stop = StopRequest()
    try:
        if args.stop_on_stdin:
            stop_on_stdin(stop)
        try:
            plan = plan_from_args([args])
        except PlanError as e:
            return e.report(Reporter())
        reporter = Reporter(tagged=not plan.solo)  # a group replay tags each camera's lines
        if args.preview and plan.solo:  # the window shows one camera
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


if __name__ == "__main__":
    sys.exit(main())
