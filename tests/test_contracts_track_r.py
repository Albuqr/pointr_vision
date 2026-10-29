"""Track R, slice R0 (D-033 to D-041): the 0.11.0 formats in DATA_CONTRACTS.md match the code."""

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from services.edge import contract
from services.edge.session.writer import TRACKS_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "DATA_CONTRACTS.md").read_text(encoding="utf-8")
DELETE = object()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    s = load(ROOT / "contracts" / f"{name}.schema.json")
    Draft202012Validator.check_schema(s)
    return Draft202012Validator(s)


def example(name: str) -> dict:
    return load(ROOT / "tests" / "fixtures" / "contracts" / f"{name}.example.json")


def mutate(doc: dict, path: tuple, value) -> dict:
    doc = copy.deepcopy(doc)
    node = doc
    for key in path[:-1]:
        node = node[key]
    if value is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


def columns_after(marker: str) -> list[str]:
    """Column names, in order, of the first markdown table after `marker` in DATA_CONTRACTS.md."""
    start = DOC.index(marker)
    table = re.search(r"((?:^\|.*\|[ \t]*\r?\n)+)", DOC[start:], re.M).group(1)
    names = []
    for cell in re.findall(r"^\| ([\w, ]+?) \|", table, re.M)[1:]:  # [0] is the header
        names += cell.split(", ")
    return names


