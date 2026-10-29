"""The group runner (R2a 03, ADR 0007): every camera of a group in one process, with one detector.

Each camera keeps its own capture thread, processing thread, tracker, session writer and recorder
(one CameraPipeline each), so its session folder, frame rate, drops and app delay are its own, as
with one process per camera. The detector is loaded once by the caller and shared: frames of every
camera go through it in turn. Each camera keeps its own calibration. Track IDs are unique
within the group run and not linked across cameras yet (`link` unshared); the cross-camera
matcher (R2a 05) links them.
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

from services.edge.camera_pipeline import (
    CameraPipeline,
    load_camera_calibration,
    session_calibration,
)
from services.edge.capture.health import HealthConfig
from services.edge.capture.types import Frame, FrameSource, HealthEvent, SourceInfo, utc_now
from services.edge.contract import UI_STOP_DETAIL
from services.edge.perception.types import Detections, Detector, Tracker, TrackObs
from services.edge.recording.recorder import FileRecorder
from services.edge.session.types import RunMeta, SessionMeta
from services.edge.session.writer import FileSessionWriter, device_id

OnGroupEvent = Callable[[str, HealthEvent, float | None], None]  # camera_id, event, run's t0


@dataclass(frozen=True)
class GroupCamera:
    camera_id: str
    source: FrameSource  # not opened yet
    link: str | None = None  # how the source reaches the PC (D-012); None: the source's own
    calibration_path: str | None = None  # checked against the opened source's size


class SharedDetector:
    """One detector for every camera of the group, called from each camera's processing thread
    in turn. rfdetr 1.11.2's predict() also takes a list as one batch, but a batch would make each
    camera wait for the other's frame and mix their app delays (D-055)."""

    def __init__(self, detector):
        self._detector = detector
        self._lock = threading.Lock()

    def detect(self, frame: Frame) -> Detections:
        with self._lock:
            return self._detector.detect(frame)


class GroupTrackIds:
    """A group track ID for each (camera, local tracker ID): unique within the group run."""

    def __init__(self):
        self._ids: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()  # every camera's processing thread asks

    def get(self, camera_id: str, local_id: int) -> int:
        with self._lock:
            return self._ids.setdefault((camera_id, local_id), len(self._ids) + 1)


class CameraTracker:
    """A camera's own tracker, writing group track IDs instead of its local ones."""

    def __init__(self, tracker, camera_id: str, ids: GroupTrackIds):
        self._tracker, self._camera_id, self._ids = tracker, camera_id, ids

    def update(self, dets: Detections, frame: Frame) -> list[TrackObs]:
        return [
            dataclasses.replace(t, track_id=self._ids.get(self._camera_id, t.track_id))
            for t in self._tracker.update(dets, frame)
        ]


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
    camera's pipeline once its session is open, before any camera starts."""
    camera_ids = [c.camera_id for c in cameras]
    if len(set(camera_ids)) != len(camera_ids):
        raise ValueError(f"a camera_id is given twice: {camera_ids}")
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
                    (*load_camera_calibration(cam.calibration_path, cam.camera_id, info), None)
                    if cam.calibration_path
                    else (None, None, None)
                )
            except (ValueError, OSError) as e:
                calibrations.append((None, None, f"calibration not used: {e}"))
        shared_detector = None if detector is None else SharedDetector(detector)
        ids = GroupTrackIds()
        pipelines = [
            CameraPipeline(
                cam.source,
                info,
                FileSessionWriter(out),
                config,
                detector=shared_detector,
                tracker=None
                if detector is None
                else CameraTracker(make_tracker(cam.camera_id), cam.camera_id, ids),
                recorder=FileRecorder() if record else None,
                calibration=calibration,
                positions=positions,
                on_event=functools.partial(report, cam.camera_id),
            )
            for cam, info, (calibration, positions, _) in zip(
                cameras, infos, calibrations, strict=True
            )
        ]
        session_ids = [str(uuid.uuid4()) for _ in cameras]
        runs = [make_run(c, info) for c, info in zip(camera_ids, infos, strict=True)]
        group = {
            "group_id": group_id,
            "group_run_id": str(uuid.uuid4()),
            "cameras": [
                {"camera_id": c, "session_id": s, "run_id": r.run_id}
                for c, s, r in zip(camera_ids, session_ids, runs, strict=True)
            ],
            "params": {},  # no matcher yet (R2a 05)
        }
        device = device_id(out)
        for i, p in enumerate(pipelines):
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
            p.open_session(dataclasses.replace(runs[i], group=group), meta=meta)
            opened.append(p)
            if problem := calibrations[i][2]:  # before any run, so no t0: t_mono is null
                p.log_event(HealthEvent("error", utc_now(), None, problem))
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
            pass
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
        statuses = {}
        for camera_id, p in zip(camera_ids, pipelines, strict=True):
            try:
                statuses[camera_id] = p.stop(status)
            except BaseException as e:  # a second Ctrl+C or a failure: the others still stop
                statuses[camera_id] = "error"
                print(f"error: {camera_id} did not stop cleanly: {e!r}", file=sys.stderr)
    return statuses
