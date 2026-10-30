"""T2 / #64: the folder reader's damage and strictness contract."""

import json
from dataclasses import FrozenInstanceError

import pytest

from services.edge.session.folder import (
    SessionDamaged,
    find_sessions,
    mark_interrupted,
    read_run,
    read_session,
)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "truncated",
        "list",
        "null-status",
        "events-shape",
        "event-shape",
        "runs-shape",
        "no-folder",
        "missing-run",
        "ready-missing",
        "ready-null",
        "counts-null",
        "bom",
    ],
)
def test_T2_damage_table(tmp_path, damage):
    folder = tmp_path / "session"
    run_dir = folder / "runs" / "last"
    run_dir.mkdir(parents=True)
    session = {"session_id": "s", "status": "ended", "events": [], "runs": ["last"]}
    run = {"ready": {}, "counts": {"captured": 1}}
    if damage == "null-status":
        session["status"] = None
    elif damage == "events-shape":
        session["events"] = {}
    elif damage == "event-shape":
        session["events"] = [None, {"kind": "error"}]
    elif damage == "runs-shape":
        session["runs"] = {}
    elif damage == "no-folder":
        session["runs"] = ["absent"]
    elif damage == "ready-missing":
        del run["ready"]
    elif damage == "ready-null":
        run["ready"] = None
    elif damage == "counts-null":
        run["counts"] = None
    contents = {"empty": "", "truncated": "{", "list": "[]"}.get(damage, json.dumps(session))
    if damage != "missing":
        (folder / "session.json").write_text(
            contents, encoding="utf-8-sig" if damage == "bom" else "utf-8"
        )
    if damage != "missing-run":
        (run_dir / "run.json").write_text(
            json.dumps(run), encoding="utf-8-sig" if damage == "bom" else "utf-8"
        )
    snapshot = read_session(folder)
    run_snapshot = read_run(run_dir)
    assert isinstance(snapshot.problems, tuple)
    assert isinstance(run_snapshot.problems, tuple)
    if damage in {"missing", "empty", "truncated", "list"}:
        assert snapshot.status is None
        with pytest.raises(SessionDamaged, match="session damaged"):
            snapshot.require("status")
    elif damage == "bom":
        assert snapshot.require("status")["status"] == "ended"
        assert run_snapshot.require("ready")["ready"] == {}
    elif damage == "missing-run":
        assert run_snapshot.problems
        with pytest.raises(SessionDamaged, match="session damaged"):
            run_snapshot.require()
    elif damage in {"ready-missing", "ready-null", "counts-null"}:
        field = "counts" if damage == "counts-null" else "ready"
        assert getattr(run_snapshot, field) is None
        with pytest.raises(SessionDamaged, match="session damaged"):
            run_snapshot.require(field)
    else:
        assert snapshot.problems
    if damage == "event-shape":
        assert len(snapshot.events) == 1
    with pytest.raises((FrozenInstanceError, AttributeError)):
        snapshot.status = "running"


def test_T2_snapshot_is_deeply_immutable_and_detached(tmp_path):
    (tmp_path / "session.json").write_text(json.dumps({"events": [{"kind": "error"}], "runs": []}))
    snapshot = read_session(tmp_path)
    with pytest.raises(TypeError):
        snapshot.events[0]["kind"] = "changed"
    copy = snapshot.document()
    copy["events"][0]["kind"] = "changed"
    assert snapshot.events[0]["kind"] == "error"


def test_T2_discovery_latest_and_recovery(tmp_path):
    folder = tmp_path / "s"
    for name in ["z-first", "a-last"]:
        run_dir = folder / "runs" / name
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text('{"ready": {}}')
    (folder / "session.json").write_text(
        json.dumps(
            {
                "session_id": "id",
                "group_id": "group",
                "status": "running",
                "runs": ["z-first", "a-last"],
                "events": [],
                "unknown": {"keep": True},
            }
        ),
        encoding="utf-8-sig",
    )
    snapshot = read_session(folder)
    assert snapshot.latest_run.path.name == "a-last"
    assert find_sessions(tmp_path, session_id="id")[0].path == folder
    assert find_sessions(tmp_path, group_id="group")[0].path == folder
    assert mark_interrupted(snapshot) == ()
    assert snapshot.status == "running"
    recovered = read_session(folder)
    assert recovered.status == "interrupted"
    assert recovered.events[-1]["kind"] == "interrupted"
    assert recovered.document()["unknown"] == {"keep": True}
    assert mark_interrupted(recovered) == ()
    assert len(read_session(folder).events) == 1