@pytest.mark.parametrize(
    "marker,expected",
    [
        ("## 11. `objects.csv`", contract.OBJECTS_COLUMNS),
        ("## 12. `events.csv`", contract.EVENTS_COLUMNS),
        ("## 13. `shots.csv`", contract.SHOTS_COLUMNS),
        ("## 14. `labels.csv`", contract.LABELS_COLUMNS),
        ("`fused_tracks.csv`: one row", contract.FUSED_TRACKS_COLUMNS),
        ("`fusion_diff.csv`: one row", contract.FUSION_DIFF_COLUMNS),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_csv_columns_in_code_match_the_doc(marker, expected):
    assert list(expected) == columns_after(marker)


def test_code_version_matches_the_doc():
    assert re.search(r"Contract version: \*\*(.+?)\*\*", DOC).group(1) == contract.CONTRACT_VERSION


# -- run.json: the two new blocks ------------------------------------------------------------

CHECKS = [
    {
        "check": "cameras",
        "result": "passed",
        "detail": "2 of 2 connected",
        "t_wall": "2026-12-01T18:00:00Z",
    },
    {
        "check": "sensor",
        "result": "failed",
        "detail": "7 of 10 drops",
        "t_wall": "2026-12-01T18:02:00Z",
    },
]
CLOCK = {
    "domain": "perf_counter",
    "sensors": [
        {
            "sensor_id": "rim_a",
            "link": "espnow",
            "offset_start_s": 5000.0004,
            "offset_end_s": 5000.0009,
            "estimates": 12,
        },
        {
            "sensor_id": "rim_b",
            "link": "espnow",
            "offset_start_s": 5000.0006,
            "offset_end_s": 5000.0011,
            "estimates": 12,
        },
    ],
    "camera_latency": [
        {
            "camera_id": "cam1",
            "when": "start",
            "flashes": 40,
            "median_s": 0.08,
            "p95_s": 0.1,
            "std_s": 0.01,
        },
        {
            "camera_id": "cam1",
            "when": "end",
            "flashes": 40,
            "median_s": 0.081,
            "p95_s": 0.1,
            "std_s": 0.01,
        },
    ],
}


OBJECTS = {"classes": ["ball", "rim"]}
INTERVALS = [{"start_t": 12.0, "end_t": 32.0, "detected_t": 14.0}]
OUTAGES = [{"sensor_id": "rim_a", **INTERVALS[0]}]


def test_run_example_has_null_blocks_and_populated_blocks_validate():
    run = example("run")
    for key in ("checks", "clock", "objects", "gaps", "outages"):
        assert run[key] is None
    assert isinstance(run["t0_mono"], float)
    run["checks"], run["clock"], run["objects"] = CHECKS, CLOCK, OBJECTS
    run["gaps"], run["outages"] = INTERVALS, OUTAGES
    assert not list(validator("run").iter_errors(run))


def test_a_sensor_with_no_estimate_has_null_offsets():
    run = example("run")
    sensors = [
        {
            "sensor_id": "rim_a",
            "link": "usb",
            "offset_start_s": None,
            "offset_end_s": None,
            "estimates": 0,
        }
    ]
    run["clock"] = {**CLOCK, "sensors": sensors}
    assert not list(validator("run").iter_errors(run))


def test_clock_without_a_sensor_is_valid():
    run = example("run")
    run["clock"] = {**CLOCK, "sensors": []}
    assert not list(validator("run").iter_errors(run))


@pytest.mark.parametrize(
    "path,value",
    [
        (("checks", 0, "check"), "lighting"),
        (("checks", 0, "result"), "skipped"),
        (("checks", 0, "extra"), 1),
        (("checks", 0, "t_wall"), "yesterday"),
        (("clock", "domain"), "wall"),
        (("clock", "sensors", 0, "link"), "wifi"),
        (("clock", "sensors", 0, "estimates"), -1),
        (("clock", "camera_latency", 0, "when"), "middle"),
        (("clock", "camera_latency", 0, "flashes"), 0),
        (("clock", "camera_latency", 0, "median_s"), -0.1),
        (("clock", "camera_latency", 0, "camera_id"), ""),
        (("clock", "extra"), 1),
        (("clock", "sensors", 0, "offset_s"), 0.1),
        (("objects", "classes"), ["person"]),
        (("objects", "classes"), []),
        (("objects", "classes"), ["ball", "ball"]),
        (("gaps", 0, "end_t"), -1),
        (("gaps", 0, "extra"), 1),
        (("outages", 0, "start_t"), "x"),
        (("t0_mono",), "x"),
        (("gaps", 0, "start_t"), -1),
        (("outages", 0, "end_t"), -1),
        (("outages", 0, "extra"), 1),
        (("objects", "extra"), 1),
        (("clock", "camera_latency", 0, "extra"), 1),
        (("clock", "camera_latency", 0, "p95_s"), -0.1),
        (("clock", "camera_latency", 0, "std_s"), -0.1),
        (("clock", "sensors", 0, "offset_start_s"), "x"),
        (("clock", "sensors", 0, "offset_end_s"), "x"),
        (("checks", 0, "detail"), None),
    ],
    ids=lambda x: "/".join(map(str, x)) if isinstance(x, tuple) else repr(x)[:20],
)
def test_broken_track_r_blocks_fail(path, value):
    run = example("run")
    run["checks"], run["clock"] = copy.deepcopy(CHECKS), copy.deepcopy(CLOCK)
    run["objects"], run["gaps"] = copy.deepcopy(OBJECTS), copy.deepcopy(INTERVALS)
    run["outages"] = copy.deepcopy(OUTAGES)
    errors = list(validator("run").iter_errors(mutate(run, path, value)))
    assert errors, f"{path} = {value!r} should be rejected"


@pytest.mark.parametrize(
    "key", ["checks", "clock", "t0_mono", "objects", "gaps", "outages", "group", "ready"]
)
def test_run_requires_the_blocks_even_when_null(key):
    assert list(validator("run").iter_errors(mutate(example("run"), (key,), DELETE)))


# -- run.json: the group block (0.14.0, D-051) ------------------------------------------------

GROUP = {
    "group_id": "g1",
    "group_run_id": "5e0b7c1d-2a4f-4b6e-8d3c-9f1a0e2b4c67",
    "cameras": [
        {
            "camera_id": "cam1",
            "session_id": "3f1c2a8e-5b7d-4e9a-8c21-6d4f0b9e7a13",
            "run_id": "c2b9e6f4-1d3a-4c8e-9f7b-5a0d2e4c6b81",
        },
        {
            "camera_id": "cam2",
            "session_id": "7a2d4e6f-8b0c-4d1e-9f3a-5b7c9d1e3f50",
            "run_id": "1b3d5f7a-9c2e-4a6b-8d0f-2e4a6c8e0b12",
        },
    ],
    "params": {"any_name": 0.5},  # names arrive with the matcher (R2a 05, 06)
}


def test_a_run_without_a_group_has_a_null_group_and_a_group_run_validates():
    run = example("run")
    assert run["group"] is None
    run["group"] = GROUP
    assert not list(validator("run").iter_errors(run))


def test_a_group_with_no_matcher_has_empty_params():
    run = example("run")
    run["group"] = {**GROUP, "params": {}}
    assert not list(validator("run").iter_errors(run))


@pytest.mark.parametrize(
    "path,value",
    [
        (("group", "group_id"), ""),
        (("group", "group_id"), "a/b"),
        (("group", "group_id"), "x" * 65),
        (("group", "group_run_id"), "not-a-uuid"),
        (("group", "group_run_id"), DELETE),
        (("group", "cameras"), []),
        (("group", "cameras", 0, "camera_id"), "has space"),
        (("group", "cameras", 0, "session_id"), "x"),
        (("group", "cameras", 0, "run_id"), DELETE),
        (("group", "cameras", 0, "extra"), 1),
        (("group", "params"), None),
        (("group", "params"), DELETE),
        (("group", "extra"), 1),
    ],
    ids=lambda x: "/".join(map(str, x)) if isinstance(x, tuple) else repr(x)[:20],
)
def test_broken_group_fails(path, value):
    run = example("run")
    run["group"] = copy.deepcopy(GROUP)
    errors = list(validator("run").iter_errors(mutate(run, path, value)))
    assert errors, f"{path} = {value!r} should be rejected"


def test_an_identical_camera_entry_listed_twice_fails():
    run = example("run")
    run["group"] = {**GROUP, "cameras": [GROUP["cameras"][0]] * 2}
    assert list(validator("run").iter_errors(run))


# -- fusion.json -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,value",
    [
        (("fusion_id",), "not-a-uuid"),
        (("group_id",), ""),
        (("group_id",), "has space"),
        (("created_at",), "yesterday"),
        (("cameras",), []),
        (("cameras", 0, "run_id"), "x"),
        (("cameras", 0, "latency_median_s"), -1),
        (("cameras", 0, "extra"), 1),
        (("params", "match_distance_m"), 0),
        (("params", "max_offset_s"), -0.01),
        (("gaps", 0, "start_t"), "x"),
        (("excluded", 0, "reason"), "tired"),
        (("excluded", 0, "camera_id"), "has space"),
        (("excluded", 0, "extra"), 1),
        (("counts", "single_camera_rows"), -1),
        (("counts", "differences"), 1.5),
        (("cameras", 0, "t0_mono"), "x"),
        (("excluded",), DELETE),
        (("cameras", 0, "t0_mono"), DELETE),
        (("params", "step_s"), 0),
        (("counts", "players"), -1),
        (("counts", "merged_rows"), 1.5),
        (("counts", "merged_frames"), 1),
        (("counts", "extra"), 1),
        (("extra",), 1),
        (("contract_version",), "0.10.0"),
        (("params",), DELETE),
        (("counts",), DELETE),
    ],
    ids=lambda x: "/".join(map(str, x)) if isinstance(x, tuple) else repr(x)[:20],
)
def test_broken_fusion_fails(path, value):
    fusion = example("fusion")
    fusion["excluded"] = [{"camera_id": "cam3", "reason": "operator"}]
    errors = list(validator("fusion").iter_errors(mutate(fusion, path, value)))
    assert errors, f"{path} = {value!r} should be rejected"


def test_a_fusion_without_gaps_is_valid():
    fusion = example("fusion")
    fusion["gaps"] = []
    assert not list(validator("fusion").iter_errors(fusion))


def test_a_camera_without_a_latency_test_is_valid_and_gaps_may_start_before_zero():
    fusion = example("fusion")
    fusion["cameras"][0]["latency_median_s"] = None
    fusion["gaps"] = [{"camera_id": "cam1", "start_t": -0.05, "end_t": -0.01}]
    fusion["excluded"] = [{"camera_id": "cam3", "reason": "calibration_failed"}]
    assert not list(validator("fusion").iter_errors(fusion))


# -- enumerated values ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "marker,end,values",
    [
        ("`checks` (0.11.0", "`clock` (0.11.0", contract.CHECK_NAMES),
        ("## 5.", "## 6.", contract.ID_SOURCES + contract.TRACK_LINKS),
        ("## 11.", "## 12.", contract.OBJECT_CLASSES + contract.OBJECT_SOURCES),
        ("## 12.", "## 13.", contract.SENSOR_EVENT_KINDS + contract.LINKS),
        ("## 13.", "## 14.", contract.SHOT_CALLS + contract.CALL_SOURCES + contract.SHOT_FLAGS),
        ("## 14.", "## 15.", contract.LABEL_EVENTS),
        ("## 15.", "`fused_tracks.csv`: one row", contract.EXCLUDED_REASONS),
        ("`fusion_diff.csv`: one row", None, contract.FUSION_FIELDS),
        ("Event kinds:", "## 3.", contract.TRACK_R_SESSION_EVENT_KINDS),
    ],
    ids=lambda x: x[:12] if isinstance(x, str) else "",
)
def test_every_enumerated_value_is_named_in_its_doc_section(marker, end, values):
    start = DOC.index(marker)
    text = DOC[start : DOC.index(end, start)] if end else DOC[start:]
    for value in values:
        assert f"`{value}`" in text, f"{value} is missing from the section after {marker!r}"


