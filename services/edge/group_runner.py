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
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from services.edge.appearance import describe
from services.edge.calibration.homography import CalibrationPositions, check_homography
from services.edge.camera_pipeline import (
    CameraPipeline,
    load_camera_calibration,
    session_calibration,
)
from services.edge.capture.health import HealthConfig
from services.edge.capture.types import Frame, FrameSource, HealthEvent, SourceInfo, utc_now
from services.edge.contract import UI_STOP_DETAIL
from services.edge.matcher import CourtMatcher, CrossCameraMatcher, LocalTrack
from services.edge.perception.types import Detections, Detector, Tracker, TrackObs
from services.edge.recording.recorder import FileRecorder
from services.edge.replay.order import GroupTimeOrder
from services.edge.replay.resolve import ReplayTarget
from services.edge.session.types import RunMeta, SessionMeta
from services.edge.session.writer import FileSessionWriter, device_id

# the appearance_only event's detail (DATA_CONTRACTS section 2, D-061); a calibration that could
# not be used has its own error event
APPEARANCE_ONLY = (
    "no valid calibration: tracks link to the other cameras by clothing colour and box height only"
)

OnGroupEvent = Callable[[str, HealthEvent, float | None], None]  # camera_id, event, run's t0


class SharedCodeError(RuntimeError):
    """A failure in code every camera of the group depends on: it ends the whole group."""


@dataclass(frozen=True)
class RecordedCamera:
    """A camera of a group replay (R2a 08, D-060): its recorded session gets a new run."""

    target: ReplayTarget  # the video and session folder, checked against session.json
    session_id: str
    calibration: dict | None  # the live run's, as a document (calibration.document)
    group_time: Callable[[int], float]  # video frame seq -> the live run's group time (PC clock)


@dataclass(frozen=True)
class GroupCamera:
    camera_id: str
    source: FrameSource  # not opened yet
    link: str | None = None  # how the source reaches the PC (D-012); None: the source's own
    calibration_path: str | None = None  # checked against the opened source's size
    replay: RecordedCamera | None = None  # a group replay; calibration_path is then unused


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


class CameraTracker:
    """A camera's own tracker, writing the matcher's group track IDs and links instead of its
    local ones. `positions` (a calibrated camera's PositionMap) gives each track's court position
    for the matcher; `image_size` is the size the calibration was made at, and a frame of another
    size has no positions (the writer leaves them empty too). Each track also reports its
    appearance, from its box in the frame."""

    def __init__(
        self,
        tracker,
        camera_id: str,
        matcher: CrossCameraMatcher,
        positions=None,
        image_size: tuple[int, int] | None = None,
        order: GroupTimeOrder | None = None,
    ):
        self._tracker, self._camera_id, self._matcher = tracker, camera_id, matcher
        self._positions, self._image_size = positions, image_size
        self._order = order  # a group replay: the live run's group time, in its order

    def _court_xy(self, box, frame: Frame):
        if self._positions is None or frame.image.shape[1::-1] != self._image_size:
            return None
        try:
            return self._positions((box[0] + box[2]) / 2, box[3])
        except Exception:  # a point that cannot be projected is a track without a position
            return None

    def update(self, dets: Detections, frame: Frame) -> list[TrackObs]:
        if self._order is None:
            return self._update(dets, frame)
        with self._order.turn(self._camera_id, frame.seq) as t:
            return self._update(dets, dataclasses.replace(frame, t_recv=t))

    def _update(self, dets: Detections, frame: Frame) -> list[TrackObs]:
        tracks = self._tracker.update(dets, frame)
        local = [
            LocalTrack(t.track_id, self._court_xy(t.xyxy, frame), describe(frame.image, t.xyxy))
            for t in tracks
        ]
        try:  # also with no tracks: the camera reported
            linked = self._matcher.update(self._camera_id, frame.t_recv, local)
        except Exception as e:
            raise SharedCodeError(f"matcher: {e!r}") from e
        return [
            dataclasses.replace(t, track_id=g.group_id, link=g.link)
            for t, g in zip(tracks, linked, strict=True)
        ]


def _saved_positions(doc: dict) -> CalibrationPositions:
    """The positions of a replayed run's saved calibration; ValueError when it is unusable."""
    try:
        check_homography(doc["homography_image_to_court"])
        return CalibrationPositions(doc)
    except (KeyError, TypeError) as e:
        raise ValueError(f"the saved calibration block is malformed: {e!r}") from e


def _raise_shared_failure(pipelines: list[CameraPipeline]) -> None:
    for p in pipelines:
        if isinstance(p.processor.error, SharedCodeError):
            raise p.processor.error


