"""The group runner (R2a 03, seam A, ADR 0007): the cameras of a group in one process with one
detector. Driven in-process with synthetic clips and a scripted fake detector; the tests read the
session folders back as a reader of the files would. No camera, weights or network."""

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from services.edge import contract
from services.edge.appearance import colour_distance, describe
from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import FileSource, SourceOpenError
from services.edge.capture.types import Frame
from services.edge.contract import VIDEO_FILE
from services.edge.group_runner import CameraTracker, GroupCamera, run_group
from services.edge.main import RunSettings, run_meta
from services.edge.matcher import CourtMatcher, GroupTrack, MatcherParams
from services.edge.perception.loop import NO_DETECTIONS
from services.edge.perception.types import Detections
from services.edge.session import writer as writer_mod
from services.edge.session.writer import FileSessionWriter
from tests.edge.fakes import EvenFrameDetector, OneTrackPerDetection
from tests.edge.test_calibration_size import calibration_file
from tests.edge.test_session import (
    load,
    rows,
    validate,
)
from tests.fixtures.make_clips import scene, write_clip


class CountingDetector(EvenFrameDetector):
    """The scripted fake detector, counting its instances and the cameras it saw frames from."""

    instances = 0

    def __init__(self):
        super().__init__()
        type(self).instances += 1
        self.sources: set[str] = set()
        self._lock = threading.Lock()

    def detect(self, frame):
        with self._lock:
            self.sources.add(frame.source_id)
        return super().detect(frame)


def run_two(
    clips, out: Path, detector, record=False, second=None, calibrations=None, **kw
) -> dict[str, str]:
    settings = RunSettings(None, None)
    config = HealthConfig()
    calibrations = calibrations or {}
    cameras = [
        GroupCamera(cid, FileSource(str(clip), realtime=False), "file", calibrations.get(cid))
        for cid, clip in (("cam1", clips["moving"]), ("cam2", second or clips["frozen"]))
    ]
    return run_group(
        "g1",
        cameras,
        detector,
        lambda camera_id: OneTrackPerDetection(),
        out,
        config,
        lambda camera_id, info: run_meta(
            settings, info, config, detector, OneTrackPerDetection(), None
        ),
        record=record,
        **kw,
    )


def camera_files(out: Path) -> dict[str, tuple[dict, dict, list[dict], list[dict]]]:
    """camera_id -> (session.json, run.json, frames rows, tracks rows) of each session folder."""
    files = {}
    for folder in (p for p in out.iterdir() if p.is_dir()):
        session = load(folder / "session.json")
        [run_dir] = list((folder / "runs").iterdir())
        run = load(run_dir / "run.json")
        files[session["camera_id"]] = (
            session, run, rows(run_dir / "frames.csv"), rows(run_dir / "tracks.csv")
        )  # fmt: skip
    return files


def test_two_cameras_share_one_detector_and_each_writes_a_complete_session(clips, tmp_path):
    """R2a-A1."""
    CountingDetector.instances = 0
    detector = CountingDetector()
    statuses = run_two(clips, tmp_path, detector, record=True)
    assert statuses == {"cam1": "ended", "cam2": "ended"}
    assert CountingDetector.instances == 1
    assert len(detector.sources) == 2  # frames of both cameras went through the one detector
    files = camera_files(tmp_path)
    assert set(files) == {"cam1", "cam2"}
    for session, run, frames, _ in files.values():
        validate("session", session)
        validate("run", run)
        assert list(frames[0]) == writer_mod.FRAMES_COLUMNS
        assert session["status"] == "ended" and session["group_id"] == "g1"
        assert run["counts"]["processed"] == len(frames) > 0
        assert session["recording"]["sha256"]
    assert all((p / VIDEO_FILE).stat().st_size > 0 for p in tmp_path.iterdir() if p.is_dir())


def test_the_runs_name_one_group_run_with_every_camera(clips, tmp_path):
    run_two(clips, tmp_path, EvenFrameDetector())
    files = camera_files(tmp_path)
    groups = [run["group"] for _, run, _, _ in files.values()]
    assert groups[0] == groups[1]  # one group run, the same block in every camera's run.json
    group = groups[0]
    assert group["group_id"] == "g1" and tuple(group["params"]) == contract.MATCHER_PARAMS
    assert sorted(group["cameras"], key=lambda c: c["camera_id"]) == [
        {"camera_id": cid, "session_id": s["session_id"], "run_id": r["run_id"]}
        for cid, (s, r, _, _) in sorted(files.items())
    ]


