"""CLI entry point of one camera (PHASE_01, PHASE_02, PHASE_03): its arguments (run/args.py) are
planned and executed as a group of one (D-071, services/edge/run/entry.py). --replay of a group id
replays the group.

    python -m services.edge.main --source <ref> | --replay <target> [options]

See `python -m services.edge.main --help` for the options.
"""

import sys

from services.edge.run.args import parse_args
from services.edge.run.entry import run_cameras


def main(argv: list[str] | None = None) -> int:
    return run_cameras([parse_args(argv)])


if __name__ == "__main__":
    sys.exit(main())
