"""The group runner (R2a 03, ADR 0007): every camera of a group in one process, with one detector.

Each camera keeps its own capture thread, processing thread, tracker, session writer and recorder
(one CameraPipeline each), so its session folder, frame rate, drops and app delay are its own, as
with one process per camera. The detector is loaded once by the caller and shared: frames of every
camera go through it in turn. Each camera keeps its own calibration. Track IDs are unique within
the group run: the cross-camera matcher (R2a 05, `matcher.py`) gives the same ID to a person two
calibrated cameras both see (or, without a court position, who looks alike: R2a 06), and each
tracks row says how its track was linked.

Failures (R2a 07): a camera's stream loss or outage is its own (its source_lost and
source_recovered events); the other cameras keep recording, and a camera that comes back re-links
through the matcher. A failure in shared code (the detector, the matcher) is a SharedCodeError and
ends every camera through the one shutdown path.
"""

import dataclasses
import functools
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from services.edge.appearance import describe
from services.edge.calibration.intake import FromFile, FromRun, Offer, take_calibration
from services.edge.camera_pipeline import (
    CameraPipeline,
    LiveInput,
    ReplayInput,
)
from services.edge.capture.health import HealthConfig
from services.edge.capture.types import Frame, FrameSource, HealthEvent, SourceInfo, utc_now
from services.edge.child_protocol import StartFailed, emit
from services.edge.matcher import CourtMatcher, CrossCameraMatcher, LocalTrack
from services.edge.perception.types import Detections, Detector, Tracker, TrackObs
from services.edge.recording.recorder import FileRecorder
from services.edge.replay.order import MatcherOrder
from services.edge.replay.resolve import ReplayTarget
from services.edge.run.stop import hold_ctrl_c, ignore_ctrl_c, release_ctrl_c, stop_end
from services.edge.run.wait import Waiter, plain
from services.edge.session.types import RunMeta, SessionMeta
from services.edge.session.writer import FileSessionWriter, device_id

# the appearance_only event's detail (DATA_CONTRACTS section 2, D-061); a calibration that could
# not be used has its own error event
APPEARANCE_ONLY = (
    "no valid calibration: tracks link to the other cameras by clothing colour and box height only"
)

# the replay_order_approximate event's detail (DATA_CONTRACTS section 2, D-072)
APPROXIMATE = (
    "the live run recorded no matcher-call order (frames.csv match_seq): frames are replayed in "
    "receive-time order, which is the live order only if no camera's processing lagged another's"
)

OnGroupEvent = Callable[[str, HealthEvent, float | None], None]  # camera_id, event, run's t0


class SharedCodeError(RuntimeError):
    """A failure in code every camera of the group depends on: it ends the whole group."""


@dataclass(frozen=True)
class RecordedCamera:
    """A camera that replays a video as a new run. In a group replay (R2a 08, D-060) its recorded
    session gets the run; a single replay (D-071) adds a run to a session too, or, with no session
    folder in `target`, starts a new session from a bare video file."""

    target: ReplayTarget  # the video and session folder, checked against session.json
    session_id: str | None  # of target's session; None for a bare file
    calibration: dict | None  # the live run's saved run block
    group_time: Callable[[int], float] | None = None  # video frame seq -> the live run's group
    # time (PC clock); None: the camera's own receive times, no group (decision 13)
    match_seq: dict[int, int] | None = None  # video frame seq -> the live run's matcher call
    # number (D-072); None: a live run without it, so the order is that of group_time


@dataclass(frozen=True)
class GroupCamera:
    camera_id: str
    source: FrameSource  # not opened yet
    link: str | None = None  # how the source reaches the PC (D-012); None: the source's own
    calibration_path: str | None = None  # checked against the opened source's size
    replay: RecordedCamera | None = None  # a replay; calibration_path is then unused
    offer: Offer = None  # what calibration to try, when given; it overrides calibration_path
    # and the replay's saved block (a single replay offers its own, D-071)

    @property
    def kind(self) -> str:
        """live | replay_session (adds a run to a recorded session) | replay_file (new session)."""
        if self.replay is None:
            return "live"
        return "replay_file" if self.replay.target.session_dir is None else "replay_session"


