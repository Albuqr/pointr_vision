"""Group replay (R2a 08, D-060): a recorded group's videos processed again together, one new run
in every camera's session, in the live run's group time and matcher-call order, so the matcher gives
the live run's shared IDs on the same frames.

    python -m services.edge.main --replay <group_id> [--out sessions] [detector options]
"""

import argparse
import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from services.edge.capture.sources import FileSource
from services.edge.group_runner import GroupCamera, RecordedCamera
from services.edge.matcher import CourtMatcher, MatcherParams
from services.edge.recording.recorder import recorded_fps
from services.edge.replay.resolve import ReplayError, resolve_replay
from services.edge.run.plan import PlanError, RunPlan
from services.edge.session.folder import (
    Rows,
    RunSnapshot,
    SessionDamaged,
    find_sessions,
    read_frames,
    run_paths,
    video_frames,
)


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


def live_group_time(frames: Rows, t0_mono: float, fps: float) -> Callable[[int], float]:
    """Video frame k -> the live run's group time of that frame: t0_mono + t_recv of the frame the
    live run recorded at k / fps; linear between the frames it processed, 1 / fps steps before the
    first and after the last."""
    known = [(k, t0_mono + float(r["t_recv"])) for k, r in video_frames(frames, fps)]
    if not known:
        raise ReplayError("the live run has no frame with a video time to replay in group time")
    index, times = (list(v) for v in zip(*known, strict=True))

    def at(k: int) -> float:
        if k <= index[0]:
            return times[0] - (index[0] - k) / fps
        if k >= index[-1]:
            return times[-1] + (k - index[-1]) / fps
        return float(np.interp(k, index, times))

    return at


def live_match_seq(frames: Rows, fps: float) -> dict[int, int] | None:
    """Video frame k -> the number of the live run's matcher call for that frame (frames.csv
    `match_seq`, D-072), for the frames it gave to the matcher; None for a live run from before
    the column (0.27.0), whose order is then only known by receive time."""
    if "match_seq" not in frames.columns:
        return None
    return {k: int(r["match_seq"]) for k, r in video_frames(frames, fps) if r["match_seq"]}


def _load(snapshot: RunSnapshot) -> dict:
    try:
        document = snapshot.require()
        if snapshot.calibration_damaged:
            document["calibration"] = {}  # preserve refusal through the tolerant reader
        return document
    except (SessionDamaged, json.JSONDecodeError) as e:
        raise ReplayError(str(e)) from e


def resolve_group(target: str, out_dir: Path | str) -> GroupReplay | None:
    """The sessions under out_dir whose group_id is `target`, ready to replay together; None when
    there are none. Raises ReplayError when they cannot be replayed as one group."""
    out = Path(out_dir)
    found = []
    for snapshot in find_sessions(out, group_id=target):
        try:
            session = snapshot.require("camera_id", "runs", "source", "session_id")
            run_paths(snapshot.path)  # validate every listed folder name before joining paths
        except SessionDamaged as error:
            raise ReplayError(str(error)) from error
        found.append((snapshot, session))
    if not found:
        return None
    cameras, group_runs, params = [], set(), {}
    for snapshot, session in found:
        folder = snapshot.path
        try:
            if not session.get("camera_id") or not session.get("runs"):
                raise ReplayError(f"{folder} has no camera_id or no run")
            live_run = snapshot.live_run  # replays come after it
            if live_run is None:
                raise ReplayError(f"{folder} has no readable live run")
            live = _load(live_run)
            if not live_run.is_live or live.get("t0_mono") is None:
                raise ReplayError(f"{live_run.path} is not a live run that started")
            group = live.get("group") or {}
            group_runs.add(group.get("group_run_id"))
            params = group.get("params") or params
            fps = recorded_fps(session["source"].get("reported_fps"))
            frames = read_frames(live_run.path)
            replay = resolve_replay(str(folder), out)
            recorded = RecordedCamera(
                replay,
                session["session_id"],
                live.get("calibration"),
                live_group_time(frames, live["t0_mono"], fps),
                live_match_seq(frames, fps),
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
    if args.calibration or args.calibration_failed or args.camera_id:
        raise PlanError(
            "config_conflict",
            "a group replay takes each camera's id and calibration from its session; "
            "do not pass --calibration, --calibration-failed or --camera-id",
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
