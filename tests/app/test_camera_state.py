"""B4: GET /api/status reports each camera's state as it steps through start, record and stop."""

import json
from pathlib import Path

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
    (folder / "session.json").write_text(
        json.dumps({"status": status, "events": [], "runs": ["run1"]}), "utf-8"
    )
    ready = {"model_loaded": "t", "first_frame": None, "first_preview": None, **(ready or {})}
    (run / "run.json").write_text(json.dumps({"ready": ready}), "utf-8")
    child.session_dir = folder


@pytest.mark.parametrize("folder_order", [("live", "replay"), ("replay", "live")])
@pytest.mark.parametrize("listed_order", [("live", "replay"), ("replay", "live")])
def test_B9_status_uses_last_listed_run(client, tmp_path, monkeypatch, folder_order, listed_order):
    child, _ = start_two(client)
    folder = tmp_path / "cam1"
    runs = folder / "runs"
    for mode, people, tracks, drops, elapsed, preview in (
        ("live", 2, 3, 4, 1, None),
        ("replay", 5, 6, 7, 0.5, "t"),
    ):
        run = runs / mode
        run.mkdir(parents=True)
        (run / "run.json").write_text(
            json.dumps({"mode": mode, "ready": {"first_frame": "t", "first_preview": preview}}),
            encoding="utf-8",
        )
        (run / "frames.csv").write_text(
            "seq,t_recv,t_proc_start,t_proc_end,app_delay_ms,n_detections,n_tracks,dropped_total\n"
            f"0,0,0,{elapsed},0,{people},{tracks},{drops}\n",
            encoding="utf-8",
        )
    (folder / "session.json").write_text(
        json.dumps({"status": "running", "events": [], "runs": listed_order}), encoding="utf-8"
    )
    child.session_dir = folder
    original_iterdir = Path.iterdir

    def ordered_iterdir(path):
        if path == runs:
            return iter(runs / mode for mode in folder_order)
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", ordered_iterdir)
    response = client.get("/api/status")
    assert response.status_code == 200
    camera = next(c for c in response.json()["cameras"] if c["camera_id"] == "cam1")
    expected = (
        ("preview_ready", 2.0, 5, 6, 7)
        if listed_order[-1] == "replay"
        else ("recording", 1.0, 2, 3, 4)
    )
    shown = tuple(camera[key] for key in ("state", "processed_fps", "people", "tracks", "drops"))
    assert shown == expected


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


def test_the_launcher_marks_a_child_loading_its_model_from_its_device_line():
    import io
    from types import SimpleNamespace

    from services.edge.launcher import Camera
    from services.edge.launcher_impl import Child, Launcher

    child = Child(Camera("cam1", "0", "builtin"))
    child.proc = SimpleNamespace(
        stdout=io.StringIO("source ok\ndevice: cpu (no CUDA GPU in use)\n")
    )
    launcher = Launcher.__new__(Launcher)
    launcher.say = lambda line: None
    assert child.loading_model is False
    Launcher.read(launcher, child)
    assert child.loading_model is True


def test_camera_state_survives_run_json_with_ready_null(client, tmp_path):
    first, _ = start_two(client)
    folder = tmp_path / first.cam.camera_id
    run = folder / "runs" / "run1"
    run.mkdir(parents=True, exist_ok=True)
    (folder / "session.json").write_text(json.dumps({"status": "running", "events": []}), "utf-8")
    (run / "run.json").write_text(json.dumps({"ready": None}), "utf-8")
    first.session_dir = folder

    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert states(client)["cam1"] == "waiting_first_frame"


def test_camera_state_survives_run_json_with_ready_missing(client, tmp_path):
    first, _ = start_two(client)
    folder = tmp_path / first.cam.camera_id
    run = folder / "runs" / "run1"
    run.mkdir(parents=True, exist_ok=True)
    (folder / "session.json").write_text(json.dumps({"status": "running", "events": []}), "utf-8")
    (run / "run.json").write_text(json.dumps({}), "utf-8")
    first.session_dir = folder

    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert states(client)["cam1"] == "waiting_first_frame"
