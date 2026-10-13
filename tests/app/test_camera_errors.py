"""Studio keeps each camera's last error and recent events, masked, until dismissed (backend
side of the persistent error panel; the status payload is what a reloaded page reads)."""

import json
import time
from collections import deque

import pytest
from starlette.testclient import TestClient

from services.app.camera_log import EVENT_LIMIT
from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.session.writer import mask_credentials
from tests.app.test_api import FakeLauncher

SECRET_URL = "rtsp://admin:hunter2@192.168.1.5:554/stream?token=abc123"


class Proc:
    returncode = 3


class FailedChild:
    def __init__(self, camera):
        self.cam = camera
        self.session_dir = None
        self.preview_port = camera.http_preview_port
        self.running = False
        self.proc = Proc()
        self.failure = f"cannot open {SECRET_URL}"
        self.tail = deque([f"error: cannot open {SECRET_URL}"], maxlen=20)


class FailingLauncher(FakeLauncher):
    def __init__(self, cameras, options):
        super().__init__(cameras, options)
        self.children = [FailedChild(camera) for camera in cameras]


def make_client(tmp_path, factory=FakeLauncher, cameras=("cam1",)):
    config = CameraConfig(tmp_path / "config.json")
    config.write(
        [
            {
                "camera_id": c,
                "source": SECRET_URL.replace("192.168.1.5", f"192.168.1.{10 + i}"),
                "link": "wifi",
            }
            for i, c in enumerate(cameras)
        ]
    )
    FakeLauncher.instances.clear()
    app = create_app(str(tmp_path / "sessions"), config, factory)
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))


def camera(client, camera_id="cam1"):
    return next(
        c for c in client.get("/api/status").json()["cameras"] if c["camera_id"] == camera_id
    )


def test_error_persists_across_polls_and_a_30_second_clock_advance(tmp_path, monkeypatch):
    with make_client(tmp_path, FailingLauncher) as client:
        client.post("/api/recording/start")
        first = camera(client)["last_error"]
        assert first["message"] and "exit code: 3" in first["detail"] and first["at"]
        real_monotonic, real_time = time.monotonic, time.time
        monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 30)
        monkeypatch.setattr(time, "time", lambda: real_time() + 30)
        for _ in range(5):
            assert camera(client)["last_error"] == first
        assert camera(client)["error"]


def test_dismiss_clears_the_error_and_the_next_start_replaces_it(tmp_path):
    with make_client(tmp_path, FailingLauncher) as client:
        client.post("/api/recording/start")
        assert camera(client)["last_error"]
        assert client.delete("/api/cameras/cam1/error").status_code == 200
        assert camera(client)["last_error"] is None
        assert camera(client)["recent_events"]  # dismissing an error keeps the history
        client.post("/api/recording/stop")
        client.post("/api/recording/start")
        assert camera(client)["last_error"]  # failed again: a fresh error


def test_a_successful_start_clears_the_previous_error(tmp_path):
    with make_client(tmp_path, FailingLauncher) as client:
        client.post("/api/recording/start")
        assert camera(client)["last_error"]
        client.post("/api/recording/stop")
        client.app.state.studio.launcher_factory = FakeLauncher
        client.post("/api/recording/start")
        assert camera(client)["last_error"] is None


def test_events_are_bounded_newest_first_and_read_from_the_session_file(tmp_path):
    with make_client(tmp_path) as client:
        client.post("/api/recording/start")
        child = FakeLauncher.instances[-1].children[0]
        child.session_dir = tmp_path / "session"
        child.session_dir.mkdir()
        events = [
            {"t_wall": f"2026-01-01T00:00:{i % 60:02d}Z", "t_mono": i, "kind": "frozen_frames",
             "detail": f"event {i} {SECRET_URL}"}
            for i in range(EVENT_LIMIT + 30)
        ]  # fmt: skip
        (child.session_dir / "session.json").write_text(
            json.dumps({"status": "running", "events": events}), encoding="utf-8"
        )
        shown = camera(client)["recent_events"]
        assert len(shown) == EVENT_LIMIT
        assert shown[0]["detail"].startswith(f"event {EVENT_LIMIT + 29} ")
        assert shown[-1]["detail"].startswith("event 30 ")
        for _ in range(3):  # polling again must not duplicate
            assert len(camera(client)["recent_events"]) == EVENT_LIMIT
        # a new "page load" (fresh request, no client state) sees the same list
        assert camera(client)["recent_events"] == shown


def test_credentials_are_masked_everywhere_in_status(tmp_path):
    with make_client(tmp_path, FailingLauncher) as client:
        client.post("/api/recording/start")
        payload = json.dumps(client.get("/api/status").json())
        for secret in ("hunter2", "abc123", "admin:"):
            assert secret not in payload
        assert "***@" in payload


def test_mask_credentials_handles_urls_and_query_secrets():
    assert mask_credentials("open rtsp://u:p@h:1/x failed") == "open rtsp://***@h:1/x failed"
    assert mask_credentials("http://h/a?password=p&x=1") == "http://h/a?password=***&x=1"
    assert mask_credentials("no secret here") == "no secret here"


@pytest.fixture
def two_cameras(tmp_path):
    with make_client(tmp_path, FakeLauncher, ("cam1", "cam2")) as client:
        yield client


def test_refused_start_names_the_camera_and_keeps_the_other_state(two_cameras, tmp_path):
    client = two_cameras
    studio = client.app.state.studio
    client.post("/api/recording/start")
    group = studio.group_id
    for child in FakeLauncher.instances[-1].children:  # each camera ended cleanly
        child.session_dir = tmp_path / child.cam.camera_id
        child.session_dir.mkdir()
        (child.session_dir / "session.json").write_text(
            json.dumps({"status": "ended", "events": []}), encoding="utf-8"
        )
    studio.final = {"cam1": {"summary": "earlier"}}
    client.post("/api/recording/stop")
    folder = studio.calibrations.camera_dir("cam2")
    folder.mkdir(parents=True)
    (folder / "active.json").write_text('{"calibration_id": "', encoding="utf-8")
    refused = client.post("/api/recording/start")
    assert refused.status_code == 422 and "cam2" in refused.text
    status = client.get("/api/status").json()
    assert status["group_id"] == group  # nothing was reset by the refusal
    assert status["final"] == {"cam1": {"summary": "earlier"}}
    assert {c["camera_id"] for c in status["cameras"]} == {"cam1", "cam2"}
    assert status["cameras"][0]["last_error"] is None
    folder_error = camera(client, "cam2")["last_error"]
    assert folder_error["message"].startswith("Start refused") and "cam2" in folder_error["detail"]


def test_refused_start_with_no_previous_group_shows_in_idle_cameras(two_cameras):
    client = two_cameras
    folder = client.app.state.studio.calibrations.camera_dir("cam2")
    folder.mkdir(parents=True)
    (folder / "active.json").write_text("not json", encoding="utf-8")
    assert client.post("/api/recording/start").status_code == 422
    idle = client.get("/api/status").json()["idle_cameras"]
    assert [item["camera_id"] for item in idle] == ["cam2"]
    assert idle[0]["last_error"]["message"].startswith("Start refused")
    client.delete("/api/cameras/cam2/error")
    assert client.get("/api/status").json()["idle_cameras"] == []
