"""Track R, slice R0 (D-033 to D-040): the 0.11.0 formats in DATA_CONTRACTS.md match the code."""

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from services.edge import contract

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
    "sensor": {"link": "espnow", "offset_s": 0.0004, "estimates": 12},
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


def test_run_example_has_null_blocks_and_populated_blocks_validate():
    run = example("run")
    assert run["checks"] is None and run["clock"] is None
    run["checks"], run["clock"] = CHECKS, CLOCK
    assert not list(validator("run").iter_errors(run))


def test_clock_without_a_sensor_is_valid():
    run = example("run")
    run["clock"] = {**CLOCK, "sensor": None}
    assert not list(validator("run").iter_errors(run))


@pytest.mark.parametrize(
    "path,value",
    [
        (("checks", 0, "check"), "lighting"),
        (("checks", 0, "result"), "skipped"),
        (("checks", 0, "extra"), 1),
        (("checks", 0, "t_wall"), "yesterday"),
        (("clock", "domain"), "wall"),
        (("clock", "sensor", "link"), "wifi"),
        (("clock", "sensor", "estimates"), -1),
        (("clock", "camera_latency", 0, "when"), "middle"),
        (("clock", "camera_latency", 0, "flashes"), 0),
        (("clock", "camera_latency", 0, "median_s"), -0.1),
        (("clock", "camera_latency", 0, "camera_id"), ""),
        (("clock", "extra"), 1),
    ],
    ids=lambda x: "/".join(map(str, x)) if isinstance(x, tuple) else repr(x)[:20],
)
def test_broken_track_r_blocks_fail(path, value):
    run = example("run")
    run["checks"], run["clock"] = copy.deepcopy(CHECKS), copy.deepcopy(CLOCK)
    errors = list(validator("run").iter_errors(mutate(run, path, value)))
    assert errors, f"{path} = {value!r} should be rejected"


@pytest.mark.parametrize("key", ["checks", "clock"])
def test_run_requires_the_blocks_even_when_null(key):
    assert list(validator("run").iter_errors(mutate(example("run"), (key,), DELETE)))


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
        (("gaps", 0, "end_t"), -1),
        (("counts", "players"), -1),
        (("counts", "merged_frames"), 1.5),
        (("counts", "extra"), 1),
        (("extra",), 1),
        (("contract_version",), "0.10.0"),
        (("params",), DELETE),
        (("counts",), DELETE),
    ],
    ids=lambda x: "/".join(map(str, x)) if isinstance(x, tuple) else repr(x)[:20],
)
def test_broken_fusion_fails(path, value):
    errors = list(validator("fusion").iter_errors(mutate(example("fusion"), path, value)))
    assert errors, f"{path} = {value!r} should be rejected"


def test_a_fusion_without_gaps_is_valid():
    fusion = example("fusion")
    fusion["gaps"] = []
    assert not list(validator("fusion").iter_errors(fusion))
