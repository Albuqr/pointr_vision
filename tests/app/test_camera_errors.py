"""Studio keeps each camera's last error and recent events, masked, until dismissed (backend
side of the persistent error panel; the status payload is what a reloaded page reads)."""

import json
import time
from collections import deque
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from services.app.camera_log import EVENT_LIMIT
from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.launcher_impl import Child, Launcher
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
        assert camera(client)["recent_events"][0]["kind"] == "source_open_failed"
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


def test_frame_size_errors_are_named_in_the_camera_event_log(tmp_path):
    with make_client(tmp_path) as client:
        client.post("/api/recording/start")
        child = FakeLauncher.instances[-1].children[0]
        child.session_dir = tmp_path / "session-size"
        child.session_dir.mkdir()
        (child.session_dir / "session.json").write_text(
            json.dumps(
                {
                    "status": "running",
                    "events": [
                        {
                            "t_wall": "2026-10-14T12:00:00Z",
                            "t_mono": 1,
                            "kind": "error",
                            "detail": "frame size 640x480 differs from 1280x720",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        assert camera(client)["recent_events"][0]["kind"] == "frame_size_mismatch"


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


def test_a_corrupt_calibration_does_not_refuse_the_group_and_lands_in_the_event_log(
    two_cameras,
):
    """Merged with the calibration branch: one camera's bad calibration starts that camera
    uncalibrated (no 422 for the group), says why in its warning, and logs an event."""
    client = two_cameras
    studio = client.app.state.studio
    folder = studio.calibrations.camera_dir("cam2")
    folder.mkdir(parents=True)
    (folder / "active.json").write_text('{"calibration_id": "', encoding="utf-8")
    started = client.post("/api/recording/start")
    assert started.status_code == 200, started.text
    cam1, cam2 = camera(client, "cam1"), camera(client, "cam2")
    assert cam1["calibration_warning"] is None and cam1["recent_events"] == []
    assert "without calibration" in cam2["calibration_warning"]
    assert [e["kind"] for e in cam2["recent_events"]] == ["calibration_not_used"]


def test_a_camera_with_an_error_but_no_process_is_listed_in_idle_cameras(two_cameras):
    client = two_cameras
    studio = client.app.state.studio
    studio.log("cam2").set_error("Start refused.", "the reason")
    idle = client.get("/api/status").json()["idle_cameras"]
    assert [item["camera_id"] for item in idle] == ["cam2"]
    assert idle[0]["last_error"]["message"] == "Start refused."
    client.delete("/api/cameras/cam2/error")
    assert client.get("/api/status").json()["idle_cameras"] == []


# -- B2: an error printed mid-run is not a start failure --------------------------------------


def real_children(cameras, lines):
    """Real launcher children fed through the real Launcher.read, process still alive."""
    children = [Child(c) for c in cameras]
    stdout = [line + "\n" for line in lines]
    proc = SimpleNamespace(stdout=stdout, poll=lambda: None, returncode=None)
    for child in children:
        child.proc = proc
    Launcher(cameras, SimpleNamespace()).read(*children)
    return children


class RealChildLauncher(FakeLauncher):
    def run(self):  # real children's `running` follows their proc and cannot be assigned
        self.event.wait()
        return 0


def make_session(root, camera_id):
    folder = root / camera_id
    (folder / "runs" / "r1").mkdir(parents=True)
    (folder / "session.json").write_text(
        json.dumps({"camera_id": camera_id, "status": "running", "events": [], "runs": ["r1"]}),
        encoding="utf-8",
    )
    (folder / "runs" / "r1" / "run.json").write_text(
        json.dumps({"ready": {"first_frame": "2026-10-30T00:00:00Z"}}), encoding="utf-8"
    )
    return folder


def launcher_with(tmp_path, lines):
    """A two-camera group whose process printed both session lines, then `lines`."""
    folders = {c: make_session(tmp_path / "s", c) for c in ("cam1", "cam2")}

    class GroupLauncher(RealChildLauncher):
        def __init__(self, cameras, options):
            super().__init__(cameras, options)
            tagged = [f"[{c}] session: {folder}" for c, folder in folders.items()]
            self.children = real_children(cameras, [*tagged, *lines])

    return GroupLauncher


def test_b2_a_run_error_keeps_the_camera_recording_and_is_logged_once(tmp_path):
    line = "error: final session files could not be written"
    factory = launcher_with(tmp_path, [line])
    with make_client(tmp_path, factory, ("cam1", "cam2")) as client:
        client.post("/api/recording/start")
        for _ in range(3):  # polling again must not duplicate
            cams = [camera(client, c) for c in ("cam1", "cam2")]
        audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        for cam in cams:
            assert cam["state"] == "recording"
            assert "while recording" in cam["last_error"]["message"]
            assert "final session files could not be written" in cam["last_error"]["detail"]
            kinds = [e["kind"] for e in cam["recent_events"]]
            assert kinds == ["error"]
            assert "final session files could not be written" in cam["recent_events"][0]["detail"]
        assert "could not start recording" not in audit
        assert "while recording" in audit


def test_b2_an_error_before_the_session_line_is_still_a_start_failure(tmp_path):
    class StartFailLauncher(RealChildLauncher):
        def __init__(self, cameras, options):
            super().__init__(cameras, options)
            folder = make_session(tmp_path / "s", "cam2")
            lines = ["error: cannot open source", f"[cam2] session: {folder}"]
            self.children = real_children(cameras, lines)
            self.children[0].proc = SimpleNamespace(poll=lambda: 3, returncode=3)

    with make_client(tmp_path, StartFailLauncher, ("cam1", "cam2")) as client:
        client.post("/api/recording/start")
        cam1 = camera(client, "cam1")
        assert cam1["state"] == "error"
        assert cam1["last_error"]["message"] == "The camera could not start recording."
