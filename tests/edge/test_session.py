"""PHASE_03 A1-A5 and the session writer. Fixture clips and fakes: no camera, no weights."""

import _thread
import csv
import json
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from services.edge import main as cli
from services.edge.capture.health import HealthConfig
from services.edge.capture.types import SourceInfo
from services.edge.main import EXIT_CAPTURE_ERROR, EXIT_INTERRUPTED, EXIT_OPEN_FAILED
from services.edge.perception.loop import NO_DETECTIONS
from services.edge.perception.types import Detections, TrackObs
from services.edge.session import writer as writer_mod
from services.edge.session.types import (
    FrameRecord,
    RunCounts,
    RunMeta,
    SessionEvent,
    SessionMeta,
)
from services.edge.session.writer import FileSessionWriter, device_id, redact

ROOT = Path(__file__).resolve().parents[2]


def validate(name: str, doc: dict) -> None:
    schema = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(doc)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def session_files(out: Path) -> tuple[dict, dict, list[dict], list[dict]]:
    [folder] = [p for p in out.iterdir() if p.is_dir()]
    session = load(folder / "session.json")
    [run_dir] = list((folder / "runs").iterdir())
    assert run_dir.name == session["runs"][0]
    run = load(run_dir / "run.json")
    return session, run, rows(run_dir / "frames.csv"), rows(run_dir / "tracks.csv")


class EvenFrameDetector:
    """One person on even seq, none on odd: both kinds of frames must get a row."""

    threshold, det_size, device = 0.5, 384, "cuda"  # "cuda" must be written as cuda:0

    def __init__(self, fail_at: int | None = None):
        self.fail_at = fail_at

    def detect(self, frame):
        if frame.seq == self.fail_at:
            raise RuntimeError("inference exploded")
        if frame.seq % 2:
            return NO_DETECTIONS
        box = np.array([[10.0, 20.0, 110.0, 220.0]], np.float32)
        return Detections(box, np.array([0.9], np.float32), np.array([1], np.int64))


class OneTrackPerDetection:
    params = {"lost_track_buffer": 30}

    def update(self, dets, frame):
        return [
            TrackObs(i + 1, tuple(float(v) for v in box), float(c), None)
            for i, (box, c) in enumerate(zip(dets.xyxy, dets.confidence, strict=True))
        ]


def run_main(monkeypatch, out: Path, *args: str, detector=None) -> int:
    if detector is not None:
        monkeypatch.setattr(cli, "load_perception", lambda a, d: (detector, OneTrackPerDetection()))
    return cli.main([*args, "--out", str(out)])


def test_gpu_name_is_printed_and_recorded(monkeypatch, tmp_path, clips, capsys):
    """--device auto on a CUDA machine: the GPU name is on the console and in run.json."""
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda index: "Fake RTX 9000")
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        detector=EvenFrameDetector(),
    )  # fmt: skip
    assert code == 0
    assert "device: cuda:0 (Fake RTX 9000)" in capsys.readouterr().out
    _, run, _, _ = session_files(out)
    validate("run", run)
    assert run["runtime"]["device"] == "cuda:0" and run["runtime"]["gpu"] == "Fake RTX 9000"


def test_fixture_clip_produces_valid_files(monkeypatch, tmp_path, clips):
    """A1, A2: all files, valid against the schemas; one row per processed frame including
    0-detection frames; seq increasing; counts add up."""
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        detector=EvenFrameDetector(),
    )  # fmt: skip
    assert code == 0
    session, run, frames, tracks = session_files(out)
    validate("session", session)
    validate("run", run)
    assert session["status"] == "ended" and session["ended_at"] and session["events"] == []
    assert session["device_id"] == (out / "device_id").read_text().strip()
    assert run["t0_wall"] and run["ended_at"]
    assert run["runtime"]["device"] == "cuda:0"
    assert run["detector"]["det_size"] == 384 and run["tracker"]["package"] == "trackers"
    assert run["health"]["dark_secs"] == 1.0
    c = run["counts"]
    assert c["captured"] == 30 == c["processed"] + c["dropped"] + c["unprocessed"]
    assert c["rec_dropped"] is None
    assert len(frames) == c["processed"] > 0
    seqs = [int(r["seq"]) for r in frames]
    assert seqs == sorted(set(seqs))
    assert list(frames[0]) == writer_mod.FRAMES_COLUMNS
    assert {r["n_detections"] for r in frames} == {"0", "1"}  # 0-detection frames logged
    for r in frames:
        t_recv, start, end = float(r["t_recv"]), float(r["t_proc_start"]), float(r["t_proc_end"])
        assert 0 <= t_recv <= start <= end
        assert float(r["app_delay_ms"]) == pytest.approx((end - t_recv) * 1000, abs=0.01)
    assert int(frames[-1]["dropped_total"]) <= c["dropped"]
    even = [r["seq"] for r in frames if r["n_detections"] == "1"]
    assert [r["seq"] for r in tracks] == even
    assert list(tracks[0]) == writer_mod.TRACKS_COLUMNS
    assert tracks[0]["x1"] == "10.00" and tracks[0]["confidence"] == "0.9000"
    assert tracks[0]["state"] == "" and tracks[0]["athlete_id"] == ""
    assert tracks[0]["x_m"] == tracks[0]["y_m"] == ""
    assert tracks[0]["position_method"] == tracks[0]["in_court"] == ""


