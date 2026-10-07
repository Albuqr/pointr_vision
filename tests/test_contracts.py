"""A2: example session.json/run.json validate; broken examples fail; schemas match the doc."""

import copy
import json
import re
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "contracts"
EXAMPLES = ROOT / "tests" / "fixtures" / "contracts"
DOC = (ROOT / "docs" / "DATA_CONTRACTS.md").read_text(encoding="utf-8")
DELETE = object()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def schema(name: str) -> dict:
    return load(SCHEMAS / f"{name}.schema.json")


def validator(name: str) -> Draft202012Validator:
    s = schema(name)
    Draft202012Validator.check_schema(s)
    return Draft202012Validator(s)


def example(name: str) -> dict:
    return load(EXAMPLES / f"{name}.example.json")


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


def doc_version() -> str:
    return re.search(r"Contract version: \*\*(\d+\.\d+\.\d+)\*\*", DOC).group(1)


def doc_example(section: str) -> dict:
    """The JSON block under a '## N. `<section>`' heading of DATA_CONTRACTS.md."""
    m = re.search(rf"## \d+\. `{re.escape(section)}`\s+```json\n(.*?)```", DOC, re.S)
    return json.loads(m.group(1))


@pytest.mark.parametrize("name", ["session", "run"])
def test_example_validates(name):
    validator(name).validate(example(name))


@pytest.mark.parametrize("name", ["session", "run"])
def test_versions_agree(name):
    v = doc_version()
    assert schema(name)["properties"]["contract_version"]["const"] == v
    assert example(name)["contract_version"] == v
    assert f"urn:pointr:contracts:{v}:" in schema(name)["$id"]


def test_session_valid_while_running():
    """A running session has no end time yet: null, not absent and not 0."""
    doc = mutate(example("session"), ("status",), "running")
    doc = mutate(doc, ("ended_at",), None)
    doc = mutate(doc, ("registration",), None)
    validator("session").validate(doc)


def test_run_without_recording_has_null_rec_dropped():
    validator("run").validate(mutate(example("run"), ("counts", "rec_dropped"), None))


def test_run_valid_while_running():
    validator("run").validate(mutate(example("run"), ("ended_at",), None))


def test_shared_defs_identical():
    """uuid4/utc/sha256 are duplicated per schema; the copies must not drift."""
    assert schema("run")["$defs"] == schema("session")["$defs"]


@pytest.mark.parametrize("kind", ["camera", "stream", "file"])
def test_run_input_kinds(kind):
    validator("run").validate(mutate(example("run"), ("input", "kind"), kind))


UUID1 = str(uuid.UUID("12345678-1234-1234-8234-123456789abc"))  # version 1, not 4

BROKEN = {
    "session": [
        (("session_id",), DELETE),
        (("ended_at",), DELETE),
        (("contract_version",), "0.1.0"),
        (("status",), "finished"),
        (("session_id",), "not-a-uuid"),
        (("device_id",), UUID1),
        (("started_at",), "2026-10-07 18:00:00"),
        (("started_at",), "2026-10-07T18:00:00+03:00"),
        (("ended_at",), 0),
        (("source", "kind"), "webcam"),
        (("source", "width"), "1280"),
        (("source", "reported_fps"), 0),
        (("source", "width"), 0),
        (("source", "extra"), 1),
        (("registration", "team_ids"), []),
        (("registration", "team_ids"), [str(uuid.uuid4()) for _ in range(3)]),
        (("registration", "date"), "07/10/2026"),
        (("recording", "sha256"), 0),
        (("recording", "sha256"), "abc"),
        (("runs",), ["not-a-uuid"]),
        (("events", 0, "kind"), "lost"),
        (("events", 0, "t_mono"), DELETE),
        (("events", 0, "extra"), 1),
        (("extra",), 1),
    ],
    "run": [
        (("run_id",), DELETE),
        (("run_id",), UUID1),
        (("session_id",), "not-a-uuid"),
        (("started_at",), "2026-10-07T18:00:00+03:00"),
        (("ended_at",), "2026-10-07 18:01:00"),
        (("input", "sha256"), "abc"),
        (("runtime", "python"), "py3"),
        (("counts", "rec_dropped"), -1),
        (("contract_version",), DELETE),
        (("contract_version",), "0.1.0"),
        (("mode",), "test"),
        (("input", "kind"), "usb"),
        (("input", "sha256"), 0),
        (("detector", "threshold"), 1.5),
        (("detector", "package_version"), DELETE),
        (("tracker", "params"), None),
        (("runtime", "device"), "gpu"),
        (("ended_at",), 0),
        (("counts", "dropped"), -1),
        (("counts", "processed"), None),
        (("counts", "captured"), 1.5),
        (("extra",), 1),
    ],
}


@pytest.mark.parametrize(
    "name,path,value",
    [(n, p, v) for n, cases in BROKEN.items() for p, v in cases],
    ids=lambda x: "/".join(map(str, x)) if isinstance(x, tuple) else repr(x)[:20],
)
def test_broken_example_fails(name, path, value):
    errors = list(validator(name).iter_errors(mutate(example(name), path, value)))
    assert errors, f"{name}: {path} = {value!r} should be rejected"


def _assert_matches(doc_node, schema_node, path=()):
    """Every key and enum in the doc's example appears in the schema, and nothing more."""
    if isinstance(doc_node, dict) and doc_node:
        assert set(doc_node) == set(schema_node["properties"]), path
        assert set(doc_node) == set(schema_node["required"]), path
        for key, value in doc_node.items():
            _assert_matches(value, schema_node["properties"][key], (*path, key))
    elif isinstance(doc_node, list) and doc_node and isinstance(doc_node[0], dict):
        _assert_matches(doc_node[0], schema_node["items"], path)
    elif isinstance(doc_node, str) and " | " in doc_node and "enum" in schema_node:
        assert set(doc_node.split(" | ")) == set(schema_node["enum"]), path


@pytest.mark.parametrize("name", ["session", "run"])
def test_schema_matches_doc(name):
    _assert_matches(doc_example(f"{name}.json"), schema(name))


def test_event_kinds_match_doc():
    listed = re.search(r"Event kinds: (.*?)\.\n", DOC, re.S).group(1)
    kinds = set(re.findall(r"`(\w+)`", listed))
    events = schema("session")["properties"]["events"]["items"]
    assert set(events["properties"]["kind"]["enum"]) == kinds
