"""One tolerant view of session-folder metadata (D-065).

Snapshots contain only immutable values. Missing or malformed fields are None;
problems describe damage without making tolerant reads raise. Strict consumers
require only the fields they need. JSON text always accepts a UTF-8 BOM.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from services.edge.capture.types import utc_now


class SessionDamaged(ValueError):
    """A required part of a session folder cannot be read."""


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _snapshot_data(value, problems, filename):
    try:
        return _freeze(value)
    except RecursionError:
        problems.append(f"{filename}: JSON nesting is too deep")
        return None


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _name(value):
    return (
        isinstance(value, str)
        and value not in ("", ".", "..")
        and not any(char in value for char in "/\\:")
    )


@dataclass(frozen=True)
class Snapshot:
    path: Path
    data: Mapping[str, Any] | None
    problems: tuple[str, ...]

    def get(self, field, default=None):
        return self.data.get(field, default) if self.data is not None else default

    def document(self) -> dict:
        """An independent mutable copy for existing report/UI consumers."""
        return _thaw(self.data) if self.data is not None else {}

    def require(self, *fields: str) -> dict:
        """Require a readable object and the named fields, raising one damage error.

        Unrelated optional fields may be absent or damaged. With no field names,
        only the top-level JSON object is required.
        """
        missing = [field for field in fields if self.get(field) is None]
        if self.data is None or missing:
            reasons = list(self.problems) + [f"{field} not recorded" for field in missing]
            raise SessionDamaged(f"session damaged: {'; '.join(reasons)} ({self.path})")
        return self.document()

    @property
    def status(self):
        return self.get("status")

    @property
    def events(self):
        return self.get("events")

    @property
    def ready(self):
        return self.get("ready")

    @property
    def counts(self):
        return self.get("counts")


@dataclass(frozen=True)
class RunSnapshot(Snapshot):
    pass


@dataclass(frozen=True)
class SessionSnapshot(Snapshot):
    runs: tuple[RunSnapshot | None, ...] | None

    @property
    def latest_run(self) -> RunSnapshot | None:
        """The final listed run, even when earlier runs are healthier."""
        return self.runs[-1] if self.runs else None


def _read(path: Path, filename: str):
    try:
        value = json.loads((path / filename).read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("not a JSON object")
        return value, []
    except (OSError, ValueError, RecursionError) as error:
        return None, [f"{filename}: {error}"]


def _field(value, key, kind, problems, filename):
    item = value.get(key)
    if not isinstance(item, kind):
        value[key] = None
        problems.append(f"{filename}: {key} not readable")


def read_run(path: Path | str) -> RunSnapshot:
    path = Path(path)
    value, problems = _read(path, "run.json")
    if value is not None:
        for key in ("ready", "counts", "calibration", "group", "capture", "detection", "recording"):
            if key in ("ready", "counts") or value.get(key) is not None:
                _field(value, key, dict, problems, "run.json")
    return RunSnapshot(path, _snapshot_data(value, problems, "run.json"), tuple(problems))


def read_session(path: Path | str) -> SessionSnapshot:
    path = Path(path)
    value, problems = _read(path, "session.json")
    runs = None
    if value is not None:
        for key in ("status", "session_id", "camera_id", "group_id", "started_at", "ended_at"):
            if key == "status" or value.get(key) is not None:
                _field(value, key, str, problems, "session.json")
        for key in ("recording", "source"):
            if value.get(key) is not None:
                _field(value, key, dict, problems, "session.json")
        _field(value, "events", list, problems, "session.json")
        if value["events"] is not None:
            events = value["events"]
            skipped = sum(not isinstance(event, dict) for event in events)
            if skipped:
                problems.append(f"session.json: skipped {skipped} non-object events")
            value["events"] = [event for event in events if isinstance(event, dict)]
        _field(value, "runs", list, problems, "session.json")
        if value["runs"] is not None:
            loaded = []
            for name in value["runs"]:
                if not _name(name):
                    problems.append("session.json: runs contains an invalid folder name")
                    loaded.append(None)
                    continue
                run = read_run(path / "runs" / name)
                loaded.append(run)
                if not run.path.is_dir():
                    problems.append(f"session.json: run {name} has no folder")
            runs = tuple(loaded)
    data = _snapshot_data(value, problems, "session.json")
    return SessionSnapshot(path, data, tuple(problems), runs if data is not None else None)


def find_sessions(
    out: Path | str, *, group_id=None, session_id=None
) -> tuple[SessionSnapshot, ...]:
    """Discover metadata-bearing folders, in folder order; unrelated damage is ignored."""
    try:
        folders = sorted(Path(out).iterdir())
    except OSError:
        return ()
    found = []
    for folder in folders:
        if folder.is_symlink() or not folder.is_dir() or not (folder / "session.json").is_file():
            continue
        snapshot = read_session(folder)
        if group_id is not None and snapshot.get("group_id") != group_id:
            continue
        if session_id is not None and snapshot.get("session_id") != session_id:
            continue
        found.append(snapshot)
    return tuple(found)


def run_paths(path: Path | str) -> list[Path]:
    snapshot = read_session(path)
    snapshot.require("runs")
    if any(run is None for run in snapshot.runs):
        raise SessionDamaged(f"session damaged: {path}: invalid run folder name")
    return [run.path for run in snapshot.runs]


def mark_interrupted(session: SessionSnapshot) -> tuple[str, ...]:
    """Atomically recover a running session. Return write/content problems to the caller.

    Preserve unknown fields and refuse malformed events rather than erase evidence.
    Recovery is called only after the owning child process has gone away.
    """
    if session.status != "running":
        return ()
    if session.events is None or any("non-object events" in p for p in session.problems):
        return session.problems
    # Recovery changes only lifecycle fields; retain even malformed unrelated metadata.
    value, problems = _read(session.path, "session.json")
    if value is None:
        return tuple(problems)
    if value.get("status") != "running":
        return ()
    events = value.get("events")
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        return ("session.json: events changed or are not readable during recovery",)
    value["status"] = "interrupted"
    value["ended_at"] = utc_now()
    value["events"].append(
        {
            "t_wall": value["ended_at"],
            "t_mono": None,
            "kind": "interrupted",
            "detail": "app restarted after an unclean shutdown",
        }
    )
    destination = session.path / "session.json"
    temporary = destination.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
    except OSError as error:
        return (f"session.json: {error}",)
    return ()
