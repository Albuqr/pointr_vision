"""Phase 04 replay: re-run the pipeline on a recorded video as a new run (RF09, RNF05).

R1-A1 / Phase 04 A3 (the original run is untouched), R1-A2 / A4 (MP4 and MOV). Subprocess runs use
--no-detect: no model, no weights."""

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import cv2
import pytest

from services.edge.main import EXIT_OPEN_FAILED

ROOT = Path(__file__).resolve().parents[2]


def run_cli(out: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "services.edge.main", "--no-detect", "--out", str(out), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def record(clips, out: Path) -> Path:
    """A live run of the synthetic clip; returns its session folder."""
    result = run_cli(out, "--source", str(clips["moving"]), "--link", "file")
    assert result.returncode == 0, result.stderr
    (folder,) = [p for p in out.iterdir() if p.is_dir()]
    return folder


def digests(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def new_run(folder: Path, before: set[str]) -> Path:
    (run_dir,) = [p for p in (folder / "runs").iterdir() if p.name not in before]
    return run_dir


def frames(run_dir: Path) -> list[dict]:
    with open(run_dir / "frames.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_A3_replay_adds_a_run_and_leaves_the_original_untouched(clips, tmp_path):
    folder = record(clips, tmp_path)
    (original,) = (folder / "runs").iterdir()
    before = digests(original)
    session_before = json.loads((folder / "session.json").read_text())

    result = run_cli(tmp_path, "--replay", str(folder))

    assert result.returncode == 0, result.stderr
    assert digests(original) == before, "the original run changed"
    run_dir = new_run(folder, {original.name})
    run = json.loads((run_dir / "run.json").read_text())
    assert run["mode"] == "replay"
    assert run["input"]["sha256"] == hashlib.sha256((folder / "video.mp4").read_bytes()).hexdigest()
    session = json.loads((folder / "session.json").read_text())
    assert session["runs"] == [*session_before["runs"], run["run_id"]]
    session_before["runs"] = session["runs"]
    assert session == session_before, "replay changed more of session.json than its runs"


def test_replay_by_session_id(clips, tmp_path):
    folder = record(clips, tmp_path)
    session_id = json.loads((folder / "session.json").read_text())["session_id"]
    result = run_cli(tmp_path, "--replay", session_id)
    assert result.returncode == 0, result.stderr
    assert len(list((folder / "runs").iterdir())) == 2


def test_replay_processes_every_frame_with_container_times(clips, tmp_path):
    folder = record(clips, tmp_path)
    (original,) = (folder / "runs").iterdir()
    run_cli(tmp_path, "--replay", str(folder))
    run_dir = new_run(folder, {original.name})
    counts = json.loads((run_dir / "run.json").read_text())["counts"]
    assert counts["dropped"] == 0 and counts["processed"] == counts["captured"] == 30
    fps = cv2.VideoCapture(str(folder / "video.mp4")).get(cv2.CAP_PROP_FPS)
    rows = frames(run_dir)
    assert [float(r["t_video"]) for r in rows] == pytest.approx(
        [i / fps for i in range(30)], abs=1e-3
    )


@pytest.mark.parametrize("clip", ["moving", "moving_mov"])
def test_A4_mp4_and_mov_replay(clips, tmp_path, clip):
    result = run_cli(tmp_path, "--replay", str(clips[clip]))
    assert result.returncode == 0, result.stderr
    (folder,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    (run_dir,) = (folder / "runs").iterdir()
    run = json.loads((run_dir / "run.json").read_text())
    assert run["mode"] == "replay" and run["input"]["kind"] == "file"
    assert run["input"]["sha256"] == hashlib.sha256(Path(clips[clip]).read_bytes()).hexdigest()
    assert run["counts"]["processed"] == 30
    assert float(frames(run_dir)[1]["t_video"]) == pytest.approx(1 / 15, abs=1e-3)


def test_changed_video_is_refused(clips, tmp_path):
    folder = record(clips, tmp_path)
    video = folder / "video.mp4"
    video.write_bytes(video.read_bytes() + b"x")
    result = run_cli(tmp_path, "--replay", str(folder))
    assert result.returncode == EXIT_OPEN_FAILED
    assert "sha256" in result.stderr
    assert len(list((folder / "runs").iterdir())) == 1


def test_session_without_video_is_refused(clips, tmp_path):
    result = run_cli(tmp_path, "--source", str(clips["moving"]), "--link", "file", "--no-record")
    assert result.returncode == 0, result.stderr
    (folder,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    result = run_cli(tmp_path, "--replay", str(folder))
    assert result.returncode == EXIT_OPEN_FAILED
    assert "video.mp4" in result.stderr


def test_unknown_target_is_refused(tmp_path):
    result = run_cli(tmp_path, "--replay", "no-such-session")
    assert result.returncode == EXIT_OPEN_FAILED
    assert "Traceback" not in result.stderr


def test_source_and_replay_are_exclusive(clips, tmp_path):
    result = run_cli(tmp_path, "--source", str(clips["moving"]), "--replay", str(clips["moving"]))
    assert result.returncode != 0
    result = run_cli(tmp_path)
    assert result.returncode != 0
