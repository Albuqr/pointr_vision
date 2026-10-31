"""Group replay (R2a 08, D-060): a recorded group's videos processed again together, one new run
in every camera's session, in the live run's group time and matcher-call order, so the matcher gives
the live run's shared IDs on the same frames.

    python -m services.edge.main --replay <group_id> [--out sessions] [detector options]
"""

import argparse
import csv
import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from services.edge.capture.sources import FileSource
from services.edge.group_runner import GroupCamera, RecordedCamera
from services.edge.matcher import CourtMatcher, MatcherParams
from services.edge.recording.recorder import DEFAULT_FPS
from services.edge.replay.resolve import ReplayError, resolve_replay
from services.edge.run.execute import execute
from services.edge.run.perception import (
    create_tracker,
    load_perception,
    resolve_device,
    start_perception,
)
from services.edge.run.plan import PlanError, RunPlan
from services.edge.run.report import Reporter
from services.edge.run.stop import StopRequest
from services.edge.run.wait import benchmark, plain


@dataclass(frozen=True)
class GroupReplay:
    group_id: str
    cameras: list[GroupCamera]  # in the order of their session folders
    params: dict  # the live run's group.params; {} when it had none


def live_matcher(params: dict, lost_s: float) -> CourtMatcher:
    """The live run's matcher, from its group.params. A live run without one (a group recorded
    one process per camera, or without detection) gets the defaults, keeping tracks `lost_s`."""
    if not params:
        return CourtMatcher(MatcherParams(lost_s=lost_s))
    names = [f.name for f in dataclasses.fields(MatcherParams)]
    return CourtMatcher(MatcherParams(**{n: params[n] for n in names}), params["latency_s"])


def live_group_time(run_dir: Path, t0_mono: float, fps: float) -> Callable[[int], float]:
    """Video frame k -> the live run's group time of that frame: t0_mono + t_recv of the frame the
    live run recorded at k / fps; linear between the frames it processed, 1 / fps steps before the
    first and after the last."""
    with open(run_dir / "frames.csv", newline="", encoding="utf-8") as f:
        known = sorted(
            (round(float(r["t_video"]) * fps), t0_mono + float(r["t_recv"]))
            for r in csv.DictReader(f)
            if r["t_video"]
        )
    if not known:
        raise ReplayError(f"{run_dir} has no frame with a video time to replay in group time")
    index, times = (list(v) for v in zip(*known, strict=True))

    def at(k: int) -> float:
        if k <= index[0]:
            return times[0] - (index[0] - k) / fps
        if k >= index[-1]:
            return times[-1] + (k - index[-1]) / fps
        return float(np.interp(k, index, times))

    return at


def live_match_seq(run_dir: Path, fps: float) -> dict[int, int] | None:
    """Video frame k -> the number of the live run's matcher call for that frame (frames.csv
    `match_seq`, D-072), for the frames it gave to the matcher; None for a live run from before
    the column (0.27.0), whose order is then only known by receive time."""
    with open(run_dir / "frames.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "match_seq" not in (reader.fieldnames or ()):
            return None
        return {
            round(float(r["t_video"]) * fps): int(r["match_seq"])
            for r in reader
            if r["t_video"] and r["match_seq"]
        }


def _load(path: Path) -> dict:
    from services.edge.session.folder import SessionDamaged, read_run

    try:
        snapshot = read_run(path.parent)
        document = snapshot.require()
        if any("calibration" in problem for problem in snapshot.problems):
            document["calibration"] = {}  # preserve refusal through the tolerant reader
        return document
    except (SessionDamaged, json.JSONDecodeError) as e:
        raise ReplayError(str(e)) from e


def resolve_group(target: str, out_dir: Path | str) -> GroupReplay | None:
    """The sessions under out_dir whose group_id is `target`, ready to replay together; None when
    there are none. Raises ReplayError when they cannot be replayed as one group."""
    from services.edge.session.folder import SessionDamaged, find_sessions, run_paths

    out = Path(out_dir)
    found = []
    for snapshot in find_sessions(out, group_id=target):
        try:
            session = snapshot.require("camera_id", "runs", "source", "session_id")
            run_paths(snapshot.path)  # validate every listed folder name before joining paths
        except SessionDamaged as error:
            raise ReplayError(str(error)) from error
        found.append((snapshot.path, session))
    if not found:
        return None
    cameras, group_runs, params = [], set(), {}
    for folder, session in found:
        try:
            if not session.get("camera_id") or not session.get("runs"):
                raise ReplayError(f"{folder} has no camera_id or no run")
            run_dir = folder / "runs" / session["runs"][0]  # the live run: replays come after it
            live = _load(run_dir / "run.json")
            if live.get("mode") != "live" or live.get("t0_mono") is None:
                raise ReplayError(f"{run_dir} is not a live run that started")
            group = live.get("group") or {}
            group_runs.add(group.get("group_run_id"))
            params = group.get("params") or params
            fps = session["source"].get("reported_fps") or DEFAULT_FPS  # the recorder's rate
            replay = resolve_replay(str(folder), out)
            recorded = RecordedCamera(
                replay,
                session["session_id"],
                live.get("calibration"),
                live_group_time(run_dir, live["t0_mono"], fps),
                live_match_seq(run_dir, fps),
            )
            source = FileSource(replay.video, realtime=False)  # as fast as processing allows
            cameras.append(GroupCamera(session["camera_id"], source, "file", replay=recorded))
        except (OSError, ValueError, KeyError, TypeError) as e:  # a session not as written
            raise ReplayError(f"{folder} cannot be replayed: {e!r}") from e
    if len(group_runs) > 1:
        raise ReplayError(f"the sessions of group {target!r} come from more than one group run")
    return GroupReplay(target, cameras, params)


def plan_group_replay(args: argparse.Namespace, group: GroupReplay) -> RunPlan:
    """The plan for a group replay: every camera of the group again, in the live run's matcher. The
    cameras take their ids and calibrations from their sessions."""
    if args.calibration or args.camera_id:
        raise PlanError(
            "config_conflict",
            "a group replay takes each camera's id and calibration from its session; "
            "do not pass --calibration or --camera-id",
        )
    return RunPlan(
        group.cameras,
        {c.camera_id: args for c in group.cameras},
        args,
        group.group_id,
        False,
        live_matcher(group.params, args.track_lost_secs),
        args.benchmark,
    )


def run_replay(
    args: argparse.Namespace, group: GroupReplay, stop: StopRequest | None = None
) -> int:
    """The command for a group: what services.edge.main does for one replayed session, for every
    camera of the group through the run module."""
    reporter = Reporter(tagged=True)
    try:
        plan = plan_group_replay(args, group)
    except PlanError as e:
        return e.report(reporter)
    return execute(
        plan,
        stop or StopRequest(),
        perception=lambda a: start_perception(
            a,
            resolve_device=resolve_device,
            load_perception=load_perception,
            emit=lambda ev, t0: reporter.event(None, ev, t0),
        ),
        make_tracker=lambda a: create_tracker(a),
        reporter=reporter,
        waiter=benchmark(plan.benchmark) if plan.benchmark else plain,
    ).exit_code
