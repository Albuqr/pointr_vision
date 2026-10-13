"""PHASE_03 A1-A5 and the session writer. Fixture clips and fakes: no camera, no weights."""

import _thread
import csv
import json
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from services.edge import main as cli
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
        monkeypatch.setattr(cli, "load_perception", lambda a: (detector, OneTrackPerDetection()))
    return cli.main([*args, "--out", str(out)])


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
        {"python": "3.11.9", "platform": "test", "device": None, "packages": packages},
        "2026-10-13T12:00:00Z",
    )  # fmt: skip


def rec(seq: int) -> FrameRecord:
    return FrameRecord(seq, 0.1 * seq, 0.1 * seq, 0.1 * seq + 0.05, 0, 0, 0)


COUNTS = RunCounts(3, 3, 0, 0)


def started(out: Path, **kw) -> tuple[FileSessionWriter, Path]:
    w = FileSessionWriter(out, **kw)
    m, r = meta(), run_meta()
    w.start(m, r)
    w.set_t0(time.monotonic(), "2026-10-13T12:00:01Z")
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