def enum_of(schema_name: str, *path: str) -> set:
    node = load(ROOT / "contracts" / f"{schema_name}.schema.json")
    for key in path:
        node = node[key]
    return set(node["enum"])


def test_schema_enums_equal_the_code_constants():
    props = ("properties",)
    checks = enum_of("run", *props, "checks", "items", "properties", "check")
    assert checks == set(contract.CHECK_NAMES)
    link = enum_of("run", *props, "clock", "properties", "sensors", "items", "properties", "link")
    assert link == set(contract.LINKS)
    classes = enum_of("run", *props, "objects", "properties", "classes", "items")
    assert classes == set(contract.OBJECT_CLASSES)
    reason = enum_of("fusion", "properties", "excluded", "items", "properties", "reason")
    assert reason == set(contract.EXCLUDED_REASONS)


# -- CSV formats: header, types, empty cells and value domains, all read from the doc tables ----

CSV_FILES = {
    "tracks": ("## 5. `tracks.csv`", TRACKS_COLUMNS),
    "objects": ("## 11.", contract.OBJECTS_COLUMNS),
    "events": ("## 12.", contract.EVENTS_COLUMNS),
    "shots": ("## 13.", contract.SHOTS_COLUMNS),
    "labels": ("## 14.", contract.LABELS_COLUMNS),
    "fused_tracks": ("`fused_tracks.csv`: one row", contract.FUSED_TRACKS_COLUMNS),
    "fusion_diff": ("`fusion_diff.csv`: one row", contract.FUSION_DIFF_COLUMNS),
}
# (file, column) -> the code constant that must equal the backticked values in that doc row
ENUM_COLUMNS = {
    ("tracks", "id_source"): contract.ID_SOURCES,
    ("tracks", "link"): contract.TRACK_LINKS,
    ("objects", "class"): contract.OBJECT_CLASSES,
    ("objects", "source"): contract.OBJECT_SOURCES,
    ("events", "kind"): contract.SENSOR_EVENT_KINDS,
    ("events", "link"): contract.LINKS,
    ("shots", "call"): contract.SHOT_CALLS,
    ("shots", "call_source"): contract.CALL_SOURCES,
    ("shots", "flags"): contract.SHOT_FLAGS,
    ("labels", "event"): contract.LABEL_EVENTS,
    ("fusion_diff", "field"): contract.FUSION_FIELDS,
}
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def doc_table(marker: str) -> list[tuple[list[str], str, str]]:
    """(column names, type, meaning) per row of the first table after `marker`."""
    start = DOC.index(marker)
    table = re.search(r"((?:^\|.*\|[ \t]*\r?\n)+)", DOC[start:], re.M).group(1)
    rows = []
    for line in table.splitlines()[2:]:  # [0] is the header, [1] the separator
        names, type_, meaning = (c.strip() for c in line.strip().strip("|").split("|", 2))
        rows.append((names.split(", "), type_, meaning))
    return rows


