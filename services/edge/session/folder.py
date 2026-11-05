"""One tolerant view of session-folder metadata (D-065).

Snapshots contain only immutable values. Missing or malformed fields are None;
problems describe damage without making tolerant reads raise. Strict consumers
require only the fields they need. JSON text always accepts a UTF-8 BOM.
"""

import csv
import json
import os
from collections import deque
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

    def require(self, *fields: str, expected: type | None = None) -> dict:
        """Require a readable object and the named fields, raising one damage error.

        Unrelated optional fields may be absent or damaged. With no field names,
        only the top-level JSON object is required.
        """
        missing = []
        for field in fields:
            value = self.data
            for part in field.split("."):
                value = value.get(part) if isinstance(value, Mapping) else None
            if value is None or (expected is not None and not isinstance(value, expected)):
                missing.append(field)
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


@dataclass(frozen=True)
class RunSnapshot(Snapshot):
    calibration_damaged: bool = False  # run.json holds a calibration block that cannot be read

    @property
    def is_live(self) -> bool:
        return self.get("mode") == "live"


@dataclass(frozen=True)
class SessionSnapshot(Snapshot):
    runs: tuple[RunSnapshot | None, ...] | None
    skipped_events: int = 0  # events entries that were not objects, left out of `events`

    @property
    def latest_run(self) -> RunSnapshot | None:
        """The final listed run, even when earlier runs are healthier."""
        return self.runs[-1] if self.runs else None

    @property
    def live_run(self) -> RunSnapshot | None:
        """The first listed run: the one recorded live, since replays are appended after it.
        Check `is_live` when the caller needs it to have been a live run."""
        return self.runs[0] if self.runs else None

    def run(self, run_id: str) -> RunSnapshot | None:
        """The listed run with this id; None when session.json does not list it."""
        return next((r for r in self.runs or () if r is not None and r.path.name == run_id), None)


