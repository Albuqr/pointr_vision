"""A calibration only applies to frames of the size it was made at. The Studio captures the
calibration frame with the recorder's own capture size, and a recording whose frames have another
size fails loudly (first frame) or stops applying the homography (a later change)."""

import dataclasses
import json
from pathlib import Path

import cv2
import numpy as np
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge import main as cli
from services.edge.capture.sources import DEFAULT_CAPTURE_SIZE
from services.edge.capture.types import Frame, SourceInfo
from tests.app.test_api import FakeLauncher
from tests.edge.fakes import EvenFrameDetector
from tests.edge.test_session import run_main, session_files

ROOT = Path(__file__).resolve().parents[2]


class Resizing:
    """A source whose frames change size from seq `switch_at` on (a reconnect at another size)."""

    def __init__(self, inner, switch_at, size):
        self.inner, self.switch_at, self.size = inner, switch_at, size
        self.kind = inner.kind

    def open(self):
        return self.inner.open()

    def read(self):
        frame = self.inner.read()
        if frame is not None and frame.seq >= self.switch_at:
            frame = dataclasses.replace(frame, image=cv2.resize(frame.image, self.size))
        return frame

    def close(self):
        self.inner.close()


def calibration_file(tmp_path):
    calibration = json.loads(
        (ROOT / "tests/fixtures/contracts/calibration.example.json").read_text(encoding="utf-8")
    )
    calibration["camera_id"] = "cam1"
    calibration["image_size"] = {"width": 640, "height": 360}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration), encoding="utf-8")
    return path


def record(monkeypatch, tmp_path, clips, switch_at):
    real = cli.open_source
    monkeypatch.setattr(
        cli, "open_source", lambda ref, size=None: Resizing(real(ref, size), switch_at, (320, 180))
    )
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        "--camera-id", "cam1", "--calibration", str(calibration_file(tmp_path)),
        detector=EvenFrameDetector(),
    )  # fmt: skip
    return code, out


def test_first_frame_of_another_size_fails_the_camera_with_both_sizes(
    monkeypatch, tmp_path, clips, capsys
):
    code, out = record(monkeypatch, tmp_path, clips, switch_at=0)
    assert code != 0
    stderr = capsys.readouterr().err
    assert "calibration cannot be used" in stderr
    assert "320x180" in stderr and "640x360" in stderr  # both sizes, for the UI to show
    session, _, frames, tracks = session_files(out)
    assert session["status"] == "error"
    assert sum(int(frame["n_tracks"] or 0) for frame in frames) == len(tracks)
    assert all(row["x_m"] == row["y_m"] == row["in_court"] == "" for row in tracks)


def test_a_size_change_mid_session_stops_the_homography_and_logs_an_event(
    monkeypatch, tmp_path, clips
):
    code, out = record(monkeypatch, tmp_path, clips, switch_at=10)
    assert code == 0
    session, _, frames, tracks = session_files(out)
    assert session["status"] == "ended"
    before = [r for r in tracks if int(r["seq"]) < 10]
    after = [r for r in tracks if int(r["seq"]) >= 10]
    assert before and after
    assert all(r["x_m"] and r["in_court"] for r in before)
    assert all(r["x_m"] == r["y_m"] == r["in_court"] == "" for r in after)
    assert all(r["calibration_id"] for r in after)  # still says which calibration was refused
    events = [e["detail"] for e in session["events"] if e["kind"] == "error"]
    assert any("320x180" in d and "640x360" in d for d in events)
    assert len(frames) > len(before) + len(after) - 1  # every processed frame has its row


# -- the Studio's idle calibration frame uses the recorder's capture size ----------------------


class DriverDefaultCamera:
    """640x480 unless a size is requested, as most webcams do."""

    requested = []

    def __init__(self, ref, size):
        self.size = size or (640, 480)
        DriverDefaultCamera.requested.append(size)

    def open(self):
        return SourceInfo("camera", "0", *self.size, 30.0, "usb")

    def read(self):
        image = np.zeros((self.size[1], self.size[0], 3), np.uint8)
        return Frame(0, 0.0, "2026-10-13T12:00:00Z", image, "0")

    def close(self):
        pass


def test_idle_calibration_frame_is_captured_at_the_recorders_size(monkeypatch, tmp_path):
    from services.app import server

    DriverDefaultCamera.requested.clear()
    monkeypatch.setattr(
        server, "open_source", lambda ref, size=None: DriverDefaultCamera(ref, size)
    )
    config = CameraConfig(tmp_path / "config.json")
    config.write([{"camera_id": "cam1", "source": "0", "link": "usb"}])
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        response = client.get("/api/cameras/cam1/calibration/frame")
    assert DriverDefaultCamera.requested == [DEFAULT_CAPTURE_SIZE]
    assert (response.headers["x-frame-width"], response.headers["x-frame-height"]) == (
        "1280",
        "720",
    )


