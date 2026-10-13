import json
import subprocess
import sys
import threading
import time

import pytest
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


def test_cli_and_app_share_launcher_library_and_http_preview_flag():
    assert run_cameras.Launcher is Launcher
    camera = Camera("cam1", "0", "builtin", http_preview_port=45678)
    command = child_command(camera, Options("C:/sessions", "group"))
    assert "--http-preview=45678" in command
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