def test_track_ids_never_collide_between_the_cameras_of_a_group(clips, tmp_path):
    # the fake tracker gives local ID 1 to the one person in each camera: both would write 1. The
    # second camera sees a black frame, so the two boxes do not look alike either (R2a 06)
    run_two(clips, tmp_path, EvenFrameDetector(), second=clips["black"])
    files = camera_files(tmp_path)
    ids = {cid: {t["track_id"] for t in tracks} for cid, (_, _, _, tracks) in files.items()}
    assert ids["cam1"] and ids["cam2"]
    assert all(list(tracks[0]) == writer_mod.TRACKS_COLUMNS for *_, tracks in files.values())
    assert not ids["cam1"] & ids["cam2"]
    assert len(ids["cam1"]) == len(ids["cam2"]) == 1  # one local track keeps one group ID
    # not linked yet: every row says so (link column, 0.14.0)
    assert {t["link"] for _, _, _, tracks in files.values() for t in tracks} == {"unshared"}


def test_each_camera_records_its_own_rate_drops_and_app_delay(clips, tmp_path):
    short = write_clip(tmp_path / "short.mp4", [scene(i) for i in range(12)])  # 30 in the other
    run_two(clips, tmp_path / "out", EvenFrameDetector(), second=short)
    files = camera_files(tmp_path / "out")
    assert {cid: run["counts"]["captured"] for cid, (_, run, _, _) in files.items()} == {
        "cam1": 30,
        "cam2": 12,
    }
    for _, run, frames, _ in files.values():
        counts = run["counts"]
        assert counts["captured"] == counts["processed"] + counts["dropped"] + counts["unprocessed"]
        assert len(frames) == counts["processed"]  # each camera's processing rate is in its rows
        for f in frames:
            t_recv, end = float(f["t_recv"]), float(f["t_proc_end"])
            assert float(f["app_delay_ms"]) == pytest.approx((end - t_recv) * 1000, abs=0.01)
        assert int(frames[-1]["dropped_total"]) <= counts["dropped"]


def test_a_camera_id_given_twice_is_refused_before_anything_opens(clips, tmp_path):
    source = FileSource(str(clips["moving"]), realtime=False)
    cameras = [GroupCamera("cam1", source), GroupCamera("cam1", source)]
    with pytest.raises(ValueError, match="twice"):
        run_group("g1", cameras, None, None, tmp_path, HealthConfig(), lambda c, i: None)
    assert not any(tmp_path.iterdir())


def test_ctrl_c_while_running_ends_every_session_interrupted_with_an_event(clips, tmp_path):
    class CtrlC(threading.Event):
        def wait(self, timeout=None):
            raise KeyboardInterrupt

    reported: list[tuple[str, str]] = []
    with pytest.raises(KeyboardInterrupt):
        run_two(
            clips, tmp_path, EvenFrameDetector(), stop=CtrlC(),
            on_event=lambda cid, ev, t0: reported.append((cid, ev.kind)),
        )  # fmt: skip
    files = camera_files(tmp_path)
    for session, run, _, _ in files.values():
        assert session["status"] == "interrupted" and run["counts"] is not None
        assert any(e["kind"] == "interrupted" for e in session["events"])
    assert {("cam1", "interrupted"), ("cam2", "interrupted")} <= set(reported)


def test_a_session_that_cannot_be_written_ends_the_open_ones_with_an_error(
    clips, tmp_path, monkeypatch
):
    start = FileSessionWriter.start
    calls = []

    def second_fails(self, *a, **k):  # the disk fails for the second camera's session
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return start(self, *a, **k)

    monkeypatch.setattr(FileSessionWriter, "start", second_fails)
    with pytest.raises(OSError, match="disk full"):
        run_two(clips, tmp_path, EvenFrameDetector())
    [(session, run, _, _)] = camera_files(tmp_path).values()  # only the first was written
    assert session["status"] == "error" and run["counts"] is not None
    assert any("did not start" in e["detail"] for e in session["events"])


