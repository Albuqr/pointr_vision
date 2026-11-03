"""B4: GET /api/status reports each camera's state as it steps through start, record and stop."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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


def test_a_camera_that_died_without_ending_its_session_is_an_error(client, tmp_path):
    first, _ = start_two(client)
    open_session(first, tmp_path, ready={"first_frame": "t"})
    first.running = False  # the process is gone and session.json still says running
    camera = client.get("/api/status").json()["cameras"][0]
    assert camera["state"] == "error" and camera["error"]


@pytest.mark.parametrize("has_session, exit_code", [(True, 7), (False, None)])
def test_a_dead_camera_with_no_end_written_reaches_its_log(
    client, tmp_path, has_session, exit_code
):
    first, _ = start_two(client)
    if has_session:
        open_session(first, tmp_path, ready={"first_frame": "t"})
    source = "rtsp://operator:secret-pass@192.168.1.8/stream?token=secret-token"
    first.cam = replace(first.cam, source=source)
    first.proc = SimpleNamespace(returncode=exit_code)
    first.tail = [f"last frame from {source}", "native crash"]
    first.running = False
    camera = client.get("/api/status").json()["cameras"][0]
    assert camera["state"] == "error"
    assert camera["last_error"]
    assert "without writing a session end" in camera["error"]
    detail = camera["last_error"]["detail"]
    assert "without writing a session end" in detail
    assert f"session status: {'running' if has_session else None}" in detail
    if exit_code is not None:
        assert f"exit code: {exit_code}" in detail
    else:
        assert "exit code:" not in detail
    assert "output (last 2 lines):" in detail and "native crash" in detail
    assert "source: rtsp://***@" in detail
    for _ in range(3):
        assert client.get("/api/status").json()["cameras"][0] == camera
    errors = [e for e in camera["recent_events"] if e["kind"] == "error"]
    assert len(errors) == 1
    assert "without writing a session end" in errors[0]["detail"]
    audit = client.app.state.studio.audit.read()
    failures = [e for e in audit if e["action"] == "error" and e["camera_id"] == "cam1"]
    assert len(failures) == 1
    assert failures[0]["detail"]["reason"] == detail
    shown = json.dumps([camera, audit])
    assert "secret-pass" not in shown and "secret-token" not in shown


@pytest.mark.parametrize("status", ["ended", "interrupted"])
@pytest.mark.parametrize("alive", [False, True])
def test_a_normal_camera_end_is_logged_once_without_error(client, tmp_path, status, alive):
    first, _ = start_two(client)
    open_session(first, tmp_path, status=status)
    first.running = alive  # a group process may still be running for its other camera
    for _ in range(3):
        camera = client.get("/api/status").json()["cameras"][0]
        assert camera["state"] == status
        assert camera["last_error"] is None and camera["error"] is None
    assert len(camera["recent_events"]) == 1
    assert status in camera["recent_events"][0]["detail"]
    results = [
        e
        for e in client.app.state.studio.audit.read()
        if e["action"] == "recording_stop" and e["camera_id"] == "cam1"
    ]
    assert len(results) == 1 and results[0]["outcome"] == "ok"
    assert status in results[0]["detail"]["reason"]


@pytest.mark.parametrize("has_session", [False, True])
def test_a_requested_stop_without_a_written_end_is_not_an_error(client, tmp_path, has_session):
    first, _ = start_two(client)
    if has_session:
        open_session(first, tmp_path)
    first.stop_sent = True
    waiting = client.get("/api/status").json()["cameras"][0]
    assert waiting["state"] == "stopping"
    assert waiting["recent_events"] == []
    first.running = False
    for _ in range(3):
        camera = client.get("/api/status").json()["cameras"][0]
        assert camera["state"] in ("stopping", "interrupted")
        assert camera["last_error"] is None and camera["error"] is None
    assert len(camera["recent_events"]) == 1
    assert camera["recent_events"][0]["kind"] == "interrupted"
    assert "without writing a session end" in camera["recent_events"][0]["detail"]
    results = [
        e
        for e in client.app.state.studio.audit.read()
        if e["action"] == "recording_stop" and e["camera_id"] == "cam1"
    ]
    assert len(results) == 1 and results[0]["outcome"] == "ok"
    assert "without writing a session end" in results[0]["detail"]["reason"]


@pytest.mark.parametrize("status, kind", [("ended", "stopped"), ("interrupted", "interrupted")])
def test_a_written_stop_event_is_not_duplicated_in_the_camera_log(client, tmp_path, status, kind):
    first, _ = start_two(client)
    open_session(first, tmp_path, status=status)
    path = first.session_dir / "session.json"
    session = json.loads(path.read_text(encoding="utf-8"))
    session["events"] = [{"kind": kind, "detail": "ui: stop requested in Studio"}]
    path.write_text(json.dumps(session), encoding="utf-8")
    first.running = False
    for _ in range(3):
        camera = client.get("/api/status").json()["cameras"][0]
    assert [e["kind"] for e in camera["recent_events"]] == [kind]
    assert camera["last_error"] is None


@pytest.mark.parametrize("alive", [False, True])
def test_a_written_session_error_keeps_its_existing_message(client, tmp_path, alive):
    first, _ = start_two(client)
    open_session(first, tmp_path, status="error")
    first.running = alive
    for _ in range(3):
        camera = client.get("/api/status").json()["cameras"][0]
    assert camera["state"] == "error"
    assert camera["last_error"]["message"] == "The camera stopped recording because of an error."
    assert [e["kind"] for e in camera["recent_events"]] == ["error"]
    errors = [
        e
        for e in client.app.state.studio.audit.read()
        if e["action"] == "error" and e["camera_id"] == "cam1"
    ]
    assert len(errors) == 1


def test_the_launcher_marks_a_child_loading_its_model_from_its_device_line():
    import io
    from types import SimpleNamespace

    from services.edge.launcher import Camera, Child, Launcher

    child = Child(Camera("cam1", "0", "builtin"))
    child.proc = SimpleNamespace(
        stdout=io.StringIO("source ok\ndevice: cpu (no CUDA GPU in use)\n")
    )
    launcher = Launcher.__new__(Launcher)
    launcher.say = lambda line: None
    assert child.loading_model is False
    Launcher.read(launcher, child)
    assert child.loading_model is True
