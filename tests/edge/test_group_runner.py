"""The group runner (R2a 03, seam A, ADR 0007): the cameras of a group in one process with one
detector. Driven in-process with synthetic clips and a scripted fake detector; the tests read the
session folders back as a reader of the files would. No camera, weights or network."""

import threading
from pathlib import Path

import pytest

from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import FileSource, SourceOpenError
from services.edge.contract import VIDEO_FILE
from services.edge.group_runner import GroupCamera, run_group
from services.edge.main import parse_args, run_meta
from services.edge.session import writer as writer_mod
from services.edge.session.writer import FileSessionWriter
from tests.edge.test_session import (
    EvenFrameDetector,
    OneTrackPerDetection,
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
    clips, out: Path, detector, record=False, second=None, stop=None, on_event=None
) -> dict[str, str]:
    args = parse_args(["--source", "unused"])  # the CLI's defaults, as the launcher passes them
    config = HealthConfig()
    cameras = [
        GroupCamera("cam1", FileSource(str(clips["moving"]), realtime=False)),
        GroupCamera("cam2", FileSource(str(second or clips["frozen"]), realtime=False)),
    ]
    return run_group(
        "g1",
        cameras,
        detector,
        OneTrackPerDetection,
        out,
        config,
        lambda info: run_meta(args, info, config, detector, OneTrackPerDetection(), None),
        record=record,
        stop=stop,
        on_event=on_event,
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
    assert group["group_id"] == "g1" and group["params"] == {}
    assert sorted(group["cameras"], key=lambda c: c["camera_id"]) == [
        {"camera_id": cid, "session_id": s["session_id"], "run_id": r["run_id"]}
        for cid, (s, r, _, _) in sorted(files.items())
    ]


def test_track_ids_never_collide_between_the_cameras_of_a_group(clips, tmp_path):
    # the fake tracker gives local ID 1 to the one person in each camera: both would write 1
    run_two(clips, tmp_path, EvenFrameDetector())
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
        run_group("g1", cameras, None, None, tmp_path, HealthConfig(), lambda i: None)
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
        run_group("g1", cameras, None, None, tmp_path / "out", HealthConfig(), lambda i: None)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())
    assert first.closed
