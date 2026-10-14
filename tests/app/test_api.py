import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from jsonschema import Draft202012Validator
from starlette.testclient import TestClient

from scripts import run_cameras
from services.app import __main__ as app_cli
from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.launcher import Camera, Options, child_command
from services.edge.launcher_impl import Launcher
from tests.fixtures.make_clips import make_clips


class Child:
    def __init__(self, camera):
        self.cam = camera
        self.session_dir = None
        self.preview_port = camera.http_preview_port
        self.running = True


class FakeLauncher:
    instances = []

    def __init__(self, cameras, options):
        self.cameras = cameras
        self.opts = options
        self.children = [Child(camera) for camera in cameras]
        self.event = threading.Event()
        self.stop_called = False
        FakeLauncher.instances.append(self)

    def run(self):
        self.event.wait()
        for child in self.children:
            child.running = False
        return 0

    def stop_all(self, reason=None):
        self.stop_called = True
        self.event.set()


@pytest.fixture
def client(tmp_path):
    FakeLauncher.instances.clear()
    config = CameraConfig(tmp_path / "config.json")
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as test_client:
        yield test_client


def test_camera_crud_and_duplicate_source(client):
    first = {"camera_id": "cam1", "source": "0", "link": "builtin"}
    assert client.post("/api/cameras", json=first).status_code == 200
    duplicate = {"camera_id": "cam2", "source": "0", "link": "builtin"}
    assert client.post("/api/cameras", json=duplicate).status_code == 422
    assert client.put("/api/cameras/cam1", json={**first, "source": "1"}).status_code == 200
    assert client.get("/api/cameras").json()[0]["source"] == "1"
    assert client.delete("/api/cameras/cam1").status_code == 200


def test_camera_config_returns_field_specific_errors(client):
    response = client.post(
        "/api/cameras",
        json={
            "camera_id": "cam1",
            "name": "",
            "source": "",
            "link": "builtin",
            "det_size": 333,
            "fps_cap": 0,
        },
    )
    assert response.status_code == 422
    fields = {item["field"] for item in response.json()["detail"]["fields"]}
    assert {"name", "source", "det_size", "fps_cap"} <= fields


def test_camera_urls_are_masked_in_config_api_and_credentials_survive_edit(client):
    source = "rtsp://operator:secret@192.168.1.15:554/stream?token=token-secret"
    added = client.post(
        "/api/cameras",
        json={"camera_id": "cam1", "name": "Court", "source": source, "link": "wifi"},
    )
    assert added.status_code == 200
    shown = client.get("/api/cameras").json()[0]
    assert "secret" not in json.dumps(shown)
    assert "***@" in shown["source"]
    assert client.put("/api/cameras/cam1", json=shown).status_code == 200
    assert client.app.state.studio.entries()[0]["source"] == source


def test_disabled_cameras_are_not_started_and_config_warning_is_visible(client, tmp_path):
    client.post(
        "/api/cameras",
        json={"camera_id": "cam1", "source": "0", "link": "builtin", "enabled": False},
    )
    client.post(
        "/api/cameras",
        json={"camera_id": "cam2", "source": "1", "link": "usb", "enabled": True},
    )
    client.post("/api/recording/start")
    assert [camera.camera_id for camera in FakeLauncher.instances[-1].cameras] == ["cam2"]
    client.post("/api/recording/stop")
    client.app.state.studio.config.path.write_text("{broken", encoding="utf-8")
    assert client.get("/api/cameras").json() == []
    assert "could not be read" in client.get("/api/status").json()["config_warning"]


def test_test_camera_measures_three_seconds_and_closes_before_start(client, monkeypatch):
    from types import SimpleNamespace

    import services.app.server as server

    client.post("/api/cameras", json={"camera_id": "cam1", "source": "0", "link": "builtin"})
    clock = [0.0]

    class Source:
        closed = False

        def open(self):
            return SimpleNamespace(width=64, height=48, reported_fps=30.0)

        def read(self):
            clock[0] += 1.0
            return SimpleNamespace(image=np.zeros((48, 64, 3), dtype=np.uint8))

        def close(self):
            self.closed = True

    source = Source()
    monkeypatch.setattr(server, "open_source", lambda ref, size=None: source)
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    result = client.post("/api/cameras/cam1/test").json()
    assert result["resolution"] == [64, 48]
    assert result["fps"] == 1.0 and clock[0] == 3.0
    assert source.closed

    class AssertReleasedLauncher(FakeLauncher):
        def __init__(self, cameras, options):
            assert source.closed
            super().__init__(cameras, options)

    client.app.state.studio.launcher_factory = AssertReleasedLauncher
    assert client.post("/api/recording/start").status_code == 200
    client.post("/api/recording/stop")


