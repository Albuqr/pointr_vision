"""B2: every Studio action and error is one masked entry in audit.jsonl next to cameras.json."""

import json

from starlette.testclient import TestClient

from services.app.audit import AuditTrail
from services.app.config import CameraConfig
from services.app.server import create_app
from tests.app.test_api import FakeLauncher

SECRET_URL = "rtsp://admin:hunter2@192.168.1.5:554/stream?token=abc123"


def make_client(tmp_path):
    FakeLauncher.instances.clear()
    config = CameraConfig(tmp_path / "config.json")
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234))
    return client, tmp_path / "audit.jsonl"


def camera(camera_id="cam1", source=SECRET_URL):
    return {"camera_id": camera_id, "source": source, "link": "wifi"}


def entries(path, actions_only=False):
    found = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [e for e in found if e["action"] != "error"] if actions_only else found


def test_each_action_writes_one_entry_with_time_action_camera_and_outcome(tmp_path, monkeypatch):
    client, path = make_client(tmp_path)
    with client:
        studio = client.app.state.studio
        monkeypatch.setattr(studio, "calibration_fit", lambda *args, **kwargs: {"saved": True})
        monkeypatch.setattr(studio, "test_camera", lambda camera_id: {"error": None})
        assert client.post("/api/cameras", json=camera()).status_code == 200
        edited = {**camera(), "name": "Court"}
        assert client.put("/api/cameras/cam1", json=edited).status_code == 200
        client.post("/api/cameras/cam1/test")
        client.put("/api/cameras/cam1/calibration", json={})
        client.post("/api/recording/start")
        client.post("/api/recording/stop")
        client.delete("/api/cameras/cam1")
    written = entries(path, actions_only=True)  # FakeLauncher's children end without an exit code
    assert [(e["action"], e["camera_id"], e["outcome"]) for e in written] == [
        ("camera_add", "cam1", "ok"),
        ("camera_edit", "cam1", "ok"),
        ("camera_test", "cam1", "ok"),
        ("calibration_save", "cam1", "ok"),
        ("recording_start", None, "ok"),
        ("recording_stop", None, "ok"),
        ("camera_remove", "cam1", "ok"),
    ]
    assert all(e["t_wall"].endswith("Z") for e in written)


def test_start_records_the_settings_it_started_from(tmp_path):
    client, path = make_client(tmp_path)
    with client:
        client.post("/api/cameras", json={**camera(), "det_size": 640, "fps_cap": 15})
        client.post("/api/recording/start")
        client.post("/api/recording/stop")
    start = next(e for e in entries(path) if e["action"] == "recording_start")
    [started] = start["detail"]["cameras"]
    assert (started["camera_id"], started["det_size"], started["fps_cap"]) == ("cam1", 640, 15)
    assert start["detail"]["group_id"]


def test_a_refused_action_writes_its_error_as_the_outcome_masked(tmp_path):
    client, path = make_client(tmp_path)
    with client:
        refused = client.post("/api/cameras", json=camera(source="http://127.0.0.1/stream"))
        assert refused.status_code == 422
        assert client.post("/api/recording/start").status_code == 422
        assert client.put("/api/cameras/ghost", json=camera("ghost")).status_code == 404
        assert client.put("/api/cameras/cam1/calibration", json={}).status_code == 409
    add, start, edit, save = entries(path)
    assert (add["action"], add["camera_id"]) == ("camera_add", "cam1")
    assert "loopback and link-local camera URLs are not allowed" in add["outcome"]
    assert start["outcome"] == "add at least one camera"
    assert edit["outcome"] == "camera not found"
    assert save["outcome"] == "capture a fresh frame before fitting or saving"


def test_a_failed_camera_test_is_an_error_outcome_and_no_secret_reaches_the_file(tmp_path):
    client, path = make_client(tmp_path)
    with client:
        studio = client.app.state.studio
        client.post("/api/cameras", json=camera())
        studio.test_camera = lambda camera_id: {"error": f"cannot open {SECRET_URL}"}
        client.post("/api/cameras/cam1/test")
        studio.log("cam1").set_error("The camera test failed.", f"source: {SECRET_URL}")
    text = path.read_text(encoding="utf-8")
    for secret in ("hunter2", "abc123"):
        assert secret not in text
    test, error = entries(path)[1:]
    assert test["action"] == "camera_test" and test["outcome"].startswith("cannot open")
    assert error["action"] == "error" and error["camera_id"] == "cam1"


def test_an_unexpected_exception_is_recorded_and_still_raised(tmp_path):
    client, path = make_client(tmp_path)
    with client:
        studio = client.app.state.studio

        def boom():
            raise RuntimeError("disk gone")

        real_stop = studio.stop
        studio.stop = lambda source=None: boom()
        try:
            client.post("/api/recording/stop")
        except RuntimeError:
            pass
        studio.stop = real_stop  # the app's shutdown calls stop too
    [stop] = entries(path)
    assert stop["action"] == "recording_stop" and stop["outcome"] == "RuntimeError: disk gone"


def test_entries_are_appended_and_a_torn_last_line_leaves_the_rest_readable(tmp_path):
    trail = AuditTrail(tmp_path / "audit.jsonl")
    trail.record("camera_add", "cam1")
    before = trail.path.read_bytes()
    trail.record("camera_edit", "cam1")
    assert trail.path.read_bytes().startswith(before)  # append-only: earlier bytes never change
    with trail.path.open("ab") as handle:
        handle.write(b'{"t_wall": "2026-10-29T10:00:00Z", "action": "camer')  # a crash mid-write
    assert [e["action"] for e in trail.read()] == ["camera_add", "camera_edit"]
    trail.record("camera_remove", "cam1")  # the file is still usable afterwards
    assert trail.read()[-1]["action"] == "camera_remove"


def test_an_unwritable_trail_never_changes_the_action(tmp_path):
    client, path = make_client(tmp_path)
    path.mkdir()  # audit.jsonl is a directory: every write fails
    with client:
        assert client.post("/api/cameras", json=camera()).status_code == 200
        assert client.put("/api/cameras/ghost", json=camera("ghost")).status_code == 404
        assert client.app.state.studio.audit.failed_writes == 2


def test_start_names_the_enabled_cameras_it_skipped_and_why(tmp_path):
    client, path = make_client(tmp_path)
    with client:
        studio = client.app.state.studio
        studio.config.write([camera("cam1"), camera("cam2", "rtsp://u:pw@192.168.1.9/s")])
        real = studio.start

        def start_without_cam2():
            status = real()
            studio.log("cam2").set_error("The camera URL could not be used safely.", "")
            studio.launcher.cameras = [c for c in studio.launcher.cameras if c.camera_id == "cam1"]
            return status

        studio.start = start_without_cam2
        client.post("/api/recording/start")
        studio.start = real
    start = next(e for e in entries(path) if e["action"] == "recording_start")
    assert start["detail"]["skipped"] == [
        {"camera_id": "cam2", "reason": "The camera URL could not be used safely."}
    ]
    assert "pw" not in path.read_text(encoding="utf-8").replace("pwd", "")
