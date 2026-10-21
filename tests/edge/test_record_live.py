"""Phase 04 A1 end to end: a live run records video.mkv beside its CSVs (RF08 video, RF09).

Subprocess runs use --no-detect: no model, no weights. The synthetic clip plays as a live source."""

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_cli(out: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "services.edge.main", "--no-detect", "--out", str(out), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def only_session(out: Path) -> Path:
    (folder,) = [p for p in out.iterdir() if p.is_dir()]
    return folder


def video_frame_count(path: Path) -> int:
    cap = cv2.VideoCapture(str(path))
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    return n


def read_run(folder: Path) -> tuple[dict, list[dict]]:
    (run_dir,) = (folder / "runs").iterdir()
    run = json.loads((run_dir / "run.json").read_text())
    with open(run_dir / "frames.csv", newline="") as f:
        return run, list(csv.DictReader(f))


def test_A1_run_records_video_with_every_captured_frame(clips, tmp_path):
    result = run_cli(tmp_path, "--source", str(clips["moving"]), "--link", "file")
    assert result.returncode == 0, result.stderr
    folder = only_session(tmp_path)
    run, _ = read_run(folder)
    counts = run["counts"]
    assert counts["rec_dropped"] == 0
    assert video_frame_count(folder / "video.mkv") == counts["captured"] - counts["rec_dropped"]


def test_A5_session_json_holds_the_video_hash(clips, tmp_path):
    run_cli(tmp_path, "--source", str(clips["moving"]), "--link", "file")
    folder = only_session(tmp_path)
    recording = json.loads((folder / "session.json").read_text())["recording"]
    assert recording["enabled"] is True and recording["path"] == "video.mkv"
    assert recording["sha256"] == hashlib.sha256((folder / "video.mkv").read_bytes()).hexdigest()


def test_frames_csv_t_video_is_the_position_in_the_video(clips, tmp_path):
    run_cli(tmp_path, "--source", str(clips["moving"]), "--link", "file")
    run, rows = read_run(only_session(tmp_path))
    assert rows, "no processed frames"
    fps = cv2.VideoCapture(str(clips["moving"])).get(cv2.CAP_PROP_FPS)
    for r in rows:
        # every frame of this clip is recorded, so seq n is frame n of the video
        assert float(r["t_video"]) == pytest.approx(int(r["seq"]) / fps, abs=1e-4)


def test_no_record_leaves_no_video(clips, tmp_path):
    result = run_cli(tmp_path, "--source", str(clips["moving"]), "--link", "file", "--no-record")
    assert result.returncode == 0, result.stderr
    folder = only_session(tmp_path)
    run, rows = read_run(folder)
    session = json.loads((folder / "session.json").read_text())
    assert not (folder / "video.mkv").exists()
    assert session["recording"] == {"enabled": False, "path": None, "sha256": None, "locked": False}
    assert run["counts"]["rec_dropped"] is None
    assert all(r["t_video"] == "" for r in rows)


def validate(name: str, doc: dict) -> None:
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(doc)


def test_live_files_match_the_schemas(clips, tmp_path):
    run_cli(tmp_path, "--source", str(clips["moving"]), "--link", "file")
    folder = only_session(tmp_path)
    validate("session", json.loads((folder / "session.json").read_text()))
    (run_dir,) = (folder / "runs").iterdir()
    validate("run", json.loads((run_dir / "run.json").read_text()))


def run_in_process(clips, out: Path) -> tuple[int, dict, dict, list[dict]]:
    from services.edge import main as cli

    code = cli.main(
        ["--no-detect", "--source", str(clips["moving"]), "--link", "file", "--out", str(out)]
    )
    folder = only_session(out)
    run, rows = read_run(folder)
    return code, json.loads((folder / "session.json").read_text()), run, rows


def test_recorder_stop_failing_still_writes_the_final_status(monkeypatch, clips, tmp_path):
    """A locked file while hashing, or any recorder failure at shutdown, must not leave the
    session `running` with null counts."""
    from services.edge import main as cli
    from services.edge.recording.recorder import FileRecorder

    class BadStop(FileRecorder):
        def stop(self):
            super().stop()
            raise PermissionError("locked by OneDrive")

    monkeypatch.setattr(cli, "FileRecorder", BadStop)
    _, session, run, _ = run_in_process(clips, tmp_path)
    assert session["status"] == "error" and session["ended_at"]
    assert run["ended_at"] and run["counts"] is not None
    errors = [e["detail"] for e in session["events"] if e["kind"] == "error"]
    assert any("recording stopped" in d and "locked by OneDrive" in d for d in errors)


def test_failed_recorder_is_reported_and_leaves_no_false_video_times(monkeypatch, clips, tmp_path):
    from services.edge import main as cli
    from services.edge.recording.recorder import FileRecorder

    class DiskFullAfter5:
        n = 0

        def write(self, image):
            if self.n == 5:
                raise OSError("disk full")
            self.n += 1

        def release(self):
            pass

    monkeypatch.setattr(
        cli, "FileRecorder", lambda: FileRecorder(writer_factory=lambda p, f, s: DiskFullAfter5())
    )
    _, session, run, rows = run_in_process(clips, tmp_path)
    counts = run["counts"]
    assert session["status"] == "error"
    assert counts["rec_dropped"] == counts["captured"] - 5
    kinds = {e["kind"] for e in session["events"]}
    assert {"recorder_backlog", "error"} <= kinds
    times = [float(r["t_video"]) for r in rows if r["t_video"]]
    assert all(t < 5 / 15 for t in times), "a time past the end of what was written"
