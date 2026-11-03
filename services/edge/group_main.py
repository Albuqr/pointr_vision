"""The one process the launcher starts (R2a 04, ADR 0007): every camera of a group, one camera
included. It parses the cameras' arguments and runs them (services/edge/run/entry.py), as
services.edge.main does for one:

    python -m services.edge.group_main CAMERA_ARGS [CAMERA_ARGS ...]

Each CAMERA_ARGS is a JSON list: the arguments services.edge.main would get for that camera
(launcher.camera_args). The settings of the one detector (device, threshold, det-size) and the
stop channel come from the cameras' arguments. Every output line about one camera starts with
"[camera_id] ", so the launcher can tell the cameras apart; lines about the group (device, model
load, a failure to start) have no prefix. One camera is a group of one (D-071): its lines are
untagged, its files are a single camera's, and --preview opens its window. --benchmark SECONDS
ends the group after SECONDS and prints every camera's block.
"""

import json
import sys

from services.edge.run.args import parse_args
from services.edge.run.entry import run_cameras


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    return run_cameras([parse_args(json.loads(text)) for text in argv])


if __name__ == "__main__":
    sys.exit(main())