def test_a_source_that_cannot_open_leaves_no_session_and_closes_the_others(clips, tmp_path):
    class Spied(FileSource):
        closed = False

        def open(self):
            info = super().open()  # open() closes first: only a close after it counts
            self.closed = False
            return info

        def close(self):
            self.closed = True
            super().close()

    first = Spied(str(clips["moving"]), realtime=False)
    cameras = [
        GroupCamera("cam1", first),
        GroupCamera("cam2", FileSource(str(tmp_path / "missing.mp4"), realtime=False)),
    ]
    with pytest.raises(SourceOpenError):
        run_group("g1", cameras, None, None, tmp_path / "out", HealthConfig(), lambda c, i: None)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())
    assert first.closed


def test_each_camera_records_with_its_own_calibration_and_a_bad_one_does_not_stop_the_group(
    clips, tmp_path
):
    """Studio passes each camera's saved calibration; one that cannot be used is an event and that
    camera records uncalibrated, while the group starts (spec story 7)."""
    good = calibration_file(tmp_path)  # made for cam1 at the clips' 640x360
    statuses = run_two(
        clips, tmp_path / "out", EvenFrameDetector(), calibrations={"cam1": good, "cam2": good}
    )
    assert statuses == {"cam1": "ended", "cam2": "ended"}
    files = camera_files(tmp_path / "out")
    session, run, _, tracks = files["cam1"]
    assert session["calibration"] and run["calibration"]
    assert any(t["x_m"] for t in tracks)
    session, run, _, tracks = files["cam2"]
    assert session.get("calibration") is None and run.get("calibration") is None
    [problem] = [e for e in session["events"] if "calibration not used" in e["detail"]]
    assert problem["kind"] == "error" and "cam1" in problem["detail"]
    assert all(t["x_m"] == "" for t in tracks)


def test_a_ui_stop_ends_every_session_normally_with_a_stopped_event(clips, tmp_path):
    """Studio's stop (D-049) reaches the group as Ctrl+C with the source "ui": a normal end."""

    class CtrlC(threading.Event):
        def wait(self, timeout=None):
            raise KeyboardInterrupt

    statuses = run_two(clips, tmp_path, EvenFrameDetector(), stop=CtrlC(), ui_stop=lambda: True)
    assert statuses == {"cam1": "ended", "cam2": "ended"}
    for session, _, _, _ in camera_files(tmp_path).values():
        kinds = [e["kind"] for e in session["events"]]
        assert session["status"] == "ended" and kinds.count("stopped") == 1
        assert "interrupted" not in kinds


def test_each_opened_session_is_handed_over_before_its_camera_starts(clips, tmp_path):
    """The hook the group process uses to print each session folder and start its preview."""
    seen = []

    def on_session(camera_id, pipeline):
        seen.append((camera_id, pipeline.writer.dir.name, pipeline.capture.t0))

    run_two(clips, tmp_path, None, on_session=on_session)
    assert [(c, t0) for c, _, t0 in seen] == [("cam1", None), ("cam2", None)]  # not started
    assert {d for _, d, _ in seen} == {p.name for p in tmp_path.iterdir() if p.is_dir()}


# -- cross-camera linking by court position (R2a 05, R2a-A2) -------------------------------------


class ScriptedBoxes:
    """The scripted fake detector: one person at a chosen box per camera (by clip), every frame."""

    threshold, det_size, device = 0.5, 384, "cuda"

    def __init__(self, boxes: dict[str, list[float]]):
        self.boxes = boxes

    def detect(self, frame):
        box = self.boxes[Path(frame.source_id).name]
        return Detections(
            np.array([box], np.float32), np.array([0.9], np.float32), np.array([1], np.int64)
        )


def calibration_for(tmp_path: Path, camera_id: str) -> Path:
    """The example calibration (the same homography) made for `camera_id` at the clips' size."""
    doc = json.loads(calibration_file(tmp_path).read_text(encoding="utf-8"))
    doc["camera_id"] = camera_id
    path = tmp_path / f"calibration_{camera_id}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# 5 s: the two clips are processed at their own pace, so the test does not depend on the timing
TOLERANT = MatcherParams(max_offset_s=5.0)
SAME_PLACE = {"moving.mp4": [10.0, 20.0, 110.0, 220.0], "frozen.mp4": [12.0, 20.0, 112.0, 220.0]}
FAR_APART = {"moving.mp4": [10.0, 20.0, 110.0, 220.0], "frozen.mp4": [400.0, 200.0, 500.0, 340.0]}