def _read(path: Path, filename: str):
    try:
        value = json.loads((path / filename).read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("not a JSON object")
        return value, []
    except (OSError, ValueError, RecursionError) as error:
        return None, [f"{filename}: {error}"]


def _field(value, key, kind, problems, filename) -> bool:
    """Normalize a field; True when it was not readable."""
    item = value.get(key)
    if isinstance(item, kind):
        return False
    value[key] = None
    problems.append(_unreadable(filename, key))
    return True


def _unreadable(filename, key):
    return f"{filename}: {key} not readable"


def read_session_for_update(path: Path | str) -> dict:
    """Read an unchanged session document for replay's read-merge-write operation.

    Tolerant snapshots normalize damage for display and must never be written back.
    Validate only the fields replay needs to mutate; preserve all other content,
    including non-object event entries and absent optional historical fields.
    Refuse unreadable mutation fields rather than overwrite evidence with a stale copy.
    """
    path = Path(path)
    value, problems = _read(path, "session.json")
    if value is not None:
        for key, kind in (("session_id", str), ("runs", list), ("events", list)):
            if not isinstance(value.get(key), kind):
                problems.append(f"session.json: {key} not readable")
    if problems:
        raise SessionDamaged(f"session damaged: {'; '.join(problems)} ({path})")
    return value


def read_run(path: Path | str) -> RunSnapshot:
    path = Path(path)
    value, problems = _read(path, "run.json")
    damaged = False
    if value is not None:
        for key in ("ready", "counts", "calibration", "group", "capture", "detection", "recording"):
            if key in ("ready", "counts") or value.get(key) is not None:
                if _field(value, key, dict, problems, "run.json") and key == "calibration":
                    damaged = True
    return RunSnapshot(path, _snapshot_data(value, problems, "run.json"), tuple(problems), damaged)


def read_session(path: Path | str) -> SessionSnapshot:
    path = Path(path)
    value, problems = _read(path, "session.json")
    runs = None
    skipped = 0
    if value is not None:
        for key in ("status", "session_id", "camera_id", "group_id", "started_at", "ended_at"):
            if key == "status" or value.get(key) is not None:
                _field(value, key, str, problems, "session.json")
        for key in ("recording", "source"):
            if value.get(key) is not None:
                _field(value, key, dict, problems, "session.json")
        recording = value.get("recording")
        if recording is not None:
            for key in ("path", "sha256"):
                if key in recording and recording[key] is not None:
                    if not isinstance(recording[key], str):
                        problems.append(f"session.json: recording.{key} not readable")
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
    return SessionSnapshot(path, data, tuple(problems), runs if data is not None else None, skipped)


FRAMES_FILE = "frames.csv"
TRACKS_FILE = "tracks.csv"


@dataclass(frozen=True)
class Rows:
    """The complete rows of one run CSV, read by its own header.

    One policy for damage: a row whose cell count differs from the header (a crash cuts the last
    one) is not returned; it is counted in `skipped` and said in `problems`. A file that stops
    being readable as CSV keeps the rows before that point and says so in `unreadable_after`
    ("absence is data").
    """

    name: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    skipped: int = 0
    unreadable_after: int | None = None  # rows read before the CSV became unreadable

    @property
    def problems(self) -> tuple[str, ...]:
        found = []
        if self.skipped:
            found.append(f"{self.name}: skipped {self.skipped} row(s) with the wrong cell count")
        if self.unreadable_after is not None:
            found.append(
                f"{self.name}: unreadable after {self.unreadable_after} row(s); the rest is lost"
            )
        return tuple(found)


def _whole(values, columns) -> bool:
    """The one test of a complete row: as many cells as the header."""
    return len(values) == len(columns)


def _read_rows(path: Path) -> Rows:
    """Raises OSError when the file is absent or unreadable."""
    rows, skipped, unreadable_after = [], 0, None
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        columns = tuple(next(reader, ()))
        try:
            for values in reader:
                if not values:  # a blank line
                    continue
                if _whole(values, columns):
                    rows.append(dict(zip(columns, values, strict=True)))
                else:
                    skipped += 1
        except csv.Error:
            unreadable_after = len(rows) + skipped
    return Rows(path.name, columns, tuple(rows), skipped, unreadable_after)


def read_frames(run_dir: Path | str) -> Rows:
    return _read_rows(Path(run_dir) / FRAMES_FILE)


def read_tracks(run_dir: Path | str) -> Rows:
    return _read_rows(Path(run_dir) / TRACKS_FILE)


def video_frames(frames: Rows, fps: float) -> tuple[tuple[int, dict[str, str]], ...]:
    """(video frame index, row) for the rows that have a video time, in index order. The index
    is the frame's position in the recorded video: round(t_video * fps)."""
    return tuple(
        sorted(
            ((round(float(r["t_video"]) * fps), r) for r in frames.rows if r.get("t_video")),
            key=lambda pair: pair[0],
        )
    )


class FrameTail:
    """The last rows of a frames.csv that is still being written, read incrementally (the
    Studio polls it). Same row policy as `read_frames`; reads only the bytes added since the last
    poll, and starts over if the file got shorter."""

    def __init__(self, run_dir: Path | str, keep: int = 30):
        self.path = Path(run_dir) / FRAMES_FILE
        self.keep = keep
        self.skipped = 0
        self._reset()

    def _reset(self):
        self._offset = 0
        self._partial = b""
        self._columns: tuple[str, ...] | None = None
        self._rows: deque[dict[str, str]] = deque(maxlen=self.keep)

    def poll(self) -> list[dict[str, str]]:
        try:
            if self.path.stat().st_size < self._offset:
                self.skipped = 0
                self._reset()
            with self.path.open("rb") as stream:
                stream.seek(self._offset)
                payload = stream.read()
                self._offset += len(payload)
        except OSError:
            return list(self._rows)
        lines = (self._partial + payload).split(b"\n")
        self._partial = lines.pop()  # the line the writer has not finished
        for line in lines:
            if line.strip():
                self._take(line)
        return list(self._rows)

    def _take(self, line: bytes):
        try:
            values = next(csv.reader([line.decode("utf-8-sig").rstrip("\r")]))
        except (UnicodeDecodeError, csv.Error, StopIteration):
            self.skipped += 1
            return
        if self._columns is None:
            self._columns = tuple(values)
        elif _whole(values, self._columns):
            self._rows.append(dict(zip(self._columns, values, strict=True)))
        else:
            self.skipped += 1


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
    if session.events is None or session.skipped_events:
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