@pytest.mark.parametrize("file,column", ENUM_COLUMNS, ids=lambda x: x if isinstance(x, str) else "")
def test_an_enum_column_in_the_doc_equals_the_code_constant(file, column):
    rows = doc_table(CSV_FILES[file][0])
    expected = set(ENUM_COLUMNS[(file, column)])
    names = {n for r in rows for n in r[0]}
    meaning = next(r[2] for r in rows if column in r[0])
    found = set(re.findall(r"`([a-z_+]+)`", meaning)) - (names - expected)
    assert found == expected


def test_id_source_in_the_doc_equals_the_code_constant():
    rows = doc_table("## 5.")
    meaning = next(r[2] for r in rows if r[0] == ["id_source"])
    found = set(re.findall(r"`([a-z_+]+)`", meaning)) - {"player_number"}
    assert found == set(contract.ID_SOURCES)


@pytest.mark.parametrize("name", CSV_FILES)
def test_sample_csv_follows_the_doc_types_empty_cells_and_domains(name):
    import csv

    marker, columns = CSV_FILES[name]
    types = {n: r[1] for r in doc_table(marker) for n in r[0]}
    assert list(types) == list(columns)
    path = ROOT / "tests" / "fixtures" / "contracts" / f"{name}.example.csv"
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows and list(rows[0]) == list(columns)
    for row in rows:
        for column, value in row.items():
            type_ = types[column]
            if value == "":
                assert type_.endswith("/empty"), f"{column} may not be empty"
                continue
            base = type_.split("/")[0]
            if base == "int":
                int(value)
            elif base == "float":
                float(value)
            elif base == "bool":
                assert value in ("true", "false")
            if column == "t_wall":
                assert UTC.match(value), value
            if (name, column) in ENUM_COLUMNS and column != "flags":
                assert value in ENUM_COLUMNS[(name, column)], f"{column}={value!r}"
        if name == "shots":
            assert set(filter(None, row["flags"].split(";"))) <= set(contract.SHOT_FLAGS)
        if name == "events":  # the row rules of section 12
            if row["kind"] in ("outage_start", "outage_end", "reset"):
                assert not (row["sensor_seq"] or row["offset_s"])
            if row["kind"] == "sync":
                assert row["sensor_seq"] == "" and row["offset_s"] != ""
        if name == "fusion_diff":
            assert (row["delta"] != "") == (row["field"] == "position")


def test_every_accepted_adr_has_a_decision_entry():
    """R0-A2, the existence half: D-0NN ... (ADR 000N) in DECISIONS.md for each accepted ADR."""
    decisions = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
    adrs = sorted((ROOT / "docs" / "adr").glob("0*.md"))
    assert adrs
    checked = 0
    for adr in adrs:
        header = " ".join(adr.read_text(encoding="utf-8").splitlines()[:4]).lower()
        assert "status:" in header, f"{adr.name} has no status line"
        if "status: accepted" in header:
            checked += 1
            heading = rf"^## D-\d+ .*\(ADR {adr.name[:4]}\)"
            assert re.search(heading, decisions, re.M), f"no decision entry for {adr.name}"
    assert checked >= 1


@pytest.mark.parametrize("kind", contract.TRACK_R_SESSION_EVENT_KINDS)
def test_each_new_session_event_kind_validates(kind):
    doc = example("session")
    doc["events"] = [{"t_wall": "2026-10-07T18:00:01Z", "t_mono": 1.0, "kind": kind, "detail": "x"}]
    errors = list(validator("session").iter_errors(doc))
    assert not errors, errors[:1]
