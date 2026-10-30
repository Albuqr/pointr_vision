"""Command line of the report (D-023).

    python -m services.edge.report <session_dir> [--run RUN_ID]
    python -m services.edge.report --group GROUP_ID --out C:/pointr_sessions

Writes runs/<run_id>/report.json and prints the summary. The group form finds every session
of the group under --out and prints one section per camera: each camera is reported on its
own, nothing is fused across cameras.
"""

import argparse
import json
import sys
from pathlib import Path

from services.edge.reports.build import format_summary, run_dirs, write_report
from services.edge.reports.movement import Params


def positive(text: str) -> float:
    value = float(text)
    if not value > 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(f"must be > 0, got {text}")
    return value


def odd(text: str) -> int:
    value = int(text)
    if value < 1 or value % 2 == 0:
        raise argparse.ArgumentTypeError(f"must be an odd number >= 1, got {text}")
    return value


def at_least_one(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {text}")
    return value


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    d = Params()
    p = argparse.ArgumentParser(prog="python -m services.edge.report", description=__doc__)
    p.add_argument("session_dir", nargs="?", type=Path, help="a session folder")
    p.add_argument("--run", help="run id (default: the session's last run)")
    p.add_argument("--group", help="report every session of this group_id under --out")
    p.add_argument("--out", type=Path, default=Path("sessions"), help="sessions folder (--group)")
    p.add_argument(
        "--max-gap",
        type=positive,
        default=d.max_gap,
        help="seconds; longer intervals are excluded from speed (default 1.0)",
    )
    p.add_argument(
        "--smooth",
        type=odd,
        default=d.smooth_window,
        help="moving-median window in samples (default 3)",
    )
    p.add_argument(
        "--min-intervals",
        type=at_least_one,
        default=d.min_valid_intervals,
        help="valid intervals needed for a speed (default 2)",
    )
    p.add_argument(
        "--short-track",
        type=positive,
        default=d.short_track,
        help="seconds: shorter tracks are flagged (default 1.0)",
    )
    p.add_argument("--stationary-below", type=positive, help="px/s: below this is stationary")
    p.add_argument(
        "--walking-below", type=positive, help="px/s: below this is walking, above running"
    )
    args = p.parse_args(argv)
    if bool(args.session_dir) == bool(args.group):
        p.error("give a session folder, or --group GROUP_ID")
    if args.group and args.run:
        p.error("--run applies to one session, not --group")
    if (
        args.stationary_below is not None
        and args.walking_below is not None
        and args.walking_below <= args.stationary_below
    ):
        p.error("--walking-below must be greater than --stationary-below")
    return args


def params_of(args: argparse.Namespace) -> Params:
    return Params(
        args.max_gap,
        args.smooth,
        args.min_intervals,
        args.short_track,
        args.stationary_below,
        args.walking_below,
    )


def group_sessions(out: Path, group_id: str) -> list[Path]:
    """Session folders under `out` whose session.json has this group_id, by camera_id."""
    found = []
    for f in sorted(Path(out).glob("*/session.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # not a readable session: not ours
        if isinstance(doc, dict) and doc.get("group_id") == group_id:
            found.append((doc.get("camera_id") or "", f.parent))
    return [folder for _, folder in sorted(found)]


def report_session(session_dir: Path, run_id: str | None, params: Params) -> str:
    """Write and format the report of one session's run (default: its last run)."""
    runs = run_dirs(session_dir)
    if run_id and run_id not in [r.name for r in runs]:  # also keeps --run inside this session
        raise ValueError(f"run {run_id!r} is not in {session_dir.name}")
    run_dir = session_dir / "runs" / run_id if run_id else runs[-1]
    return format_summary(write_report(run_dir, params=params))


ERRORS = (OSError, ValueError, KeyError, IndexError)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    params = params_of(args)
    if not args.group:
        try:
            print(report_session(args.session_dir, args.run, params))
        except ERRORS as e:
            print(f"error: cannot report: {e!r}", file=sys.stderr)
            return 2
        return 0
    sessions = group_sessions(args.out, args.group)
    if not sessions:
        print(f"error: no session with group_id {args.group} under {args.out}", file=sys.stderr)
        return 2
    print(f"group {args.group}: {len(sessions)} camera(s), reported one by one")
    failed = 0
    for folder in sessions:  # one bad camera must not hide the others
        try:
            print(f"\n{folder.name}\n{report_session(folder, None, params)}")
        except ERRORS as e:
            failed += 1
            print(f"\n{folder.name}\nerror: cannot report: {e!r}", file=sys.stderr)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