def test_calibrated_run_writes_metre_positions_and_provenance(monkeypatch, tmp_path, clips):
    class TwoPersonDetector(EvenFrameDetector):
        def detect(self, frame):
            if frame.seq % 2:
                return NO_DETECTIONS
            boxes = np.array([[10.0, 20.0, 110.0, 220.0], [10.0, 20.0, 110.0, 100.0]], np.float32)
            return Detections(boxes, np.array([0.9, 0.9], np.float32), np.array([1, 2]))

    calibration = load(ROOT / "tests/fixtures/contracts/calibration.example.json")
    calibration["camera_id"] = "cam1"
    calibration["image_size"] = {"width": 640, "height": 360}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration), encoding="utf-8")
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch,
        out,
        "--source",
        str(clips["moving"]),
        "--link",
        "file",
        "--camera-id",
        "cam1",
        "--calibration",
        str(path),
        detector=TwoPersonDetector(),
    )
    assert code == 0
    session, run, _, tracks = session_files(out)
    validate("session", session)
    validate("run", run)
    assert session["calibration"]["calibration_id"] == calibration["calibration_id"]
    assert session["calibration"]["court"] == {
        "type": "custom", "length_m": 3.0, "width_m": 2.0
    }
    assert run["calibration"]["check_error_m"] == calibration["errors"]["check_mean_m"]
    assert run["calibration"]["court"]["type"] == "custom"
    assert tracks[0]["x_m"] == "0.6000" and tracks[0]["y_m"] == "2.2000"
    assert tracks[0]["calibration_id"] == calibration["calibration_id"]
    assert tracks[0]["position_method"] == "box_bottom_center"
    assert tracks[0]["in_court"] == "false"
    assert tracks[1]["in_court"] == "true"


def test_calibration_image_size_mismatch_is_refused_before_session(
    monkeypatch, tmp_path, clips, capsys
):
    calibration = load(ROOT / "tests/fixtures/contracts/calibration.example.json")
    calibration["camera_id"] = "cam1"
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration), encoding="utf-8")
    out = tmp_path / "sessions"
    result = run_main(
        monkeypatch,
        out,
        "--source",
        str(clips["moving"]),
        "--link",
        "file",
        "--camera-id",
        "cam1",
        "--calibration",
        str(path),
        "--no-detect",
    )
    assert result == EXIT_CAPTURE_ERROR
    assert (
        "calibration image size 640x480 differs from capture size 640x360"
        in capsys.readouterr().err
    )
    assert not out.exists()


def test_calibration_requires_matching_camera_id(monkeypatch, tmp_path, clips, capsys):
    calibration = load(ROOT / "tests/fixtures/contracts/calibration.example.json")
    calibration["camera_id"] = "cam1"
    calibration["image_size"] = {"width": 640, "height": 360}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration), encoding="utf-8")

    for camera_args, message in [
        ([], "--camera-id is required"),
        (["--camera-id", "cam2"], "calibration is for camera 'cam1', not 'cam2'"),
    ]:
        out = tmp_path / ("sessions_" + str(len(camera_args)))
        result = run_main(
            monkeypatch,
            out,
            "--source",
            str(clips["moving"]),
            "--link",
            "file",
            *camera_args,
            "--calibration",
            str(path),
            "--no-detect",
        )
        assert result == EXIT_CAPTURE_ERROR
        assert message in capsys.readouterr().err
        assert not out.exists()