def test_recorder_default_size_is_the_shared_constant():
    args = cli.parse_args(["--source", "0"])
    assert (args.width, args.height) == DEFAULT_CAPTURE_SIZE


def test_t8_unreadable_calibration_has_identical_single_and_group_checks(tmp_path, clips):
    from services.edge import group_main

    missing = tmp_path / "missing.json"
    outputs = []
    for grouped in (False, True):
        out = tmp_path / ("group" if grouped else "single")
        args = [
            "--source",
            str(clips["moving"]),
            "--link",
            "file",
            "--camera-id",
            "cam1",
            "--calibration",
            str(missing),
            "--no-detect",
            "--no-record",
            "--out",
            str(out),
        ]
        code = (
            group_main.main([json.dumps(args + ["--group-id", "g1"])])
            if grouped
            else cli.main(args)
        )
        assert code == 0
        session, run, _, _ = session_files(out)
        assert session["status"] == "ended" and run["calibration"] is None
        checks = [{k: v for k, v in check.items() if k != "t_wall"} for check in run["checks"]]
        events = [(event["kind"], event["detail"]) for event in session["events"]]
        assert checks[0]["result"] == "failed"
        assert [kind for kind, _ in events] == ["error", "startup_check_failed"]
        outputs.append((checks, events))
    assert outputs[0] == outputs[1]


def test_t8_session_replay_uses_live_calibration_and_explicit_override(tmp_path, clips):
    import uuid

    out = tmp_path / "sessions"
    path = calibration_file(tmp_path)
    original = json.loads(path.read_text(encoding="utf-8"))
    assert (
        cli.main(
            [
                "--source",
                str(clips["moving"]),
                "--link",
                "file",
                "--camera-id",
                "cam1",
                "--calibration",
                str(path),
                "--no-detect",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    [folder] = [p for p in out.iterdir() if p.is_dir()]
    override_id = str(uuid.uuid4())
    path.write_text(json.dumps({**original, "calibration_id": override_id}), encoding="utf-8")
    for explicit, expected in (
        (False, original["calibration_id"]),
        (True, override_id),
        (False, original["calibration_id"]),
    ):
        args = ["--replay", str(folder), "--no-detect", "--out", str(out)]
        assert cli.main(args + (["--calibration", str(path)] if explicit else [])) == 0
        session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        run = json.loads(
            (folder / "runs" / session["runs"][-1] / "run.json").read_text(encoding="utf-8")
        )
        assert run["calibration"]["calibration_id"] == expected


def test_t8_malformed_replay_calibration_is_a_persisted_failed_check(tmp_path, clips):
    out = tmp_path / "sessions"
    assert (
        cli.main(
            [
                "--source",
                str(clips["moving"]),
                "--link",
                "file",
                "--camera-id",
                "cam1",
                "--no-detect",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    [folder] = [p for p in out.iterdir() if p.is_dir()]
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    live_path = folder / "runs" / session["runs"][0] / "run.json"
    live = json.loads(live_path.read_text(encoding="utf-8"))
    live_path.write_text(json.dumps({**live, "calibration": []}), encoding="utf-8")
    assert cli.main(["--replay", str(folder), "--no-detect", "--out", str(out)]) == 0
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    run = json.loads(
        (folder / "runs" / session["runs"][-1] / "run.json").read_text(encoding="utf-8")
    )
    assert run["calibration"] is None
    assert run["checks"][0]["result"] == "failed"
    assert {e["kind"] for e in session["events"]} == {"error", "startup_check_failed"}
    assert all(run["run_id"] in e["detail"] for e in session["events"])


def test_t8_unreadable_live_run_refuses_replay_before_source_open(monkeypatch, tmp_path, clips):
    out = tmp_path / "sessions"
    assert (
        cli.main(
            ["--source", str(clips["moving"]), "--link", "file", "--no-detect", "--out", str(out)]
        )
        == 0
    )
    [folder] = [p for p in out.iterdir() if p.is_dir()]
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    (folder / "runs" / session["runs"][0] / "run.json").write_text("[]", encoding="utf-8")

    def unexpected_open(self):
        raise AssertionError("a damaged live run must be refused before opening the replay source")

    monkeypatch.setattr(cli.FileSource, "open", unexpected_open)
    assert (
        cli.main(["--replay", str(folder), "--no-detect", "--out", str(out)])
        == cli.EXIT_OPEN_FAILED
    )
    assert len(json.loads((folder / "session.json").read_text(encoding="utf-8"))["runs"]) == 1