def run_calibrated(clips, tmp_path, boxes, matcher_params=TOLERANT):
    out = tmp_path / "out"
    run_two(
        clips, out, ScriptedBoxes(boxes), matcher=CourtMatcher(matcher_params),
        calibrations={c: calibration_for(tmp_path, c) for c in ("cam1", "cam2")},
    )  # fmt: skip
    return camera_files(out)


def test_a_person_at_the_same_court_point_has_one_track_id_in_both_cameras(clips, tmp_path):
    """R2a-A2."""
    files = run_calibrated(clips, tmp_path, SAME_PLACE)
    tracks = {cid: t for cid, (_, _, _, t) in files.items()}
    ids = {cid: {int(t["track_id"]) for t in rows_} for cid, rows_ in tracks.items()}
    assert ids["cam1"] == ids["cam2"] and len(ids["cam1"]) == 1
    # whichever camera is processed first writes unshared rows until the other has been seen, and
    # which one that is depends on the threads; the linking itself does not
    links = {t["link"] for rows_ in tracks.values() for t in rows_}
    assert links == {"unshared", "position"} or links == {"position"}
    for rows_ in tracks.values():
        first_position = next((i for i, t in enumerate(rows_) if t["link"] == "position"), None)
        if first_position is not None:  # a link is not undone while both tracks exist
            assert {t["link"] for t in rows_[first_position:]} == {"position"}


def test_people_at_different_court_points_keep_their_own_track_ids(clips, tmp_path):
    still = MatcherParams(max_offset_s=5.0, max_speed_mps=0.0)  # nobody walks 4 m in the gap
    files = run_calibrated(clips, tmp_path, FAR_APART, still)
    ids = {cid: {t["track_id"] for t in tracks} for cid, (_, _, _, tracks) in files.items()}
    assert not ids["cam1"] & ids["cam2"]
    assert {t["link"] for _, _, _, tracks in files.values() for t in tracks} == {"unshared"}


def test_the_matching_parameters_are_in_every_runs_group_block(clips, tmp_path):
    files = run_calibrated(clips, tmp_path, SAME_PLACE, MatcherParams(match_distance_m=0.7))
    for _, run, _, _ in files.values():
        validate("run", run)
        params = run["group"]["params"]
        assert tuple(params) == contract.MATCHER_PARAMS
        assert params["match_distance_m"] == 0.7 and params["latency_s"] == {}


def test_the_default_matcher_is_recorded_and_a_group_without_detection_records_none(
    clips, tmp_path
):
    run_two(clips, tmp_path / "a", EvenFrameDetector())
    for _, run, _, _ in camera_files(tmp_path / "a").values():
        assert tuple(run["group"]["params"]) == contract.MATCHER_PARAMS
    run_two(clips, tmp_path / "b", None)
    for _, run, _, _ in camera_files(tmp_path / "b").values():
        assert run["group"]["params"] == {}


# -- what a camera reports to the matcher ---------------------------------------------------


class RecordingMatcher:
    def __init__(self):
        self.calls = []

    def update(self, camera_id, t_recv, tracks):
        self.calls.append((camera_id, t_recv, list(tracks)))
        return [GroupTrack(t.local_id, 100 + t.local_id, "unshared") for t in tracks]

    def record_params(self):
        return {}


def camera_tracker(positions, size=(640, 360)):
    matcher = RecordingMatcher()
    tracker = CameraTracker(OneTrackPerDetection(), "cam1", matcher, positions, size)
    return tracker, matcher


def frame_of(width=640, height=360):
    return Frame(0, 12.5, "2026-10-29T00:00:00Z", np.zeros((height, width, 3), np.uint8), "s")


BOX_DETECTION = Detections(
    np.array([[10.0, 20.0, 110.0, 220.0]], np.float32),
    np.array([0.9], np.float32),
    np.array([1], np.int64),
)


def test_a_camera_reports_the_court_position_of_the_box_bottom_centre_and_gets_group_ids_back():
    tracker, matcher = camera_tracker(lambda x, y: (x / 10, y / 10))
    [obs] = tracker.update(BOX_DETECTION, frame_of())
    [(camera_id, t_recv, [track])] = matcher.calls
    assert (camera_id, t_recv, track.local_id, track.xy) == ("cam1", 12.5, 1, (6.0, 22.0))
    assert (obs.track_id, obs.link) == (101, "unshared")


