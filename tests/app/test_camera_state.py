"""B4: GET /api/status reports each camera's state as it steps through start, record and stop."""

import json

import pytest
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from tests.app.test_api import FakeLauncher


@pytest.fixture
def client(tmp_path):
    FakeLauncher.instances.clear()
    config = CameraConfig(tmp_path / "config.json")
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as test_client:
        yield test_client


def start_two(client):
    for name, source in (("cam1", "0"), ("cam2", "1")):
        client.post("/api/cameras", json={"camera_id": name, "source": source, "link": "builtin"})
    assert client.post("/api/recording/start").status_code == 200
    first, second = FakeLauncher.instances[-1].children
    for child in (first, second):
        child.stop_sent = False
        child.loading_model = False
        child.failure = None
    return first, second


def states(client):
    return {c["camera_id"]: c["state"] for c in client.get("/api/status").json()["cameras"]}


def open_session(child, tmp_path, status="running", ready=None):
    folder = tmp_path / child.cam.camera_id
    run = folder / "runs" / "run1"
    run.mkdir(parents=True, exist_ok=True)
    (folder / "session.json").write_text(json.dumps({"status": status, "events": []}), "utf-8")
    ready = {"model_loaded": "t", "first_frame": None, "first_preview": None, **(ready or {})}
    (run / "run.json").write_text(json.dumps({"ready": ready}), "utf-8")
    child.session_dir = folder


def test_each_camera_steps_through_every_state(client, tmp_path):
    first, second = start_two(client)
    assert states(client) == {"cam1": "starting", "cam2": "starting"}

    first.loading_model = True  # cam1 printed its device line and is loading the model
    assert states(client) == {"cam1": "loading_model", "cam2": "starting"}

    open_session(first, tmp_path)  # cam1 has a session but no frame yet
    assert states(client) == {"cam1": "waiting_first_frame", "cam2": "starting"}

    open_session(first, tmp_path, ready={"first_frame": "t"})
    open_session(second, tmp_path)
    assert states(client) == {"cam1": "recording", "cam2": "waiting_first_frame"}

    open_session(first, tmp_path, ready={"first_frame": "t", "first_preview": "t"})
    assert states(client) == {"cam1": "preview_ready", "cam2": "waiting_first_frame"}

    for child in (first, second):
        child.stop_sent = True
    assert states(client) == {"cam1": "stopping", "cam2": "stopping"}

    for child in (first, second):
        open_session(child, tmp_path, status="ended")
        child.running = False
    assert states(client) == {"cam1": "ended", "cam2": "ended"}


def test_a_failed_camera_reports_error_with_its_reason_and_the_others_keep_going(client, tmp_path):
    first, second = start_two(client)
    open_session(second, tmp_path, ready={"first_frame": "t"})
    first.failure = "failed: no session after 30 s"
    first.running = False
    cameras = {c["camera_id"]: c for c in client.get("/api/status").json()["cameras"]}
    assert cameras["cam1"]["state"] == "error"
    assert cameras["cam1"]["error"] == "failed: no session after 30 s"
    assert cameras["cam2"]["state"] == "recording"
    assert cameras["cam2"]["error"] is None


def test_a_camera_that_died_without_ending_its_session_is_an_error(client, tmp_path):
    first, _ = start_two(client)
    open_session(first, tmp_path, ready={"first_frame": "t"})
    first.running = False  # the process is gone and session.json still says running
    camera = client.get("/api/status").json()["cameras"][0]
    assert camera["state"] == "error" and camera["error"]