def run_group(
    group_id: str,
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
) -> dict[str, str]:
    """Run the cameras of a group until every source ends or `stop` is set, then end every
    camera's session. Returns each camera's final session status. detector None runs no
    perception. A failure before the cameras start (a source that cannot open, a session that
    cannot be written) closes every source, ends the sessions already open with an event and
    status error, and is raised. A Ctrl+C or a failure while running ends every session (status
    interrupted or error, with an event) and is raised again, except Studio's stop (`ui_stop()`
    true when the Ctrl+C arrives), a normal end with a `stopped` event (D-049). A calibration that
    cannot be used is an event, and that camera records uncalibrated. `on_session` gets each
    camera's pipeline once its session is open, before any camera starts. `matcher` links the
    cameras' tracks (default: a CourtMatcher with its default parameters); its parameters go into
    every run's group block. A camera whose source is lost keeps its session open and the others
    run on; a SharedCodeError in any camera ends every session with status error and the failure as
    an event, and is raised.
    Cameras with `replay` are a group replay (D-060): each adds a run to its recorded
    session, records nothing and uses the live run's calibration (an unusable one is an event and
    that camera replays uncalibrated), and their frames reach the trackers and the matcher in the
    live run's group time, one at a time."""
    camera_ids = [c.camera_id for c in cameras]
    if len(set(camera_ids)) != len(camera_ids):
        raise ValueError(f"a camera_id is given twice: {camera_ids}")
    replaying = any(c.replay for c in cameras)
    if replaying and not all(c.replay for c in cameras):
        raise ValueError("a group replay replays every camera of the group")
    if detector is not None and make_tracker is None:
        raise ValueError("a detector needs make_tracker")
    report = on_event or (lambda camera_id, ev, t0: None)
    infos: list[SourceInfo] = []
    opened: list[CameraPipeline] = []  # sessions started
    try:
        for cam in cameras:
            info = cam.source.open()
            infos.append(dataclasses.replace(info, link=cam.link) if cam.link else info)
        calibrations = []  # (document, positions, why it was not used) per camera
        for cam, info in zip(cameras, infos, strict=True):
            try:
                calibrations.append(
                    (doc := cam.replay.calibration, doc and _saved_positions(doc), None)
                    if replaying
                    else (*load_camera_calibration(cam.calibration_path, cam.camera_id, info), None)
                    if cam.calibration_path
                    else (None, None, None)
                )
            except (ValueError, OSError) as e:
                calibrations.append((None, None, f"calibration not used: {e}"))
        shared_detector = None if detector is None else SharedDetector(detector)
        if detector is not None and matcher is None:
            matcher = CourtMatcher()
        order = (
            GroupTimeOrder({c.camera_id: c.replay.group_time for c in cameras})
            if replaying and detector is not None
            else None
        )
        pipelines = [
            CameraPipeline(
                cam.source,
                info,
                FileSessionWriter(out),
                config,
                detector=shared_detector,
                tracker=None
                if detector is None
                else CameraTracker(
                    make_tracker(cam.camera_id),
                    cam.camera_id,
                    matcher,
                    positions,
                    calibration
                    and (calibration["image_size"]["width"], calibration["image_size"]["height"]),
                    order,
                ),
                recorder=FileRecorder() if record and not replaying else None,
                calibration=calibration,
                positions=positions,
                replay=replaying,
                on_event=functools.partial(report, cam.camera_id),
            )
            for cam, info, (calibration, positions, _) in zip(
                cameras, infos, calibrations, strict=True
            )
        ]
        session_ids = [c.replay.session_id if replaying else str(uuid.uuid4()) for c in cameras]
        runs = [make_run(c, info) for c, info in zip(camera_ids, infos, strict=True)]
        group = {
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
        device = device_id(out)
        for i, p in enumerate(pipelines):
            run = dataclasses.replace(runs[i], group=group)
            if replaying:
                p.open_session(run, session_dir=cameras[i].replay.target.session_dir)
            else:
                meta = SessionMeta(
                    session_id=session_ids[i],
                    device_id=device,
                    started_at=utc_now(),
                    source=infos[i],
                    recording_enabled=record,
                    camera_id=camera_ids[i],
                    group_id=group_id,
                    calibration=session_calibration(p.calibration),
                )
                p.open_session(run, meta=meta)
            opened.append(p)
            if problem := calibrations[i][2]:  # before any run, so no t0: t_mono is null
                p.log_event(HealthEvent("error", utc_now(), None, problem))
            if detector is not None and len(cameras) > 1 and calibrations[i][1] is None:
                p.log_event(HealthEvent("appearance_only", utc_now(), None, APPEARANCE_ONLY))
            if on_session:
                on_session(camera_ids[i], p)
    except BaseException as e:
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
    try:
        for p in pipelines:
            p.start()
        while not all(p.done.is_set() for p in pipelines) and not stop.wait(0.1):
            for camera_id, p in zip(camera_ids, pipelines, strict=True):
                if order and p.done.is_set():  # its frames are over: nobody waits for them
                    order.finish(camera_id)
            _raise_shared_failure(pipelines)
        _raise_shared_failure(pipelines)  # also when the failing camera was the last one running
    except KeyboardInterrupt:
        if ui_stop():  # Studio's stop: a normal end (D-049)
            for p in pipelines:
                p.log_event(HealthEvent("stopped", utc_now(), time.perf_counter(), UI_STOP_DETAIL))
        else:
            status = "interrupted"
            for p in pipelines:
                p.log_event(HealthEvent("interrupted", utc_now(), time.perf_counter(), "Ctrl+C"))
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
        for camera_id, p in zip(camera_ids, pipelines, strict=True):
            try:
                statuses[camera_id] = p.stop(status)
            except BaseException as e:  # a second Ctrl+C or a failure: the others still stop
                statuses[camera_id] = "error"
                print(f"error: {camera_id} did not stop cleanly: {e!r}", file=sys.stderr)
    return statuses
