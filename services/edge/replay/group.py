"""Group replay (R2a 08, D-060): a recorded group's videos processed again together, one new run
in every camera's session, in the live run's group time, so the matcher gives the live run's shared
IDs on the same frames.

    python -m services.edge.main --replay <group_id> [--out sessions] [detector options]
"""

import argparse
import csv
import dataclasses
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from services.edge.capture.sources import FileSource
from services.edge.capture.types import utc_now
from services.edge.group_main import say
from services.edge.group_runner import GroupCamera, RecordedCamera, run_group
from services.edge.main import (
    EXIT_CAPTURE_ERROR,
    EXIT_INTERRUPTED,
    EXIT_OPEN_FAILED,
    RunSettings,
    create_tracker,
    health_config,
    load_perception,
    print_event,
    resolve_device,
    run_meta,
)
from services.edge.matcher import CourtMatcher, MatcherParams
from services.edge.recording.recorder import DEFAULT_FPS
from services.edge.replay.resolve import ReplayError, resolve_replay
from services.edge.reports.build import format_summary, write_report


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


def as_document(calibration: dict | None) -> dict | None:
    """run.json calibration as the calibration document the pipeline takes (it reads the check
    error from `errors` and the court type from `court.kind`)."""
    if calibration is None:
        return None
    court = {"kind": calibration["court"]["type"], **calibration["court"]}
    return {**calibration, "court": court, "errors": {"check_mean_m": calibration["check_error_m"]}}


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ReplayError(f"cannot read {path}: {e}") from e


def resolve_group(target: str, out_dir: Path | str) -> GroupReplay | None:
    """The sessions under out_dir whose group_id is `target`, ready to replay together; None when
    there are none. Raises ReplayError when they cannot be replayed as one group."""
    out = Path(out_dir)
    found = []
    for folder in sorted(out.iterdir()) if out.is_dir() else []:
        try:
            session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(session, dict) and session.get("group_id") == target:
            found.append((folder, session))
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
                as_document(live.get("calibration")),
                live_group_time(run_dir, live["t0_mono"], fps),
            )
            source = FileSource(replay.video, realtime=False)  # as fast as processing allows
            cameras.append(GroupCamera(session["camera_id"], source, "file", replay=recorded))
        except (OSError, ValueError, KeyError, TypeError) as e:  # a session not as written
            raise ReplayError(f"{folder} cannot be replayed: {e!r}") from e
    if len(group_runs) > 1:
        raise ReplayError(f"the sessions of group {target!r} come from more than one group run")
    return GroupReplay(target, cameras, params)


def run_replay(args: argparse.Namespace, group: GroupReplay) -> int:
    """The command for a group: what services.edge.main does for one replayed session, for every
    camera of the group through the group runner."""
    if args.calibration or args.camera_id:
        print(
            "error: a group replay takes each camera's id and calibration from its session; "
            "do not pass --calibration or --camera-id",
            file=sys.stderr,
        )
        return EXIT_OPEN_FAILED
    for cam in group.cameras:
        if not cam.replay.target.verified:
            say(cam.camera_id, "warning: the session has no video hash, so the video is unchecked")
    config = health_config(args)
    settings = RunSettings.from_args(args)
    detector = gpu = model_loaded = None
    if not args.no_detect:
        try:
            device, gpu = resolve_device(args.device)
            print(f"device: {device}" + (f" ({gpu})" if gpu else " (no CUDA GPU in use)"))
            detector, _ = load_perception(args, device)
            model_loaded = {"t_wall": utc_now(), "t_pc": time.perf_counter()}
        except Exception as e:
            print(f"error: {e!r}", file=sys.stderr)
            return EXIT_CAPTURE_ERROR
    targets = {c.camera_id: c.replay.target for c in group.cameras}

    def make_run(camera_id, info):
        tracker = None if detector is None else create_tracker(args)
        return run_meta(
            settings, info, config, detector, tracker, gpu, targets[camera_id], model_loaded
        )

    pipelines = {}

    def on_session(camera_id, pipeline):
        pipelines[camera_id] = pipeline
        say(camera_id, f"session: {pipeline.writer.dir}")

    code = 0
    try:
        statuses = run_group(
            group.group_id,
            group.cameras,
            detector,
            lambda camera_id: create_tracker(args),
            args.out,
            config,
            make_run,
            record=False,
            matcher=live_matcher(group.params, args.track_lost_secs),
            on_event=lambda camera_id, ev, t0: print_event(ev, t0, f"[{camera_id}] "),
            on_session=on_session,
        )
        if any(s != "ended" for s in statuses.values()):
            code = EXIT_CAPTURE_ERROR
    except KeyboardInterrupt:  # every run already ended (`interrupted`, or `error` if early)
        code = EXIT_INTERRUPTED
    except Exception as e:  # every replay run already ended `error`, with the failure as an event
        print(f"error: the group replay did not run: {e!r}", file=sys.stderr)
        code = EXIT_CAPTURE_ERROR
    for camera_id, p in pipelines.items():
        try:  # a failure is a warning: the run is saved (D-023)
            say(camera_id, format_summary(write_report(p.writer.run_dir)))
        except Exception as e:
            print(f"warning: {camera_id}: report not written: {e!r}", file=sys.stderr)
    return code
