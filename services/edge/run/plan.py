"""The plan of a run (R2a follow-up T11, D-071): what `execute` runs, built from parsed arguments
before the model loads. Every failure to plan (a source that cannot be found, a link that
contradicts its source, a replay target that cannot be replayed) is a `PlanError`, exit 2, so the
slow model load never starts for a run that cannot start.

A camera is `GroupCamera` (group_runner.py), of one of three kinds: `live`, `replay_session` (adds
a run to a recorded session) or `replay_file` (a bare video file, which starts a new session)."""

import argparse
import dataclasses
from pathlib import Path

from services.edge.calibration.intake import FromFile, FromRun, NotUsed, Offer, Refused
from services.edge.capture.sources import FileSource, SourceOpenError, open_source
from services.edge.child_protocol import StartFailed
from services.edge.group_runner import GroupCamera, RecordedCamera, is_solo
from services.edge.matcher import CourtMatcher, CrossCameraMatcher, MatcherParams
from services.edge.replay.resolve import ReplayError, ReplayTarget, resolve_replay
from services.edge.run.meta import link_conflict
from services.edge.run.report import Reporter
from services.edge.run.stop import EXIT_OPEN_FAILED


class PlanError(Exception):
    """The run cannot start. `reason` is set for a source that cannot be opened (the launcher
    shows its event line when there is no `error:` line), else `detail` is the whole message."""

    def __init__(
        self,
        kind: str,
        detail: str = "",
        *,
        camera_id: str | None = None,
        ref: str | None = None,
        reason: str | None = None,
    ):
        super().__init__(reason or detail)
        self.kind, self.detail, self.camera_id, self.ref, self.reason = (
            kind,
            detail,
            camera_id,
            ref,
            reason,
        )

    @classmethod
    def source(cls, ref: str, e: Exception, camera_id: str | None = None) -> "PlanError":
        return cls("source_open_failed", camera_id=camera_id, ref=ref, reason=str(e).strip())

    def report(self, reporter: Reporter) -> int:
        """Say why, and return the exit code."""
        if self.reason is not None:
            reporter.source_open_failed(self.camera_id, self.ref, self.reason)
        else:
            reporter.tell(self.camera_id, StartFailed(self.kind, self.detail))
        return EXIT_OPEN_FAILED


@dataclasses.dataclass(frozen=True)
class RunPlan:
    cameras: list[GroupCamera]  # sources not opened yet; one camera is a group of one
    args: dict[str | None, argparse.Namespace]  # each camera's arguments, by camera id
    settings: argparse.Namespace  # the run's: device, threshold, det-size, out, group, no-detect
    group_id: str | None  # of the sessions, and of the group block when there is one
    record: bool
    matcher: CrossCameraMatcher | None = None  # None: a group's default; a group of one has none
    benchmark: float | None = None  # seconds; the longest any camera asks for

    @property
    def out(self) -> str:
        return self.settings.out

    @property
    def solo(self) -> bool:
        return is_solo(self.cameras)


def group_det_size(sizes: set[int | None]) -> int | None:
    """One detector, one size (D-056): the largest a camera asks for; None (the model's own) when
    none asks for one. A camera that asks for none gets the size another camera asked for."""
    return max((s for s in sizes if s), default=None)


def group_matcher(cams: list[argparse.Namespace]) -> CourtMatcher:
    """The cross-camera matcher (D-058): a group ID is kept as long as the longest lost-track time
    of the cameras' trackers, so a track the tracker takes back is not forgotten first."""
    return CourtMatcher(MatcherParams(lost_s=max(a.track_lost_secs for a in cams)))


def calibration_offer(args: argparse.Namespace) -> Offer:
    """The calibration a camera is offered by its arguments: its file, else Studio's refusal
    (recorded as a failed check, D-057), else why the launcher passed none (an event)."""
    if args.calibration:
        return FromFile(args.calibration)
    if args.calibration_failed:
        return Refused(args.calibration_failed)
    if args.calibration_problem:
        return NotUsed(args.calibration_problem)
    return None


def single_replay(args: argparse.Namespace, offer: Offer) -> tuple[ReplayTarget, Offer]:
    """The target of a replay of one session or one video file, and the calibration to offer: the
    arguments' own, else the live run's saved one (decision 9). Raises ReplayError."""
    replay = resolve_replay(args.replay, args.out)
    if offer is None and replay.session_dir is not None:
        from services.edge.session.folder import SessionDamaged, read_session

        saved = read_session(replay.session_dir)
        try:
            if not saved.runs or saved.runs[0] is None:
                raise ReplayError("the recorded session has no readable live run")
            live = saved.runs[0]
            block = live.require().get("calibration")
        except SessionDamaged as exc:
            raise ReplayError(str(exc)) from exc
        # Tolerant snapshots replace malformed optional fields with None; damage is
        # a refused offer, while a genuinely absent calibration stays uncalibrated.
        if any("calibration" in problem for problem in live.problems):
            block = {}
        offer = FromRun(block) if block is not None else None
    return replay, offer


def plan_from_args(cams: list[argparse.Namespace]) -> RunPlan:
    """The plan for the cameras' arguments: live cameras (one is a group of one), or one `--replay`
    (a group id, a session or a video file). Raises PlanError; opens nothing."""
    if len(cams) == 1 and cams[0].replay:
        return _plan_replay(cams[0])
    return _plan_live(cams)


def _plan_live(cams: list[argparse.Namespace]) -> RunPlan:
    first = cams[0]
    sizes = {a.det_size for a in cams}
    if len(sizes) > 1:
        first = argparse.Namespace(**{**vars(first), "det_size": group_det_size(sizes)})
        asked = sorted(sizes, key=str)
        print(f"warning: cameras ask for det-size {asked}; the group uses {first.det_size}")
    cameras = []
    for a in cams:
        try:
            source = open_source(a.source, (a.width, a.height))
        except SourceOpenError as e:
            raise PlanError.source(a.source, e, a.camera_id) from e
        source.fps_cap = a.fps_cap
        if conflict := link_conflict(source.kind, a.link):
            raise PlanError("config_conflict", conflict, camera_id=a.camera_id)
        cameras.append(GroupCamera(a.camera_id, source, a.link, offer=calibration_offer(a)))
    return RunPlan(
        cameras,
        {a.camera_id: a for a in cams},
        first,
        first.group_id,
        not first.no_record,
        None if len(cams) == 1 else group_matcher(cams),
        max((a.benchmark for a in cams if a.benchmark), default=None),
    )


def _plan_replay(args: argparse.Namespace) -> RunPlan:
    try:
        if not Path(args.replay).exists():  # a group id: replay the group (D-060)
            from services.edge.replay.group import plan_group_replay, resolve_group

            group = resolve_group(args.replay, args.out)
            if group is not None:
                return plan_group_replay(args, group)
        replay, offer = single_replay(args, calibration_offer(args))
    except ReplayError as e:
        raise PlanError.source(args.replay, e) from e
    args = argparse.Namespace(
        **{**vars(args), "link": "file", "camera_id": args.camera_id or replay.camera_id}
    )
    source = FileSource(replay.video, realtime=False)  # as fast as processing allows
    source.fps_cap = args.fps_cap
    camera = GroupCamera(
        args.camera_id, source, "file", offer=offer, replay=RecordedCamera(replay, None, None)
    )
    return RunPlan(
        [camera], {args.camera_id: args}, args, args.group_id, False, None, args.benchmark
    )