def test_a_camera_reports_the_appearance_of_each_box_with_or_without_a_position():
    frame = frame_of()
    frame.image[:, :60] = (0, 0, 255)  # red on the left of the frame, black elsewhere
    for positions in (lambda x, y: (1.0, 1.0), None):
        tracker, matcher = camera_tracker(positions)
        tracker.update(BOX_DETECTION, frame)
        [track] = matcher.calls[0][2]
        expected = describe(frame.image, (10.0, 20.0, 110.0, 220.0))
        assert track.appearance.height == pytest.approx(200 / 360)
        assert colour_distance(track.appearance, expected) == pytest.approx(0.0, abs=1e-9)


def test_a_camera_with_no_position_for_a_track_still_reports_it_and_a_silent_frame_too():
    for positions, frame in (
        (None, frame_of()),  # not calibrated
        (
            lambda x, y: (1.0, 1.0),
            frame_of(320, 180),
        ),  # a frame of another size than the calibration
        (lambda x, y: None, frame_of()),  # a point that cannot be projected
        (lambda x, y: 1 / 0, frame_of()),  # a projection that fails
    ):
        tracker, matcher = camera_tracker(positions)
        tracker.update(BOX_DETECTION, frame)
        [track] = matcher.calls[0][2]
        assert (track.local_id, track.xy) == (1, None)
    tracker, matcher = camera_tracker(lambda x, y: (1.0, 1.0))
    assert tracker.update(NO_DETECTIONS, frame_of()) == []
    assert matcher.calls == [("cam1", 12.5, [])]  # the camera reported: nothing in view


# -- the appearance fallback (R2a 06) -------------------------------------------------------

# rows 150 to 350, columns 200 to 300 are background grey in every frame of the moving and the
# frozen clip, so a box there looks the same in both cameras whenever each is processed
GREY_BOX = [200.0, 150.0, 300.0, 350.0]


def appearance_events(session):
    return [e for e in session["events"] if e["kind"] == "appearance_only"]


def test_an_uncalibrated_camera_links_by_appearance_and_says_so(clips, tmp_path):
    """R2a-A3."""
    out = tmp_path / "out"
    run_two(
        clips, out, ScriptedBoxes({"moving.mp4": GREY_BOX, "frozen.mp4": GREY_BOX}),
        matcher=CourtMatcher(TOLERANT), calibrations={"cam1": calibration_for(tmp_path, "cam1")},
    )  # fmt: skip
    files = camera_files(out)
    tracks = {cid: t for cid, (_, _, _, t) in files.items()}
    assert all(t["x_m"] for t in tracks["cam1"]) and not any(t["x_m"] for t in tracks["cam2"])
    ids = {cid: {int(t["track_id"]) for t in rows_} for cid, rows_ in tracks.items()}
    assert ids["cam1"] == ids["cam2"] and len(ids["cam1"]) == 1
    links = {t["link"] for rows_ in tracks.values() for t in rows_}
    assert links == {"unshared", "appearance"} or links == {"appearance"}
    for session, run, _, _ in files.values():
        validate("session", session)
        validate("run", run)
    [event] = appearance_events(files["cam2"][0])
    assert event["t_mono"] is None and event["detail"].startswith("no valid calibration")
    assert not appearance_events(files["cam1"][0])  # calibrated: it links by position too


def test_two_uncalibrated_cameras_with_the_same_pixel_box_but_other_clothes_stay_apart(
    clips, tmp_path
):
    """No link from pixel position alone: the same box, over grey in one camera and black in the
    other."""
    run_two(
        clips, tmp_path, ScriptedBoxes({"moving.mp4": GREY_BOX, "black.mp4": GREY_BOX}),
        second=clips["black"], matcher=CourtMatcher(TOLERANT),
    )  # fmt: skip
    files = camera_files(tmp_path)
    ids = {cid: {t["track_id"] for t in tracks} for cid, (_, _, _, tracks) in files.items()}
    assert ids["cam1"] and ids["cam2"] and not ids["cam1"] & ids["cam2"]
    assert {t["link"] for _, _, _, tracks in files.values() for t in tracks} == {"unshared"}
    assert all(len(appearance_events(s)) == 1 for s, _, _, _ in files.values())


def test_no_appearance_event_without_a_matcher_or_with_calibrated_cameras(clips, tmp_path):
    run_two(clips, tmp_path / "a", None)  # no detector: nothing is linked at all
    files = run_calibrated(clips, tmp_path, SAME_PLACE)
    for out_files in (camera_files(tmp_path / "a"), files):
        assert not any(appearance_events(s) for s, _, _, _ in out_files.values())
