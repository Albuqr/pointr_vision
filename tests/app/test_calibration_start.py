"""One camera's missing or corrupt calibration never blocks the group: that camera records
uncalibrated, says so (session event and status warning), and the others keep their calibration."""

import copy
import json
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.launcher import Options, child_command
from services.edge.launcher_impl import Camera
from tests.app.test_api import FakeLauncher
from tests.edge.test_session import run_main, session_files

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = json.loads(
    (ROOT / "tests/fixtures/contracts/calibration.example.json").read_text(encoding="utf-8")
)


@pytest.fixture
def two_cameras(tmp_path):
    config = CameraConfig(tmp_path / "config.json")
    config.write(
        [
            {"camera_id": "cam1", "source": "rtsp://10.0.0.1/a", "link": "wifi"},
            {"camera_id": "cam2", "source": "rtsp://10.0.0.2/a", "link": "wifi"},
        ]
    )
    FakeLauncher.instances.clear()
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        document = copy.deepcopy(EXAMPLE)
        document.update(camera_id="cam2", calibration_id=str(uuid.uuid4()))
        client.app.state.studio.calibrations.save(document, b"jpeg")
        yield client


def corrupt_active_json(studio):
    folder = studio.calibrations.camera_dir("cam1")
    folder.mkdir(parents=True)
    (folder / "active.json").write_text('{"calibration_id": "', encoding="utf-8")


def active_points_to_a_missing_file(studio):
    folder = studio.calibrations.camera_dir("cam1")
    folder.mkdir(parents=True)
    (folder / "active.json").write_text(
        json.dumps({"calibration_id": str(uuid.uuid4())}), encoding="utf-8"
    )


def calibration_json_is_invalid(studio):
    document = copy.deepcopy(EXAMPLE)
    document.update(camera_id="cam1", calibration_id=str(uuid.uuid4()))
    document["image_size"]["width"] = 0
    folder = studio.calibrations.camera_dir("cam1") / document["calibration_id"]
    folder.mkdir(parents=True)
    (folder / "calibration.json").write_text(json.dumps(document), encoding="utf-8")
    (folder.parent / "active.json").write_text(
        json.dumps({"calibration_id": document["calibration_id"]}), encoding="utf-8"
    )


@pytest.mark.parametrize(
    "damage", [corrupt_active_json, active_points_to_a_missing_file, calibration_json_is_invalid]
)
def test_a_bad_calibration_starts_that_camera_uncalibrated_not_the_group_refused(
    two_cameras, damage
):
    client = two_cameras
    studio = client.app.state.studio
    damage(studio)
    started = client.post("/api/recording/start")
    assert started.status_code == 200, started.text
    cam1, cam2 = FakeLauncher.instances[-1].cameras
    assert cam1.camera_id == "cam1" and cam1.calibration_path is None
    assert cam1.calibration_problem and "without calibration" in cam1.calibration_problem
    assert cam2.calibration_path.endswith("calibration.json") and cam2.calibration_problem is None
    by_id = {c["camera_id"]: c for c in started.json()["cameras"]}
    assert "without calibration" in by_id["cam1"]["calibration_warning"]
    assert by_id["cam2"]["calibration_warning"] is None


def test_a_refusal_free_start_replaces_the_group_and_clears_old_warnings(two_cameras):
    client = two_cameras
    studio = client.app.state.studio
    corrupt_active_json(studio)
    client.post("/api/recording/start")
    client.post("/api/recording/stop")
    (studio.calibrations.camera_dir("cam1") / "active.json").unlink()  # fixed: uncalibrated
    again = client.post("/api/recording/start").json()
    assert all(c["calibration_warning"] is None for c in again["cameras"])


def test_an_unexpected_calibration_load_error_only_disables_that_camera(two_cameras, monkeypatch):
    client = two_cameras
    studio = client.app.state.studio
    load = studio.calibrations.load

    def load_one(camera_id):
        if camera_id == "cam1":
            raise RecursionError("too deeply nested")
        return load(camera_id)

    monkeypatch.setattr(studio.calibrations, "load", load_one)
    started = client.post("/api/recording/start")
    assert started.status_code == 200, started.text
    cameras = {camera["camera_id"]: camera for camera in started.json()["cameras"]}
    assert "too deeply nested" in cameras["cam1"]["calibration_warning"]
    assert cameras["cam2"]["calibration_warning"] is None


def test_the_launcher_passes_the_problem_to_the_recorder():
    cam = Camera("cam1", "0", "usb", calibration_problem="active.json is unreadable")
    command = child_command(cam, Options("out", "g1"))
    assert "--calibration-problem=active.json is unreadable" in command
    assert not any(part.startswith("--calibration-problem") for part in child_command(
        Camera("cam1", "0", "usb"), Options("out", "g1")
    ))  # fmt: skip


def test_the_recorder_writes_the_problem_as_a_session_event(monkeypatch, tmp_path, clips):
    from tests.edge.fakes import EvenFrameDetector

    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        "--camera-id", "cam1", "--calibration-problem", "active.json is unreadable",
        detector=EvenFrameDetector(),
    )  # fmt: skip
    assert code == 0
    session, run, _, tracks = session_files(out)
    assert any(
        e["kind"] == "error" and e["detail"] == "calibration not used: active.json is unreadable"
        for e in session["events"]
    )
    assert session["calibration"] is None and tracks[0]["x_m"] == ""
