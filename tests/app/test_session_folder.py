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