def test_cli_and_app_share_launcher_library_and_http_preview_flag():
    assert run_cameras.Launcher is Launcher
    camera = Camera("cam1", "0", "builtin", http_preview_port=45678)
    command = child_command(camera, Options("C:/sessions", "group"))
    assert "--http-preview=45678" in command
    calibrated = Camera("cam1", "0", "builtin", calibration_path="C:/calibration.json")
    assert "--calibration=C:/calibration.json" in child_command(
        calibrated, Options("C:/sessions", "group")
    )
    result = subprocess.run(
        [sys.executable, "scripts/run_cameras.py", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "--config" in result.stdout


def test_local_host_and_origin_are_restricted(client):
    assert client.get("/api/cameras", headers={"Host": "example.com"}).status_code == 400
    assert (
        client.post(
            "/api/cameras",
            json={"camera_id": "x", "source": "0", "link": "builtin"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/recording/start",
            headers={"Origin": "http://127.0.0.1:9999"},
        ).status_code
        == 403
    )


def test_non_loopback_clients_are_rejected(tmp_path):
    app = create_app(str(tmp_path / "sessions"), CameraConfig(tmp_path / "config.json"))
    with TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.10", 1234)) as remote:
        assert remote.get("/api/cameras").status_code == 403


def test_startup_marks_only_app_owned_running_sessions_interrupted(tmp_path):
    config = CameraConfig(tmp_path / "config.json")
    config.path.parent.mkdir(parents=True, exist_ok=True)
    (config.path.parent / "active_group.json").write_text(
        '{"group_id":"owned-group"}', encoding="utf-8"
    )
    out = tmp_path / "sessions"
    owned = out / "cam1_owned"
    owned.mkdir(parents=True)
    (owned / "session.json").write_text(
        '{"group_id":"owned-group","status":"running","ended_at":null,"events":[]}',
        encoding="utf-8",
    )
    other = out / "cam2_other"
    other.mkdir()
    (other / "session.json").write_text(
        '{"group_id":"other-group","status":"running","ended_at":null,"events":[]}',
        encoding="utf-8",
    )

    create_app(str(out), config)

    recovered = json.loads((owned / "session.json").read_text(encoding="utf-8"))
    untouched = json.loads((other / "session.json").read_text(encoding="utf-8"))
    assert recovered["status"] == "interrupted"
    assert recovered["ended_at"] is not None
    assert recovered["events"][-1]["kind"] == "interrupted"
    assert untouched["status"] == "running"
    assert not (config.path.parent / "active_group.json").exists()


def test_built_frontend_is_served_without_node_and_path_traversal_is_blocked(client):
    assert "Pointr Studio" in client.get("/").text
    assert client.get("/%2e%2e/%2e%2e/README.md").status_code == 404


def test_app_cli_binds_loopback_and_passes_output_and_port(monkeypatch, tmp_path):
    captured = {}

    def run(app, host, port):
        captured.update(app=app, host=host, port=port)

    monkeypatch.setattr(app_cli.uvicorn, "run", run)
    app_cli.main(["--out", str(tmp_path), "--port", "9001"])
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    assert captured["app"].state.open_browser_url == "http://127.0.0.1:9001/"


def test_group_lifecycle_stays_running_until_explicit_stop(client):
    client.post("/api/cameras", json={"camera_id": "cam1", "source": "0", "link": "builtin"})
    started = client.post("/api/recording/start")
    assert started.status_code == 200
    assert started.json()["running"] is True
    preview_port = started.json()["cameras"][0]["preview_port"]
    assert 1 <= preview_port <= 65535
    assert preview_port == FakeLauncher.instances[-1].cameras[0].http_preview_port
    time.sleep(0.02)
    assert client.get("/api/status").json()["running"] is True
    stopped = client.post("/api/recording/stop")
    assert stopped.json()["running"] is False
    assert FakeLauncher.instances[-1].stop_called


def test_application_shutdown_uses_clean_stop(tmp_path):
    config = CameraConfig(tmp_path / "config.json")
    config.write([{"camera_id": "cam1", "source": "0", "link": "builtin"}])
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as test_client:
        assert test_client.post("/api/recording/start").status_code == 200
    assert FakeLauncher.instances[-1].stop_called


def test_camera_test_uses_fixture_without_model_and_is_refused_during_recording(client, tmp_path):
    fixture = make_clips(tmp_path)["moving"]
    client.post("/api/cameras", json={"camera_id": "clip", "source": str(fixture), "link": "file"})
    result = client.post("/api/cameras/clip/test").json()
    assert result["snapshot"]
    assert result["resolution"][0] > 0
    client.post("/api/recording/start")
    assert client.post("/api/cameras/clip/test").status_code == 409
    client.post("/api/recording/stop")


def test_calibration_frame_endpoint_returns_raw_full_resolution_frame(client, tmp_path):
    fixture = make_clips(tmp_path)["moving"]
    client.post("/api/cameras", json={"camera_id": "clip", "source": str(fixture), "link": "file"})
    response = client.get("/api/cameras/clip/calibration/frame")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-frame-token"]
    assert response.content.startswith(b"\xff\xd8")
    decoded = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[1] == int(response.headers["x-frame-width"])
    assert decoded.shape[0] == int(response.headers["x-frame-height"])


def test_calibration_fit_save_and_load_round_trip(client, tmp_path):
    fixture = make_clips(tmp_path)["moving"]
    client.post("/api/cameras", json={"camera_id": "clip", "source": str(fixture), "link": "file"})
    captured = client.get("/api/cameras/clip/calibration/frame")
    points = [
        {"image_px": [0, 0], "court_m": [0, 0], "role": "calibration"},
        {"image_px": [400, 0], "court_m": [4, 0], "role": "calibration"},
        {"image_px": [400, 300], "court_m": [4, 3], "role": "calibration"},
        {"image_px": [0, 300], "court_m": [0, 3], "role": "calibration"},
        {"image_px": [100, 100], "court_m": [1, 1], "role": "check"},
        {"image_px": [300, 200], "court_m": [3, 2], "role": "check"},
    ]
    payload = {
        "frame_token": captured.headers["x-frame-token"],
        "court_kind": "custom",
        "length_m": 4,
        "width_m": 3,
        "max_check_error_m": 0.5,
        "points": points,
    }
    fitted = client.post("/api/cameras/clip/calibration/fit", json=payload)
    assert fitted.status_code == 200, fitted.text
    assert fitted.json()["check_mean_m"] < 1e-6
    saved = client.put("/api/cameras/clip/calibration", json=payload)
    assert saved.status_code == 200, saved.text
    document = saved.json()["calibration"]
    assert client.get("/api/cameras/clip/calibration").json() == document
    schema_path = Path(__file__).resolve().parents[2] / "contracts/calibration.schema.json"
    Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(document)
    assert (
        client.get("/api/cameras/clip/calibration/compare").json()["difference_score"] is not None
    )
    assert (tmp_path / "calibrations/clip" / document["calibration_id"] / "frame.jpg").is_file()
    recaptured = client.get("/api/cameras/clip/calibration/frame")
    forced_payload = {
        **payload,
        "frame_token": recaptured.headers["x-frame-token"],
        "max_check_error_m": 0.05,
    }
    forced_payload["points"] = [*points[:-1], {**points[-1], "court_m": [3.5, 2.5]}]
    refused = client.put("/api/cameras/clip/calibration", json=forced_payload)
    assert refused.status_code == 422 and "exceeds" in refused.text
    forced_payload["save_anyway"] = True
    forced = client.put("/api/cameras/clip/calibration", json=forced_payload)
    assert forced.status_code == 200 and forced.json()["calibration"]["forced"] is True
    client.post("/api/recording/start")
    camera = FakeLauncher.instances[-1].cameras[0]
    assert camera.calibration_path.endswith("calibration.json")
