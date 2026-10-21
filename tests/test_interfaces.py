"""A4: Protocols importable; a dummy class satisfying each passes isinstance."""

import dataclasses
import inspect
import json
import re
import typing
from pathlib import Path

import numpy as np
import pytest

from services.edge.capture.types import (
    Frame,
    FrameSource,
    HealthEvent,
    SourceHealth,
    SourceInfo,
)
from services.edge.perception.types import Detections, Detector, Tracker, TrackObs
from services.edge.recording.types import Recorder, RecordingInfo
from services.edge.session.types import FrameRecord, SessionEvent, SessionWriter

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "DATA_CONTRACTS.md").read_text(encoding="utf-8")
NONE = type(None)

# Methods and parameter names exactly as ARCHITECTURE.md section 4.
EXPECTED = {
    FrameSource: {"open": [], "read": [], "close": []},
    SourceHealth: {"assess": ["frame"]},
    Detector: {"detect": ["frame"]},
    Tracker: {"update": ["dets", "frame"]},
    SessionWriter: {
        "start": ["meta", "run", "positions"],
        "start_run": ["session_dir", "run", "positions"],
        "set_t0": ["t0", "t0_wall"],
        "set_final": ["blocks"],
        "set_recording_sha256": ["sha256"],
        "frame": ["rec"],
        "tracks": ["seq", "obs", "no_positions"],
        "event": ["ev"],
        "close": ["status", "counts"],
    },
    Recorder: {"start": ["path", "info"], "write": ["frame"], "t_video": ["seq"], "stop": []},
}
PROTOCOLS = list(EXPECTED)
CASES = [(p, m) for p, methods in EXPECTED.items() for m in methods]

# Return types as ARCHITECTURE.md section 4.
RETURNS = {
    (FrameSource, "open"): SourceInfo,
    (FrameSource, "read"): Frame | None,
    (FrameSource, "close"): NONE,
    (SourceHealth, "assess"): list[HealthEvent],
    (Detector, "detect"): Detections,
    (Tracker, "update"): list[TrackObs],
    (SessionWriter, "start"): NONE,
    (SessionWriter, "start_run"): NONE,
    (SessionWriter, "set_t0"): NONE,
    (SessionWriter, "set_final"): NONE,
    (SessionWriter, "set_recording_sha256"): NONE,
    (SessionWriter, "frame"): NONE,
    (SessionWriter, "tracks"): NONE,
    (SessionWriter, "event"): NONE,
    (SessionWriter, "close"): NONE,
    (Recorder, "start"): NONE,
    (Recorder, "write"): NONE,
    (Recorder, "t_video"): float | None,
    (Recorder, "stop"): RecordingInfo,
}


def dummy(methods) -> type:
    """A plain class (no Protocol inheritance) with the given methods."""
    return type("Dummy", (), {m: lambda self, *a: None for m in methods})


def protocol_methods(proto) -> set[str]:
    return {n for n, v in vars(proto).items() if not n.startswith("_") and callable(v)}


@pytest.mark.parametrize("proto", PROTOCOLS, ids=lambda p: p.__name__)
def test_protocol_matches_architecture(proto):
    assert protocol_methods(proto) == set(EXPECTED[proto])
    for name, params in EXPECTED[proto].items():
        sig = inspect.signature(getattr(proto, name))
        assert list(sig.parameters)[1:] == params, name


def test_return_types_cover_every_method():
    assert set(RETURNS) == set(CASES)


@pytest.mark.parametrize("proto,name", list(RETURNS), ids=lambda x: getattr(x, "__name__", x))
def test_protocol_return_types(proto, name):
    assert typing.get_type_hints(getattr(proto, name))["return"] == RETURNS[(proto, name)]


@pytest.mark.parametrize("proto", PROTOCOLS, ids=lambda p: p.__name__)
def test_dummy_satisfies_protocol(proto):
    assert isinstance(dummy(EXPECTED[proto])(), proto)


@pytest.mark.parametrize("proto,missing", CASES, ids=lambda x: getattr(x, "__name__", x))
def test_dummy_missing_a_method_fails(proto, missing):
    methods = [m for m in EXPECTED[proto] if m != missing]
    assert not isinstance(dummy(methods)(), proto)


def test_frame_is_frozen():
    frame = Frame(
        seq=0,
        t_recv=0.0,
        t_wall="2026-10-07T18:00:00Z",
        image=np.zeros((2, 2, 3), np.uint8),
        source_id="test",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        frame.seq = 1


def field_names(cls) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def csv_columns(section: str) -> list[str]:
    """Column names, in order, from a DATA_CONTRACTS.md CSV table."""
    text = re.search(rf"## \d+\. `{re.escape(section)}`(.*?)\n## ", DOC, re.S).group(1)
    names = []
    for cell in re.findall(r"^\| ([\w, ]+?) \|", text, re.M)[1:]:  # [0] is the header
        names += cell.split(", ")
    return names


def schema_keys(*path: str) -> set[str]:
    node = json.loads((ROOT / "contracts" / "session.schema.json").read_text(encoding="utf-8"))
    for key in path:
        node = node["items"] if key == "items" else node["properties"][key]
    return set(node["properties"])


def test_frame_record_matches_frames_csv_columns():
    """Same names in the same order; app_delay_ms is a derived property, 5th column."""
    fields = field_names(FrameRecord)
    fields.insert(fields.index("t_proc_end") + 1, "app_delay_ms")
    assert fields == csv_columns("frames.csv")


def test_track_obs_matches_tracks_csv_columns():
    """seq comes from SessionWriter.tracks(); athlete_id, player_number and id_source are filled
    in later phases."""
    fields = field_names(TrackObs)
    i = fields.index("xyxy")
    fields[i : i + 1] = ["x1", "y1", "x2", "y2"]
    assert [
        "seq",
        *fields,
        "athlete_id",
        "player_number",
        "id_source",
        "x_m",
        "y_m",
        "calibration_id",
        "position_method",
        "in_court",
    ] == csv_columns("tracks.csv")


def test_source_info_matches_session_source():
    assert set(field_names(SourceInfo)) == schema_keys("source")


@pytest.mark.parametrize("cls", [SessionEvent, HealthEvent], ids=lambda c: c.__name__)
def test_events_match_session_events(cls):
    assert set(field_names(cls)) == schema_keys("events", "items")


def test_app_delay_ms():
    rec = FrameRecord(
        seq=3,
        t_recv=1.0,
        t_proc_start=1.01,
        t_proc_end=1.025,
        n_detections=0,
        n_tracks=0,
        dropped_total=0,
    )
    assert rec.app_delay_ms == pytest.approx(25.0)


def test_writer_csv_headers_match_the_doc():
    from services.edge.session.writer import FRAMES_COLUMNS, TRACKS_COLUMNS

    assert FRAMES_COLUMNS == csv_columns("frames.csv")
    assert TRACKS_COLUMNS == csv_columns("tracks.csv")