def test_run_metadata_records_effective_tracker_parameters():
    class Detector:
        threshold = 0.5
        det_size = 384
        device = "cpu"

    class Tracker:
        params = {
            "lost_track_buffer": 120,
            "frame_rate": 30.0,
            "track_activation_threshold": 0.55,
            "minimum_consecutive_frames": 3,
            "minimum_iou_threshold": 0.1,
            "high_conf_det_threshold": 0.6,
        }

    args = cli.parse_args(
        [
            "--source",
            "0",
            "--track-lost-secs",
            "4",
            "--track-activation",
            "0.55",
            "--track-min-frames",
            "3",
        ]
    )
    info = SourceInfo("camera", "0", 1280, 720, 30.0, "builtin")
    run = cli.run_meta(args, info, HealthConfig(), Detector(), Tracker(), None)

    assert run.tracker["params"] == Tracker.params


def test_no_detect_leaves_detection_columns_empty(monkeypatch, tmp_path, clips):
    out = tmp_path / "sessions"
    assert run_main(monkeypatch, out, "--source", str(clips["moving"]), "--no-detect") == 0
    session, run, frames, tracks = session_files(out)
    validate("session", session)
    validate("run", run)
    assert run["detector"] is None and run["tracker"] is None and run["runtime"]["device"] is None
    assert frames and all(r["n_detections"] == "" == r["n_tracks"] for r in frames)
    assert tracks == []


def test_events_are_logged_relative_to_t0(monkeypatch, tmp_path, clips):
    """Capture-thread events reach session.json with t_mono in s since t0 (D-011)."""
    out = tmp_path / "sessions"
    assert run_main(monkeypatch, out, "--source", str(clips["black"]), "--no-detect") == 0
    session, run, _, _ = session_files(out)
    validate("session", session)
    [ev] = session["events"]
    assert ev["kind"] == "dark_frames"
    assert 1.0 <= ev["t_mono"] < 3.0  # dark_secs 1.0; the clip lasts 2 s


def test_exception_mid_run_leaves_readable_files_and_status_error(monkeypatch, tmp_path, clips):
    """A3: the detector fails on frame 10. CSVs readable, status error, failure an event."""
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        detector=EvenFrameDetector(fail_at=10),
    )  # fmt: skip
    assert code == EXIT_CAPTURE_ERROR
    session, run, frames, tracks = session_files(out)
    validate("session", session)
    validate("run", run)
    assert session["status"] == "error" and session["ended_at"]
    [ev] = session["events"]
    assert ev["kind"] == "error" and "inference exploded" in ev["detail"]
    assert ev["t_mono"] > 0
    assert 0 < len(frames) == run["counts"]["processed"]
    assert all(int(r["seq"]) < 10 for r in frames)
    assert run["counts"]["unprocessed"] >= 1


def test_ctrl_c_is_interrupted_with_end_time(monkeypatch, tmp_path, clips):
    """A4: KeyboardInterrupt in the main thread, as Ctrl+C delivers it."""
    out = tmp_path / "sessions"
    timer = threading.Timer(0.5, _thread.interrupt_main)
    timer.start()
    code = run_main(monkeypatch, out, "--source", str(clips["moving"]), "--no-detect")
    timer.join()
    assert code == EXIT_INTERRUPTED
    session, run, frames, _ = session_files(out)
    validate("session", session)
    validate("run", run)
    assert session["status"] == "interrupted" and session["ended_at"] and run["ended_at"]
    [ev] = session["events"]
    assert ev["kind"] == "interrupted" and ev["t_mono"] > 0
    c = run["counts"]
    assert 0 < c["captured"] < 30
    assert c["captured"] == c["processed"] + c["dropped"] + c["unprocessed"]
    assert len(frames) == c["processed"]


def test_link_contradicting_the_source_is_rejected(monkeypatch, tmp_path, clips, capsys):
    out = tmp_path / "sessions"
    code = run_main(monkeypatch, out, "--source", str(clips["moving"]), "--link", "usb")
    assert code == EXIT_OPEN_FAILED
    assert "--link usb contradicts a file source" in capsys.readouterr().err
    assert not out.exists()


def test_camera_and_group_ids_reach_session_json_and_the_folder_name(monkeypatch, tmp_path, clips):
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--no-detect",
        "--camera-id", "cam2", "--group-id", "g-2026_10_13",
    )  # fmt: skip
    assert code == 0
    [folder] = [p for p in out.iterdir() if p.is_dir()]
    session, _, _, _ = session_files(out)
    validate("session", session)
    assert session["camera_id"] == "cam2" and session["group_id"] == "g-2026_10_13"
    assert folder.name == f"cam2_{session['session_id']}"