class SharedDetector:
    """One detector for every camera of the group, called from each camera's processing thread
    in turn. rfdetr 1.11.2's predict() also takes a list as one batch, but a batch would make each
    camera wait for the other's frame and mix their app delays (D-055)."""

    def __init__(self, detector):
        self._detector = detector
        self._lock = threading.Lock()

    def detect(self, frame: Frame) -> Detections:
        with self._lock:
            try:
                return self._detector.detect(frame)
            except Exception as e:
                raise SharedCodeError(f"detector: {e!r}") from e


class MatchNumbers:
    """Numbers the matcher calls of one group run, one counter for all its cameras, in the order
    the matcher sees them: the number is taken in the same critical section as the call (D-072)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next = 0

    def call(self, fn: Callable[[], list]) -> tuple[int, list]:
        with self._lock:
            n, self._next = self._next, self._next + 1
            return n, fn()


class CameraTracker:
    """A camera's own tracker, writing the matcher's group track IDs and links instead of its
    local ones. `positions` (a calibrated camera's PositionMap) gives each track's court position
    for the matcher; `image_size` is the size the calibration was made at, and a frame of another
    size has no positions (the writer leaves them empty too). Each track also reports its
    appearance, from its box in the frame. `match_seq` is the number of the matcher call of the
    frame last updated, None if it made none (frames.csv `match_seq`)."""

    def __init__(
        self,
        tracker,
        camera_id: str,
        matcher: CrossCameraMatcher,
        positions=None,
        image_size: tuple[int, int] | None = None,
        order: MatcherOrder | None = None,
        numbers: MatchNumbers | None = None,
    ):
        self._tracker, self._camera_id, self._matcher = tracker, camera_id, matcher
        self._positions, self._image_size = positions, image_size
        self._order = order  # a group replay: the live run's group time, in its order
        self._numbers = numbers or MatchNumbers()  # shared by the cameras of a group run
        self.match_seq: int | None = None

    def _court_xy(self, box, frame: Frame):
        if self._positions is None or frame.image.shape[1::-1] != self._image_size:
            return None
        try:
            return self._positions((box[0] + box[2]) / 2, box[3])
        except Exception:  # a point that cannot be projected is a track without a position
            return None

    def update(self, dets: Detections, frame: Frame) -> list[TrackObs]:
        self.match_seq = None
        if self._order is None:
            return self._update(dets, frame)
        if not self._order.takes(self._camera_id, frame.seq):
            return []  # the live run gave this frame to no matcher: nor does the replay
        with self._order.turn(self._camera_id, frame.seq) as t:
            return self._update(dets, dataclasses.replace(frame, t_recv=t))

    def _update(self, dets: Detections, frame: Frame) -> list[TrackObs]:
        tracks = self._tracker.update(dets, frame)
        local = [
            LocalTrack(t.track_id, self._court_xy(t.xyxy, frame), describe(frame.image, t.xyxy))
            for t in tracks
        ]
        try:  # also with no tracks: the camera reported
            self.match_seq, linked = self._numbers.call(
                lambda: self._matcher.update(self._camera_id, frame.t_recv, local)
            )
        except Exception as e:
            raise SharedCodeError(f"matcher: {e!r}") from e
        return [
            dataclasses.replace(t, track_id=g.group_id, link=g.link)
            for t, g in zip(tracks, linked, strict=True)
        ]


def is_solo(cameras: list[GroupCamera]) -> bool:
    """A group of one (D-071): one camera that is not a group replay. No matcher, no group block."""
    return len(cameras) == 1 and not (cameras[0].replay and cameras[0].replay.group_time)


def _raise_shared_failure(pipelines: list[CameraPipeline]) -> None:
    for p in pipelines:
        if isinstance(p.error, SharedCodeError):
            raise p.error


def run_group(
    group_id: str | None,
    cameras: list[GroupCamera],
    detector: Detector | None,
    make_tracker: Callable[[str], Tracker] | None,
    out: Path | str,
    config: HealthConfig,
    make_run: Callable[[str, SourceInfo], RunMeta],
    *,
    record: bool = True,
    matcher: CrossCameraMatcher | None = None,
    stop: threading.Event | None = None,
    on_event: OnGroupEvent | None = None,
    on_session: Callable[[str, CameraPipeline], None] | None = None,
    ui_stop: Callable[[], bool] = lambda: False,
    wait: Waiter = plain,
) -> dict[str, str]:
    """Run the cameras of a group until every source ends or `stop` is set, then end every
    camera's session. Returns each camera's final session status. detector None runs no
    perception. A failure before the cameras start (a source that cannot open, a session that
    cannot be written) closes every source, ends the sessions already open with an event and
    status error, and is raised. A Ctrl+C or a failure while running ends every session (status
    interrupted or error, with an event) and is raised again, except Studio's stop (`ui_stop()`
    true when the Ctrl+C arrives), a normal end with a `stopped` event (D-049). A Ctrl+C while
    the sessions open waits until they are all open, then ends them the same way. A calibration
    that cannot be used is an event, and that camera records uncalibrated. `on_session` gets each
    camera's pipeline once its session is open, before any camera starts. `matcher` links the
    cameras' tracks (default: a CourtMatcher with its default parameters); its parameters go into
    every run's group block. A camera whose source is lost keeps its session open and the others
    run on; a SharedCodeError in any camera ends every session with status error and the failure as
    an event, and is raised.
    Cameras with `replay` are a group replay (D-060): each adds a run to its recorded
    session, records nothing and uses the live run's calibration (an unusable one is an event and
    that camera replays uncalibrated), and their frames reach the trackers and the matcher in the
    live run's group time, one at a time.
    One camera, not a group replay, is a group of one (D-071): no matcher, no appearance
    description, the detector and the tracker used directly (there is nobody to share with), and
    a null group block, so its files are those of a single camera. A replay with no
    `group_time` is that camera replaying one session, or a bare video file as a new session.
    `wait` is how the calling thread waits for the cameras (run/wait.py)."""
    camera_ids = [c.camera_id for c in cameras]
    if len(set(camera_ids)) != len(camera_ids):
        raise ValueError(f"a camera_id is given twice: {camera_ids}")
    replaying = any(c.replay for c in cameras)
    if replaying and not all(c.replay for c in cameras):
        raise ValueError("a group replay replays every camera of the group")
    group_replay = replaying and any(c.replay.group_time for c in cameras)
    solo = is_solo(cameras)
    if detector is not None and make_tracker is None:
        raise ValueError("a detector needs make_tracker")
    report = on_event or (lambda camera_id, ev, t0: None)
    infos: list[SourceInfo] = []
    opened: list[CameraPipeline] = []  # sessions started
    held = None
    stop_early = threading.Event()
    try:
        for cam in cameras:
            info = cam.source.open()
            infos.append(dataclasses.replace(info, link=cam.link) if cam.link else info)
        intakes = [
            take_calibration(
                cam.offer
                if cam.offer is not None
                else FromRun(cam.replay.calibration)
                if replaying and cam.replay.calibration is not None
                else FromFile(cam.calibration_path)
                if cam.calibration_path
                else None,
                cam.camera_id,
                (info.width, info.height),
            )
            for cam, info in zip(cameras, infos, strict=True)
        ]
        calibrations = [
            (i.calibration, i.calibration.positions() if i.calibration else None) for i in intakes
        ]
        shared_detector = detector if solo or detector is None else SharedDetector(detector)
        if detector is not None and matcher is None and not solo:
            matcher = CourtMatcher()
        order = (
            MatcherOrder(
                {c.camera_id: c.replay.group_time for c in cameras},
                {c.camera_id: c.replay.match_seq for c in cameras}
                if all(c.replay.match_seq is not None for c in cameras)
                else None,  # one camera without it: all go in group-time order
            )
            if group_replay and detector is not None
            else None
        )
        numbers = MatchNumbers()
        session_ids = [
            c.replay.session_id if c.kind == "replay_session" else str(uuid.uuid4())
            for c in cameras
        ]
        device = device_id(out)

        def make_input(cam, info, session_id, calibration):
            if cam.kind == "replay_session":
                return ReplayInput(cam.source, info, cam.replay.target.session_dir)
            meta = SessionMeta(
                session_id,
                device,
                utc_now(),
                info,
                record and not replaying,  # a replay already has its video
                cam.camera_id,
                group_id,
                calibration.session_block() if calibration else None,
            )
            if replaying:  # a bare video file: a new session, no recorder
                return ReplayInput(cam.source, info, None, meta)
            return LiveInput(cam.source, info, meta, FileRecorder() if record else None)

        inputs = [
            make_input(cam, info, session_id, calibration)
            for cam, info, session_id, (calibration, _) in zip(
                cameras, infos, session_ids, calibrations, strict=True
            )
        ]
        pipelines = [
            CameraPipeline(
                input,
                FileSessionWriter(out),
                config,
                detector=shared_detector,
                tracker=None
                if detector is None
                else make_tracker(cam.camera_id)
                if solo
                else CameraTracker(
                    make_tracker(cam.camera_id),
                    cam.camera_id,
                    matcher,
                    positions,
                    calibration and calibration.image_size,
                    order,
                    numbers,
                ),
                calibration=calibration,
                positions=positions,
                on_event=functools.partial(report, cam.camera_id),
            )
            for cam, input, (calibration, positions) in zip(
                cameras, inputs, calibrations, strict=True
            )
        ]
        runs = [make_run(c, info) for c, info in zip(camera_ids, infos, strict=True)]
        group = (
            None
            if solo
            else {
                "group_id": group_id,
                "group_run_id": str(uuid.uuid4()),
                "cameras": [
                    {"camera_id": c, "session_id": s, "run_id": r.run_id}
                    for c, s, r in zip(camera_ids, session_ids, runs, strict=True)
                ],
                "params": {}
                if detector is None
                else matcher.record_params(),  # no detector, no matching
            }
        )
        # a stop from here on waits until every session is open, so it ends them all, not half
        held = hold_ctrl_c(stop_early)
        for i, p in enumerate(pipelines):
            run = dataclasses.replace(
                runs[i], group=group, checks=intakes[i].checks or runs[i].checks
            )
            p.open_session(run)
            opened.append(p)
            for event in intakes[i].events:
                p.log_event(event)
            if order and not order.exact:
                p.log_event(HealthEvent("replay_order_approximate", utc_now(), None, APPROXIMATE))
            if detector is not None and len(cameras) > 1 and calibrations[i][1] is None:
                p.log_event(HealthEvent("appearance_only", utc_now(), None, APPEARANCE_ONLY))
            if on_session:
                on_session(camera_ids[i], p)
    except BaseException as e:
        release_ctrl_c(held)
        for p in opened:  # stop() closes its source
            p.log_event(
                HealthEvent("error", utc_now(), time.perf_counter(), f"group did not start: {e!r}")
            )
            p.stop("error")
        for cam in cameras[len(opened) : len(infos)]:
            cam.source.close()
        raise

    stop = stop or threading.Event()
    status = "ended"

    def check() -> None:
        for camera_id, p in zip(camera_ids, pipelines, strict=True):
            if order and p.done.is_set():  # its frames are over: nobody waits for them
                order.finish(camera_id)
        _raise_shared_failure(pipelines)

    try:
        # released inside the try: a stop that arrives right after still ends every session
        release_ctrl_c(held)
        if stop_early.is_set():  # held while the sessions opened: one shutdown path ends them
            raise KeyboardInterrupt
        for p in pipelines:
            p.start()
        wait(pipelines, stop, check)
        _raise_shared_failure(pipelines)  # also when the failing camera was the last one running
    except KeyboardInterrupt:
        end = stop_end(ui=ui_stop(), session=True)  # Studio's stop is a normal end (D-049)
        status = end.status
        for p in pipelines:
            p.log_event(end.event(time.perf_counter()))
        if end.exit_code:
            raise
    except Exception as e:  # one shutdown path; the failure is an event in every session
        status = "error"
        for p in pipelines:
            p.log_event(HealthEvent("error", utc_now(), time.perf_counter(), f"group: {e!r}"))
        raise
    finally:
        if order:  # a stop: the frames still waiting go through and the cameras drain
            order.close()
        statuses = {}
        # The shutdown path (ARCHITECTURE section 5): more Ctrl+C presses must not skip a step or
        # a session's final write; every wait in it is bounded
        previous = ignore_ctrl_c()
        try:
            for camera_id, p in zip(camera_ids, pipelines, strict=True):
                try:
                    statuses[camera_id] = p.stop(status)
                except BaseException as e:  # a failure: the others still stop
                    statuses[camera_id] = "error"
                    emit(StartFailed("exited", f"{camera_id} did not stop cleanly: {e!r}"))
        finally:
            release_ctrl_c(previous)
    return statuses
