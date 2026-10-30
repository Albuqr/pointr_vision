"""Issue #54 / B1: non-object session JSON cannot hide healthy sibling sessions.

Kept in lane S's tests/app ownership; replay and reports use their real entry points.
All footage is synthetic and detection is disabled.
"""

import json

import pytest
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.replay.resolve import ReplayError, resolve_replay
from services.edge.reports.cli import main as report_main
from tests.app.test_api import FakeLauncher
from tests.app.test_camera_state import open_session, start_two
from tests.edge.test_replay import record, run_cli


@pytest.fixture(
    params=[[], "damaged session", None, 7, False], ids=["list", "string", "null", "number", "bool"]
)
def damaged_json(request):
    return json.dumps(request.param)


def write_session(folder, contents):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "session.json").write_text(contents, encoding="utf-8")
    return folder


def test_B1_startup_recovers_owned_group_beside_non_object_session(tmp_path, damaged_json):
    out = tmp_path / "sessions"
    damaged = write_session(out / "000-damaged", damaged_json)
    owned = write_session(
        out / "good",
        json.dumps({"group_id": "owned", "status": "running", "events": []}),
    )
    pointer = tmp_path / "active_group.json"
    pointer.write_text('{"group_id": "owned"}', encoding="utf-8")
    app = create_app(str(out), CameraConfig(tmp_path / "config.json"), FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        assert client.get("/api/status").status_code == 200
        response = client.get("/api/sessions")
        assert response.status_code == 200
        row = next(row for row in response.json() if row["folder"] == damaged.name)
        assert any("not a JSON object" in problem for problem in row["missing"])
    recovered = json.loads((owned / "session.json").read_text(encoding="utf-8"))
    assert recovered["status"] == "interrupted"
    assert recovered["events"][-1]["kind"] == "interrupted"
    assert not pointer.exists()
    assert (damaged / "session.json").read_text(encoding="utf-8") == damaged_json


def test_B1_recording_status_describes_non_object_session(tmp_path, damaged_json):
    app = create_app(
        str(tmp_path / "sessions"), CameraConfig(tmp_path / "config.json"), FakeLauncher
    )
    with TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        first, second = start_two(client)
        open_session(first, tmp_path)
        write_session(first.session_dir, damaged_json)
        open_session(second, tmp_path, ready={"first_frame": "t"})
        response = client.get("/api/status")
        assert response.status_code == 200, response.text
        cameras = {camera["camera_id"]: camera for camera in response.json()["cameras"]}
        assert cameras["cam1"]["state"] == "error"
        assert "session.json" in cameras["cam1"]["error"]
        assert "not a JSON object" in cameras["cam1"]["error"]
        assert cameras["cam2"]["state"] == "recording"
        assert (first.session_dir / "session.json").read_text(encoding="utf-8") == damaged_json


@pytest.fixture
def recorded_siblings(clips, tmp_path, damaged_json):
    out = tmp_path / "sessions"
    folder = record(clips, out)
    good = folder.rename(out / "zzz-good")
    session_file = good / "session.json"
    session = json.loads(session_file.read_text(encoding="utf-8"))
    session.update(group_id="good-group", camera_id="cam1")
    session_file.write_text(json.dumps(session), encoding="utf-8")
    damaged = write_session(out / "000-damaged", damaged_json)
    return out, good, session, damaged


@pytest.mark.parametrize("target_kind", ["group", "session"])
def test_B1_replay_entry_point_finds_good_session(recorded_siblings, target_kind):
    out, good, session, damaged = recorded_siblings
    before = (damaged / "session.json").read_bytes()
    target = session["group_id"] if target_kind == "group" else session["session_id"]
    result = run_cli(out, "--replay", target)
    assert result.returncode == 0, result.stdout + result.stderr
    updated = json.loads((good / "session.json").read_text(encoding="utf-8"))
    assert len(updated["runs"]) == 2
    run = json.loads((good / "runs" / updated["runs"][-1] / "run.json").read_text("utf-8"))
    assert run["mode"] == "replay"
    assert (damaged / "session.json").read_bytes() == before


def test_B1_reports_entry_point_finds_good_session(recorded_siblings, capsys):
    out, good, session, _ = recorded_siblings
    assert report_main(["--group", session["group_id"], "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert "1 camera(s)" in captured.out
    assert good.name in captured.out
    assert not captured.err
    assert (good / "runs" / session["runs"][0] / "report.json").is_file()


def test_B1_explicit_damaged_replay_folder_reports_reason(tmp_path, damaged_json):
    damaged = write_session(tmp_path / "damaged", damaged_json)
    with pytest.raises(ReplayError, match="not a JSON object"):
        resolve_replay(str(damaged), tmp_path)