def test_without_ids_the_folder_is_the_session_id_and_both_ids_are_null(
    monkeypatch, tmp_path, clips
):
    out = tmp_path / "sessions"
    assert run_main(monkeypatch, out, "--source", str(clips["moving"]), "--no-detect") == 0
    [folder] = [p for p in out.iterdir() if p.is_dir()]
    session, _, _, _ = session_files(out)
    validate("session", session)
    assert session["camera_id"] is None and session["group_id"] is None
    assert folder.name == session["session_id"]


@pytest.mark.parametrize("flag", ["--camera-id", "--group-id"])
@pytest.mark.parametrize("bad", ["../evil", "a b", "a/b", "", "x" * 65])
def test_unsafe_ids_are_rejected_by_the_cli(tmp_path, capsys, flag, bad):
    """An id becomes part of a folder name: argparse refuses it before anything runs."""
    with pytest.raises(SystemExit) as e:
        cli.main(["--source", "0", "--out", str(tmp_path), flag, bad])
    assert e.value.code == 2 and "must match" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a b", "", "x" * 33])
def test_writer_refuses_an_unsafe_camera_id(tmp_path, bad):
    with pytest.raises(ValueError, match="camera_id"):
        FileSessionWriter(tmp_path).start(replace(meta(), camera_id=bad), run_meta())
    with pytest.raises(ValueError, match="group_id"):
        FileSessionWriter(tmp_path).start(replace(meta(), group_id="a b"), run_meta())
    assert not any(tmp_path.iterdir())  # nothing was created


def test_preview_window_is_named_after_the_camera(monkeypatch, tmp_path, clips):
    titles = []
    monkeypatch.setattr(cli, "run_preview", lambda *a: titles.append(a[-1]))
    for extra in (["--camera-id", "cam7"], []):
        run_main(monkeypatch, tmp_path / "s", "--source", str(clips["moving"]), "--no-detect",
                 "--preview", *extra)  # fmt: skip
    assert titles == ["Pointr cam7 (q to quit)", None]  # None: the default title


def test_report_is_written_when_the_session_ends_and_printed(monkeypatch, tmp_path, clips, capsys):
    """D-023: report.json beside run.json, valid, with the run's own numbers; summary on stdout."""
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        detector=EvenFrameDetector(),
    )  # fmt: skip
    assert code == 0
    session, run, frames, _ = session_files(out)
    [report_path] = out.glob("*/runs/*/report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate("report", report)
    assert report["run_id"] == run["run_id"] and report["session_id"] == session["session_id"]
    assert report["session"]["n_processed"] == len(frames) == run["counts"]["processed"]
    with_people = sum(r["n_detections"] == "1" for r in frames)
    assert report["session"]["coverage"]["value"] == pytest.approx(100 * with_people / len(frames))
    assert report["session"]["n_tracks"] == 1  # OneTrackPerDetection: every person is track 1
    text = capsys.readouterr().out
    assert "report " in text and "caveats:" in text and "positions in px" in text


def test_a_report_failure_never_changes_the_session(monkeypatch, tmp_path, clips, capsys):
    out = tmp_path / "sessions"

    def boom(run_dir):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "write_report", boom)
    assert run_main(monkeypatch, out, "--source", str(clips["moving"]), "--no-detect") == 0
    session, _, _, _ = session_files(out)
    assert session["status"] == "ended"
    assert "warning: report not written: RuntimeError('boom')" in capsys.readouterr().err
    assert not list(out.glob("*/runs/*/report.json"))


