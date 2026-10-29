"""B7: /api/sessions returns the readable fields of each session, from its files only.

The Studio page renders these fields; its visual check is manual (see PHASE_03.md B7)."""

import json
from collections import Counter
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from tests.edge.test_report import dense, make_run

SOURCE = Path(__file__).resolve().parents[2] / "services/app/ui/src/studio.tsx"
EVENTS = [
    {"t_wall": "2026-10-13T12:00:10Z", "t_mono": 10.0, "kind": "source_lost", "detail": "x"},
    {"t_wall": "2026-10-13T12:00:12Z", "t_mono": 12.0, "kind": "source_recovered", "detail": "x"},
    {"t_wall": "2026-10-13T12:00:20Z", "t_mono": 20.0, "kind": "source_lost", "detail": "y"},
]


@pytest.fixture
def studio(tmp_path):
    out = tmp_path / "sessions"
    out.mkdir()
    app = create_app(str(out), CameraConfig(tmp_path / "config.json"))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        yield client, out


def rows_by_folder(client):
    response = client.get("/api/sessions")
    assert response.status_code == 200
    return {row["folder"]: row for row in response.json()}


def edit_session(folder, **changes):
    path = folder / "session.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(changes)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_a_session_lists_time_camera_duration_fps_drops_events_and_status(studio):
    client, out = studio
    run_dir = make_run(out, dense(5), [(0, 1, 0, 0)], events=EVENTS)
    row = rows_by_folder(client)[run_dir.parent.parent.name]
    assert row["camera_id"] == "cam1" and row["status"] == "ended"
    assert row["started_at"].endswith("Z")
    assert row["duration"] > 0
    assert row["fps"] > 0
    assert (row["captured"], row["dropped"]) == (20, 15)
    assert row["drop_rate"] == pytest.approx(75.0)
    assert row["events"] == dict(Counter(e["kind"] for e in EVENTS))
    assert row["missing"] == []


def test_sessions_are_listed_newest_first(studio):
    client, out = studio
    older = make_run(out, dense(3), [], camera_id="cam1").parent.parent
    newer = make_run(out, dense(3), [], camera_id="cam2").parent.parent
    edit_session(older, started_at="2026-10-01T10:00:00Z", ended_at="2026-10-01T10:09:00Z")
    edit_session(newer, started_at="2026-10-02T10:00:00Z", ended_at="2026-10-02T10:09:00Z")
    assert [r["folder"] for r in client.get("/api/sessions").json()] == [newer.name, older.name]


def test_a_session_without_a_report_is_listed_and_says_what_is_missing(studio):
    client, out = studio
    folder = make_run(out, dense(5), [], events=EVENTS).parent.parent
    for path in (folder / "runs").rglob("run.json"):
        path.unlink()
    row = rows_by_folder(client)[folder.name]
    assert row["status"] == "ended" and row["camera_id"] == "cam1"
    assert row["events"] == dict(Counter(e["kind"] for e in EVENTS))
    assert row["fps"] is None and row["dropped"] is None
    assert any("run.json" in item for item in row["missing"])


def test_a_session_with_an_unreadable_report_is_listed_and_says_so(studio):
    client, out = studio
    run_dir = make_run(out, dense(5), [])
    (run_dir / "run.json").write_text("{not json", encoding="utf-8")
    row = rows_by_folder(client)[run_dir.parent.parent.name]
    assert row["status"] == "ended" and row["fps"] is None
    assert row["missing"]


def test_a_session_with_no_runs_says_so(studio):
    client, out = studio
    folder = make_run(out, dense(5), []).parent.parent
    edit_session(folder, runs=[])
    assert any("no run" in item for item in rows_by_folder(client)[folder.name]["missing"])


def test_an_unreadable_session_json_is_still_listed(studio):
    client, out = studio
    broken = out / "cam9_broken"
    broken.mkdir()
    (broken / "session.json").write_text("{truncated", encoding="utf-8")
    row = rows_by_folder(client)["cam9_broken"]
    assert row["status"] is None and row["fps"] is None
    assert any("session.json" in item for item in row["missing"])


def test_a_bad_time_or_shape_in_session_json_does_not_crash_the_list(studio):
    client, out = studio
    bad_time = out / "bad_time"
    bad_time.mkdir()
    (bad_time / "session.json").write_text(
        json.dumps({"status": "ended", "started_at": "yesterday", "runs": [], "events": None}),
        encoding="utf-8",
    )
    not_an_object = out / "not_object"
    not_an_object.mkdir()
    (not_an_object / "session.json").write_text("[1, 2]", encoding="utf-8")
    rows = rows_by_folder(client)
    assert rows["bad_time"]["duration"] is None
    assert any("started_at" in item for item in rows["bad_time"]["missing"])
    assert rows["not_object"]["missing"]


def test_folders_without_session_json_are_not_sessions(studio):
    client, out = studio
    (out / "notes").mkdir()
    assert client.get("/api/sessions").json() == []


def test_the_page_reads_the_fields_the_api_returns():
    page = SOURCE.read_text(encoding="utf-8").split('page === "Sessions"', 1)[1]
    for field in ("started_at", "duration", "fps", "dropped", "drop_rate", "events", "missing"):
        assert f"session.{field}" in page
    assert "session.summary" not in page
