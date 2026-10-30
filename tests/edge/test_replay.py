"""Phase 04 replay: re-run the pipeline on a recorded video as a new run (RF09, RNF05).

R1-A1 / Phase 04 A3 (the original run is untouched), R1-A2 / A4 (MP4 and MOV). Subprocess runs use
--no-detect: no model, no weights."""

import csv
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import pytest

from services.edge import contract
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
    assert run["input"]["sha256"] == hashlib.sha256((folder / "video.mkv").read_bytes()).hexdigest()
    session = json.loads((folder / "session.json").read_text())
    assert session["runs"] == [*session_before["runs"], run["run_id"]]
    session_before["runs"] = session["runs"]
    assert session == session_before, "replay changed more of session.json than its runs"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_replay_by_session_id(clips, tmp_path, encoding):
    folder = record(clips, tmp_path)
    session_file = folder / "session.json"
    before = json.loads(session_file.read_text())
    session_id = before["session_id"]
    session_file.write_text(json.dumps(before), encoding=encoding)
    result = run_cli(tmp_path, "--replay", session_id)
    assert result.returncode == 0, result.stderr
    assert len(list((folder / "runs").iterdir())) == 2
    after = json.loads(session_file.read_text(encoding="utf-8-sig"))
    assert after["runs"][:1] == before["runs"]
    assert len(after["runs"]) == 2
    after["runs"] = before["runs"]
    assert after == before


def test_replay_processes_every_frame_with_container_times(clips, tmp_path):
    folder = record(clips, tmp_path)
    (original,) = (folder / "runs").iterdir()
    run_cli(tmp_path, "--replay", str(folder))
    run_dir = new_run(folder, {original.name})
    counts = json.loads((run_dir / "run.json").read_text())["counts"]
    assert counts["dropped"] == 0 and counts["processed"] == counts["captured"] == 30
    fps = cv2.VideoCapture(str(folder / "video.mkv")).get(cv2.CAP_PROP_FPS)
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
    video = folder / "video.mkv"
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
    assert "video.mkv" in result.stderr


def test_unknown_target_is_refused(tmp_path):
    result = run_cli(tmp_path, "--replay", "no-such-session")
    assert result.returncode == EXIT_OPEN_FAILED
    assert "Traceback" not in result.stderr


def test_source_and_replay_are_exclusive(clips, tmp_path):
    result = run_cli(tmp_path, "--source", str(clips["moving"]), "--replay", str(clips["moving"]))
    assert result.returncode != 0
    result = run_cli(tmp_path)
    assert result.returncode != 0


def validate(name: str, doc: dict) -> None:
    from jsonschema import Draft202012Validator

    Draft202012Validator(contract.schema(name)).validate(doc)


def test_live_and_replay_files_match_the_schemas(clips, tmp_path):
    folder = record(clips, tmp_path)
    run_cli(tmp_path, "--replay", str(folder))
    run_cli(tmp_path, "--replay", str(clips["moving_mov"]))  # a bare file: a new session
    sessions = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(sessions) == 2
    for session_dir in sessions:
        validate("session", json.loads((session_dir / "session.json").read_text()))
        for run_dir in (session_dir / "runs").iterdir():
            validate("run", json.loads((run_dir / "run.json").read_text()))


def test_session_without_a_video_hash_still_replays_with_a_warning(clips, tmp_path):
    folder = record(clips, tmp_path)
    doc = json.loads((folder / "session.json").read_text())
    doc["recording"]["sha256"] = None  # what a killed session leaves
    (folder / "session.json").write_text(json.dumps(doc))
    result = run_cli(tmp_path, "--replay", str(folder))
    assert result.returncode == 0, result.stderr
    assert "no video hash" in result.stderr
    assert len(list((folder / "runs").iterdir())) == 2


def replay_meta(run_id: str):
    from services.edge.session.types import RunMeta

    return RunMeta(
        run_id=run_id,
        mode="replay",
        input={"kind": "file", "ref": "x", "sha256": "0" * 64,
               "requested_width": None, "requested_height": None},
        detector=None,
        tracker=None,
        health={},
        runtime={"python": "3", "platform": "p", "device": None, "gpu": None, "packages": {}},
        started_at="2026-10-20T00:00:00Z",
    )  # fmt: skip


def counts():
    from services.edge.session.types import RunCounts

    return RunCounts(0, 0, 0, 0)