def test_report_of_a_no_detect_session(monkeypatch, tmp_path, clips):
    out = tmp_path / "sessions"
    assert run_main(monkeypatch, out, "--source", str(clips["moving"]), "--no-detect") == 0
    [report_path] = out.glob("*/runs/*/report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate("report", report)
    assert report["session"]["detection"] is False
    assert report["session"]["coverage"]["value"] is None and report["tracks"] == []


# -- the writer on its own -------------------------------------------------------------------


def meta(ref: str = "fake", kind: str = "file", link: str | None = "file") -> SessionMeta:
    info = SourceInfo(kind, ref, 8, 8, None, link)
    return SessionMeta(str(uuid.uuid4()), str(uuid.uuid4()), "2026-10-13T12:00:00Z", info, False)


def run_meta(ref: str = "fake", kind: str = "file") -> RunMeta:
    packages = {"opencv": "5.0.0", "numpy": "2.0.0", "torch": None, "supervision": None}
    return RunMeta(
        str(uuid.uuid4()),
        "live",
        {"kind": kind, "ref": ref, "sha256": None, "requested_width": None,
         "requested_height": None},
        None,
        None,
        {"lost_reads": 30, "lost_secs": 2.0, "frozen_diff": 0.5, "frozen_secs": 2.0,
         "dark_level": 20.0, "dark_secs": 1.0},
        {"python": "3.11.9", "platform": "test", "device": None, "gpu": None,
         "packages": packages},
        "2026-10-13T12:00:00Z",
    )  # fmt: skip


def rec(seq: int) -> FrameRecord:
    return FrameRecord(seq, 0.1 * seq, 0.1 * seq, 0.1 * seq + 0.05, 0, 0, 0)


COUNTS = RunCounts(3, 3, 0, 0)


def started(out: Path, **kw) -> tuple[FileSessionWriter, Path]:
    w = FileSessionWriter(out, **kw)
    m, r = meta(), run_meta()
    w.start(m, r)
    w.set_t0(time.perf_counter(), "2026-10-13T12:00:01Z")
    return w, w.dir / "runs" / r.run_id


def test_two_runs_never_share_a_folder(tmp_path):
    """A5: new IDs give new folders; reusing IDs is refused, never written into."""
    w1, run1 = started(tmp_path)
    w2, run2 = started(tmp_path)
    assert w1.dir != w2.dir and run1 != run2
    w1.close("ended", COUNTS)
    w2.close("ended", COUNTS)
    m, r = meta(), run_meta()
    FileSessionWriter(tmp_path).start(m, r)
    with pytest.raises(FileExistsError):
        FileSessionWriter(tmp_path).start(m, r)


def test_files_are_readable_while_running(tmp_path):
    """A crash at any moment leaves readable CSVs and a valid session.json (running)."""
    w, run_dir = started(tmp_path)
    for seq in range(5):
        w.frame(rec(seq))
    w.event(SessionEvent("2026-10-13T12:00:02Z", 1.0, "source_lost", "test"))
    time.sleep(1.2)  # flushed at least once per second
    assert [r["seq"] for r in rows(run_dir / "frames.csv")] == ["0", "1", "2", "3", "4"]
    session, run = load(w.dir / "session.json"), load(run_dir / "run.json")
    validate("session", session)
    validate("run", run)
    assert session["status"] == "running" and session["ended_at"] is None
    assert [e["kind"] for e in session["events"]] == ["source_lost"]
    assert run["counts"] is None and run["t0_wall"] == "2026-10-13T12:00:01Z"
    w.close("ended", COUNTS)
    assert load(w.dir / "session.json")["status"] == "ended"


def test_writer_failure_ends_as_error(tmp_path, monkeypatch, capsys):
    """Disk full or similar on the writer thread: producers do not raise, the session closes
    with status error and the failure as an event."""
    w, run_dir = started(tmp_path)

    def broken(item):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(w, "_handle", broken)
    w.frame(rec(0))
    w._thread.join(2)
    w.frame(rec(1))  # after the thread died: counted, not raised
    w.close("ended", COUNTS)
    assert w.status == "error"
    session = load(w.dir / "session.json")
    validate("session", session)
    assert session["status"] == "error"
    assert "No space left" in session["events"][-1]["detail"]
    assert "items not written" in session["events"][-1]["detail"]
    assert "session writer stopped" in capsys.readouterr().err
    assert rows(run_dir / "frames.csv") == []  # header still readable


def test_full_queue_is_an_event_and_loses_no_rows(tmp_path, monkeypatch):
    w, run_dir = started(tmp_path, maxsize=2)
    real = w._handle

    def slow(item):
        time.sleep(0.02)
        return real(item)

    monkeypatch.setattr(w, "_handle", slow)
    for seq in range(20):
        w.frame(rec(seq))
    w.close("ended", COUNTS)
    assert len(rows(run_dir / "frames.csv")) == 20
    session = load(w.dir / "session.json")
    validate("session", session)
    backlog = [e for e in session["events"] if e["kind"] == "writer_backlog"]
    assert backlog and backlog[0]["t_mono"] is not None


def test_second_ctrl_c_during_the_final_write(tmp_path, monkeypatch):
    """The final write happens on the writer thread; Ctrl+C in the main thread meanwhile
    must neither escape close() nor cut the write short."""
    w, _ = started(tmp_path)
    real = writer_mod.write_json

    def slow(path, doc):
        time.sleep(0.3)
        real(path, doc)

    monkeypatch.setattr(writer_mod, "write_json", slow)
    timer = threading.Timer(0.1, _thread.interrupt_main)
    timer.start()
    w.close("interrupted", COUNTS)
    timer.join()
    assert w.status == "interrupted"
    assert load(w.dir / "session.json")["status"] == "interrupted"


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("rtsp://user:secret@10.0.0.5:554/live", "rtsp://10.0.0.5:554/live"),
        ("http://admin@192.168.0.7:8080/video", "http://192.168.0.7:8080/video"),
        ("http://192.168.0.7:8080/video", "http://192.168.0.7:8080/video"),
        ("1", "1"),
        (r"C:\clips\me@gym.mp4", r"C:\clips\me@gym.mp4"),
    ],
)
def test_redact(ref, expected):
    assert redact(ref) == expected


