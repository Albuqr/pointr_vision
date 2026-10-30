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
