"""Phase 03 B1 (D-049): Studio's stop ends every camera's session normally. R2a 04: a group is one
process, a camera alone its own. The real launcher and real camera processes on synthetic clips,
detection off: no camera, no weights."""

import dataclasses
import json
import time
from pathlib import Path

from jsonschema import Draft202012Validator
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.launcher_impl import Launcher

ROOT = Path(__file__).resolve().parents[2]
SESSION_SCHEMA = json.loads((ROOT / "contracts" / "session.schema.json").read_text("utf-8"))
RUN_SCHEMA = json.loads((ROOT / "contracts" / "run.schema.json").read_text("utf-8"))
REPORT_SCHEMA = json.loads((ROOT / "contracts" / "report.schema.json").read_text("utf-8"))


RECORDING = ("recording", "preview_ready")


def no_detect_launcher(cameras, options):
    return Launcher(cameras, dataclasses.replace(options, no_detect=True))


def test_a_studio_stop_ends_each_session_normally(tmp_path, long_clips):
    config = CameraConfig(tmp_path / "config.json")
    config.write(
        [
            {"camera_id": f"cam{i + 1}", "source": str(clip), "link": "file"}
            for i, clip in enumerate(long_clips)
        ]
    )
    out = tmp_path / "sessions"
    app = create_app(str(out), config, no_detect_launcher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        assert client.post("/api/recording/start").status_code == 200
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            cameras = client.get("/api/status").json()["cameras"]
            if len(cameras) == 2 and all(c["state"] in RECORDING for c in cameras):
                break
            time.sleep(0.2)
        assert all(c["state"] in RECORDING for c in cameras), cameras
        assert all(c["preview_port"] for c in cameras)  # each camera serves its own preview
        # R2a 04: the group is one process, the one detector's (ADR 0007)
        [process] = {child.proc for child in app.state.studio.launcher.children}
        assert "services.edge.group_main" in process.args
        time.sleep(1.0)  # some frames in each session
        assert client.post("/api/recording/stop").json()["running"] is False

    folders = sorted(out.glob("cam*_*"))
    assert [f.name.split("_")[0] for f in folders] == ["cam1", "cam2"]
    for folder in folders:
        session = json.loads((folder / "session.json").read_text("utf-8"))
        Draft202012Validator(SESSION_SCHEMA).validate(session)
        assert session["status"] == "ended" and session["ended_at"]
        kinds = [e["kind"] for e in session["events"]]
        assert kinds.count("stopped") == 1 and "interrupted" not in kinds
        [stop] = [e for e in session["events"] if e["kind"] == "stopped"]
        assert stop["detail"].startswith("ui:") and stop["t_mono"] is not None
        [run_dir] = (folder / "runs").iterdir()
        run = json.loads((run_dir / "run.json").read_text("utf-8"))
        Draft202012Validator(RUN_SCHEMA).validate(run)
        assert run["ended_at"] and run["counts"]["processed"] > 0
        report = json.loads((run_dir / "report.json").read_text("utf-8"))
        Draft202012Validator(REPORT_SCHEMA).validate(report)


def test_a_camera_without_a_group_runs_as_before(tmp_path, long_clips):
    config = CameraConfig(tmp_path / "config.json")
    config.write([{"camera_id": "cam1", "source": str(long_clips[0]), "link": "file"}])
    out = tmp_path / "sessions"
    app = create_app(str(out), config, no_detect_launcher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        assert client.post("/api/recording/start").status_code == 200
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            [camera] = client.get("/api/status").json()["cameras"]
            if camera["state"] in RECORDING:
                break
            time.sleep(0.2)
        assert camera["state"] in RECORDING and camera["preview_port"], camera
        [child] = app.state.studio.launcher.children
        assert "services.edge.main" in child.proc.args
        assert client.post("/api/recording/stop").json()["running"] is False
    [folder] = out.glob("cam1_*")
    session = json.loads((folder / "session.json").read_text("utf-8"))
    assert session["status"] == "ended"
    [run_dir] = (folder / "runs").iterdir()
    assert json.loads((run_dir / "run.json").read_text("utf-8"))["group"] is None  # no group run