def test_interrupted_replay_is_visible_in_session_json(clips, tmp_path):
    """The replay's own status lives nowhere else: an interrupted replay must not look complete."""
    from services.edge.session.types import SessionEvent
    from services.edge.session.writer import FileSessionWriter

    folder = record(clips, tmp_path)
    before = json.loads((folder / "session.json").read_text())
    w = FileSessionWriter(tmp_path)
    run_id = "22222222-2222-4222-8222-222222222222"
    w.start_run(folder, replay_meta(run_id))
    w.event(SessionEvent("2026-10-20T00:00:01Z", 1.0, "source_lost", "noise: not kept"))
    w.event(SessionEvent("2026-10-20T00:00:02Z", 2.0, "interrupted", "Ctrl+C"))
    w.close("interrupted", counts())
    after = json.loads((folder / "session.json").read_text())
    assert after["status"] == "ended" and after["recording"] == before["recording"]
    assert after["runs"] == [*before["runs"], run_id]
    assert after["events"] == [
        {"t_wall": "2026-10-20T00:00:02Z", "t_mono": 2.0, "kind": "interrupted",
         "detail": f"replay {run_id}: Ctrl+C"}
    ]  # fmt: skip


def test_replay_that_ends_badly_without_an_event_gets_one(clips, tmp_path):
    from services.edge.session.writer import FileSessionWriter

    folder = record(clips, tmp_path)
    w = FileSessionWriter(tmp_path)
    run_id = "33333333-3333-4333-8333-333333333333"
    w.start_run(folder, replay_meta(run_id))
    w.close("error", counts())
    (event,) = json.loads((folder / "session.json").read_text())["events"]
    assert event["kind"] == "error" and event["detail"].startswith(f"replay {run_id}:")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_two_replays_of_one_session_keep_both_run_ids(clips, tmp_path, encoding):
    from services.edge.session.writer import FileSessionWriter

    folder = record(clips, tmp_path)
    a, b = FileSessionWriter(tmp_path), FileSessionWriter(tmp_path)
    ids = ["44444444-4444-4444-8444-444444444444", "55555555-5555-4555-8555-555555555555"]
    a.start_run(folder, replay_meta(ids[0]))
    b.start_run(folder, replay_meta(ids[1]))  # started while a is still open
    b.close("ended", counts())
    session_file = folder / "session.json"
    session_file.write_text(session_file.read_text(), encoding=encoding)
    a.close("ended", counts())  # a's stale copy must not drop b's run
    runs = json.loads((folder / "session.json").read_text())["runs"]
    assert set(ids) <= set(runs) and len(runs) == len(set(runs)) == 3
    assert {p.name for p in (folder / "runs").iterdir()} == set(runs)


@pytest.mark.parametrize("when", ["startup", "merge"])
@pytest.mark.parametrize("damaged", [False, True], ids=["historical", "damaged-evidence"])
def test_T2_replay_preserves_original_session_metadata(tmp_path, when, damaged):
    from services.edge.session.writer import FileSessionWriter

    path = tmp_path / "session.json"
    original = {
        "session_id": "11111111-1111-4111-8111-111111111111",
        "runs": [],
        "events": [],
    }  # historical documents may omit optional metadata
    evidence = {
        "events": [None, {"kind": "error", "detail": "original evidence"}],
        "source": ["malformed but must survive"],
        "status": 123,
        "camera_id": {"unexpected": "object"},
        "future": {"nested": [None, "preserve"]},
    }
    if damaged and when == "startup":
        original.update(evidence)
    path.write_text(json.dumps(original), encoding="utf-8-sig")
    writer = FileSessionWriter(tmp_path)
    run_id = "22222222-2222-4222-8222-222222222222"
    writer.start_run(tmp_path, replay_meta(run_id))
    try:
        if when == "merge":
            current = {**original, "runs": [run_id]}
            if damaged:
                current.update(evidence)
            path.write_text(json.dumps(current), encoding="utf-8-sig")
            original = current
    finally:
        writer.close("ended", counts())
    expected = {**original, "runs": [run_id]}
    assert json.loads(path.read_text(encoding="utf-8-sig")) == expected