@pytest.mark.parametrize(
    "contents", ["", "{", "[]", "null", '{"extra":' + "[" * 600 + "0" + "]" * 600 + "}"]
)
@pytest.mark.parametrize(
    "reader,filename", [(read_session, "session.json"), (read_run, "run.json")]
)
def test_T2_unreadable_objects_never_raise(tmp_path, contents, reader, filename):
    (tmp_path / filename).write_text(contents, encoding="utf-8")
    snapshot = reader(tmp_path)
    assert snapshot.data is None and snapshot.problems
    with pytest.raises(SessionDamaged, match="session damaged"):
        snapshot.require()


def test_T2_latest_run_agrees_across_callers_and_does_not_fall_back(tmp_path):
    import shutil

    from services.app.server import session_row
    from services.edge.launcher_impl import processed_fps
    from services.edge.reports.cli import report_session
    from services.edge.reports.movement import Params
    from services.edge.score import run_dir
    from tests.edge.test_report import dense, make_run

    first = make_run(tmp_path, dense(5), [])
    folder = first.parent.parent
    last = first.parent / "000-last"
    shutil.copytree(first, last)
    # An empty final run must be displayed instead of borrowing the earlier run's FPS.
    frames = last / "frames.csv"
    frames.write_text(frames.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    session["runs"].append(last.name)
    (folder / "session.json").write_text(json.dumps(session), encoding="utf-8-sig")
    value = json.loads((last / "run.json").read_text(encoding="utf-8"))
    (last / "run.json").write_text(json.dumps(value), encoding="utf-8-sig")
    assert run_dir(folder, None) == last
    assert processed_fps(folder) == "-"
    assert session_row(folder)["fps"] is None
    assert "processed" in report_session(folder, None, Params())
    (last / "run.json").unlink()
    row = session_row(folder)
    assert row["fps"] is None and any("run.json" in problem for problem in row["missing"])
    with pytest.raises(SessionDamaged):
        report_session(folder, None, Params())


@pytest.mark.parametrize("runs", [["../escape"], [None], ["ok", {}]])
def test_T2_invalid_run_names_are_refused_by_strict_lookup(tmp_path, runs):
    from services.edge.session.folder import run_paths

    (tmp_path / "session.json").write_text(json.dumps({"runs": runs}), encoding="utf-8")
    snapshot = read_session(tmp_path)
    assert snapshot.problems
    with pytest.raises(SessionDamaged):
        run_paths(tmp_path)


def test_T2_recovery_keeps_damaged_event_evidence(tmp_path):
    contents = '{"status": "running", "events": [null]}'
    (tmp_path / "session.json").write_text(contents, encoding="utf-8")
    assert mark_interrupted(read_session(tmp_path))
    assert (tmp_path / "session.json").read_text(encoding="utf-8") == contents


def test_T2_bom_replay_lookup_and_group_run_metadata(clips, tmp_path):
    from services.edge.replay.group import resolve_group
    from services.edge.replay.resolve import resolve_replay
    from tests.edge.test_group_replay import NEAR, Scripted, record_group

    out = record_group(clips, tmp_path, Scripted(NEAR))
    for snapshot in find_sessions(out):
        for path in [snapshot.path / "session.json", snapshot.runs[0].path / "run.json"]:
            contents = path.read_text(encoding="utf-8")
            path.write_text(contents, encoding="utf-8-sig")
        target = resolve_replay(snapshot.get("session_id"), out)
        assert target.session_dir == snapshot.path.resolve()
    group = resolve_group("g1", out)
    assert [camera.camera_id for camera in group.cameras] == ["cam1", "cam2"]


def test_T2_recovery_preserves_malformed_unrelated_fields_and_checks_current_status(tmp_path):
    contents = {"status": "running", "events": [], "runs": {}, "source": ["damaged"]}
    file = tmp_path / "session.json"
    file.write_text(json.dumps(contents), encoding="utf-8")
    snapshot = read_session(tmp_path)
    assert mark_interrupted(snapshot) == ()
    recovered = json.loads(file.read_text(encoding="utf-8"))
    assert recovered["runs"] == {} and recovered["source"] == ["damaged"]
    assert mark_interrupted(snapshot) == ()  # a stale snapshot must not add a second event
    assert len(json.loads(file.read_text(encoding="utf-8"))["events"]) == 1