def test_stream_credentials_never_reach_the_files(tmp_path):
    url = "rtsp://user:secret@10.0.0.5:554/live"
    w = FileSessionWriter(tmp_path)
    r = run_meta(url, "stream")
    w.start(meta(url, "stream", "wifi"), r)
    w.close("ended", COUNTS)
    for path in w.dir.rglob("*.json"):
        assert "secret" not in path.read_text() and "user" not in path.read_text(), path


def test_device_id_is_kept_and_repaired(tmp_path):
    first = device_id(tmp_path)
    assert device_id(tmp_path) == first and uuid.UUID(first).version == 4
    (tmp_path / "device_id").write_text("garbage")
    assert device_id(tmp_path) != first


def test_a_failed_session_json_rewrite_does_not_stop_the_rows(tmp_path, monkeypatch):
    """session.json held by another program for a moment: rows keep coming, retried later."""
    w, run_dir = started(tmp_path)
    real, fails = writer_mod.write_json, []

    def locked_once(path, doc):
        if path.name == "session.json" and not fails:
            fails.append(path)
            raise PermissionError(13, "held by another process")
        real(path, doc)

    monkeypatch.setattr(writer_mod, "write_json", locked_once)
    w.event(SessionEvent("2026-10-13T12:00:02Z", 1.0, "source_lost", "test"))
    time.sleep(0.8)  # first rewrite attempt fails
    for seq in range(3):
        w.frame(rec(seq))
    time.sleep(0.8)  # retried
    assert fails and w.error is None
    assert len(rows(run_dir / "frames.csv")) == 3
    assert load(w.dir / "session.json")["events"][0]["kind"] == "source_lost"
    w.close("ended", COUNTS)
    assert w.status == "ended"


def test_a_dead_writer_ends_the_run(monkeypatch, tmp_path, clips):
    """Nothing is saved any more: the run stops with status error instead of running on."""
    out = tmp_path / "sessions"
    real = FileSessionWriter._handle

    def disk_full(self, item):
        if item[0] == "frame" and item[1].seq >= 3:
            raise OSError(28, "No space left on device")
        return real(self, item)

    monkeypatch.setattr(FileSessionWriter, "_handle", disk_full)
    t = time.perf_counter()
    code = run_main(monkeypatch, out, "--source", str(clips["moving"]), "--no-detect")
    assert code == EXIT_CAPTURE_ERROR
    assert time.perf_counter() - t < 1.8  # the clip plays 2 s: the run ended early
    session, run, frames, _ = session_files(out)
    validate("session", session)
    assert session["status"] == "error"
    assert "No space left" in session["events"][-1]["detail"]
    assert len(frames) == 3


def test_ctrl_c_pressed_again_during_shutdown_still_saves(monkeypatch, tmp_path, clips):
    """Ctrl+C, then more presses while capture is stopping: the session is still saved."""
    out = tmp_path / "sessions"
    from services.edge.capture.capture import Capture

    real_stop = Capture.stop

    def slow_stop(self, timeout=8.0):
        for _ in range(3):  # three more presses while shutting down
            _thread.interrupt_main()
            time.sleep(0.05)
        return real_stop(self, timeout)

    monkeypatch.setattr(Capture, "stop", slow_stop)
    timer = threading.Timer(0.5, _thread.interrupt_main)
    timer.start()
    code = run_main(monkeypatch, out, "--source", str(clips["moving"]), "--no-detect")
    timer.join()
    assert code == EXIT_INTERRUPTED
    session, run, frames, _ = session_files(out)
    validate("session", session)
    validate("run", run)
    assert session["status"] == "interrupted" and session["ended_at"]
    assert len(frames) == run["counts"]["processed"]