@pytest.mark.parametrize("when", ["startup", "merge"])
@pytest.mark.parametrize("key,value", [("session_id", []), ("runs", {}), ("events", None)])
def test_T2_replay_refuses_unreadable_mutation_fields_without_overwriting(
    tmp_path, when, key, value
):
    from services.edge.session.folder import SessionDamaged
    from services.edge.session.writer import FileSessionWriter

    path = tmp_path / "session.json"
    original = {
        "session_id": "11111111-1111-4111-8111-111111111111",
        "runs": [],
        "events": [],
    }
    run_id = "22222222-2222-4222-8222-222222222222"
    writer = FileSessionWriter(tmp_path)
    if when == "merge":
        path.write_text(json.dumps(original), encoding="utf-8")
        writer.start_run(tmp_path, replay_meta(run_id))
        original["runs"] = [run_id]
    original[key] = value
    path.write_text(json.dumps(original), encoding="utf-8-sig")
    before = path.read_bytes()
    with pytest.raises(SessionDamaged, match=f"session damaged:.*{key}"):
        if when == "startup":
            writer.start_run(tmp_path, replay_meta(run_id))
        else:
            writer.close("ended", counts())
    assert path.read_bytes() == before
    if when == "startup":
        assert not (tmp_path / "runs").exists()


class SlowDetector:
    """A detector slower than reading a file: a replay that drops frames would show it."""

    threshold, det_size, device = 0.5, 384, "cpu"

    def __init__(self, delay: float = 0.03):
        self.delay = delay

    def detect(self, frame):
        from services.edge.perception.loop import NO_DETECTIONS

        time.sleep(self.delay)
        return NO_DETECTIONS


class NoTracks:
    params = {}

    def update(self, dets, frame):
        return []


def test_replay_with_a_slow_detector_still_processes_every_frame(clips, tmp_path, monkeypatch):
    """D-042 / Phase 04 A3 wiring: main must run a replay with lossless capture. Without it the
    slow detector makes the capture thread drop frames, as a live run does."""
    from services.edge import main as cli

    folder = record(clips, tmp_path)
    monkeypatch.setattr(cli, "load_perception", lambda a, d: (SlowDetector(), NoTracks()))
    code = cli.main(["--replay", str(folder), "--out", str(tmp_path)])
    assert code == 0
    runs = [json.loads((r / "run.json").read_text()) for r in (folder / "runs").iterdir()]
    (replay,) = [r for r in runs if r["mode"] == "replay"]
    assert replay["counts"]["dropped"] == 0
    assert replay["counts"]["processed"] == replay["counts"]["captured"] == 30
    assert replay["detector"] is not None  # the detector path ran, not --no-detect


def test_live_run_with_the_same_slow_detector_does_drop(clips, tmp_path, monkeypatch):
    """The control: a live source plays at 15 fps (66 ms a frame), so the detector must be slower
    than that. If it did not drop, the test above would prove nothing."""
    from services.edge import main as cli

    monkeypatch.setattr(cli, "load_perception", lambda a, d: (SlowDetector(0.15), NoTracks()))
    cli.main(["--source", str(clips["moving"]), "--link", "file", "--out", str(tmp_path)])
    (folder,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    (run_dir,) = (folder / "runs").iterdir()
    assert json.loads((run_dir / "run.json").read_text())["counts"]["dropped"] > 0


def test_session_recorded_as_mp4_before_the_rename_still_replays(clips, tmp_path):
    """An older session names video.mp4 in session.json; replay follows the recorded path."""
    folder = record(clips, tmp_path)
    (folder / "video.mkv").rename(folder / "video.mp4")
    doc = json.loads((folder / "session.json").read_text())
    doc["recording"]["path"] = "video.mp4"
    (folder / "session.json").write_text(json.dumps(doc))
    result = run_cli(tmp_path, "--replay", str(folder))
    assert result.returncode == 0, result.stderr
    assert len(list((folder / "runs").iterdir())) == 2


def test_recording_path_outside_the_session_folder_is_refused(clips, tmp_path):
    folder = record(clips, tmp_path)
    doc = json.loads((folder / "session.json").read_text())
    doc["recording"]["path"] = "../" + folder.name + "/video.mkv"  # leaves the folder and returns
    (folder / "session.json").write_text(json.dumps(doc))
    doc["recording"]["path"] = str(clips["moving"])  # an absolute path elsewhere
    (folder / "session.json").write_text(json.dumps(doc))
    result = run_cli(tmp_path, "--replay", str(folder))
    assert result.returncode == EXIT_OPEN_FAILED


def test_an_mkv_file_replays_like_any_other_video(clips, tmp_path):
    folder = record(clips, tmp_path)
    copy = tmp_path / "copy.mkv"
    copy.write_bytes((folder / "video.mkv").read_bytes())
    result = run_cli(tmp_path / "out", "--replay", str(copy))
    assert result.returncode == 0, result.stderr
