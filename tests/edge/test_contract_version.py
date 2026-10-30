"""One contract version in the code, equal to the docs; contract.py parses, validates and decides
which calibration versions the loader accepts."""

import copy
import json
import re
from pathlib import Path

import pytest

from services.edge import contract
from services.edge.calibration import document as calibration_document
from services.edge.calibration.document import validate_calibration
from services.edge.contract import CONTRACT_VERSION
from services.edge.session import writer

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = json.loads(
    (ROOT / "tests/fixtures/contracts/calibration.example.json").read_text(encoding="utf-8")
)


def bumped(part):
    major, minor, patch = contract.parse_version(CONTRACT_VERSION)
    return {"minor": f"{major}.{minor + 1}.0", "patch": f"{major}.{minor}.{patch + 1}"}[part]


def test_the_code_version_is_the_documents_version_and_defined_once():
    text = (ROOT / "docs/DATA_CONTRACTS.md").read_text(encoding="utf-8")
    assert re.search(rf"contract[_ ]version[^\n]*{re.escape(CONTRACT_VERSION)}", text, re.I)
    assert writer.CONTRACT_VERSION is CONTRACT_VERSION
    assert calibration_document.CONTRACT_VERSION is CONTRACT_VERSION
    for path in ("services/app/server.py", "services/edge/session/writer.py"):
        assert not re.search(r'["\']\d+\.\d+\.\d+["\']', (ROOT / path).read_text(encoding="utf-8"))


def test_parse_version_is_numeric_and_strict():
    assert contract.parse_version("0.22.0") == (0, 22, 0)
    assert contract.parse_version("0.10.0") > contract.parse_version("0.9.0")
    for bad in ("1.0", "v0", "0.1.0-rc1", "01.0.0", "", None, 1, ("0", "1", "0")):
        with pytest.raises(ValueError):
            contract.parse_version(bad)


@pytest.mark.parametrize(
    "version",
    ["0.8.0", "0.9.0", "0.13.0", "0.14.0", "0.15.0", "0.16.0", "0.17.0", "0.18.0", "0.21.0"],
)
def test_accepts_calibration_older_versions_of_the_format(version):
    assert contract.accepts_calibration(version)


def test_accepts_calibration_the_current_version():
    assert contract.accepts_calibration(CONTRACT_VERSION)


@pytest.mark.parametrize("version", ["0.7.9", None, "1.0", "abc", "", 8])
def test_accepts_calibration_refuses_old_and_malformed(version):
    assert not contract.accepts_calibration(version)


@pytest.mark.parametrize("part", ["patch", "minor"])
def test_accepts_calibration_refuses_a_version_newer_than_the_code(part):
    assert not contract.accepts_calibration(bumped(part))


def test_a_version_outside_the_format_range_is_refused_by_the_loader():
    for version in ("0.7.9", bumped("minor")):
        refused = copy.deepcopy(EXAMPLE)
        refused["contract_version"] = version
        with pytest.raises(ValueError, match="not accepted"):
            validate_calibration(refused)


def test_the_format_table_decides_what_the_loader_accepts(monkeypatch):
    older = copy.deepcopy(EXAMPLE)
    older["contract_version"] = "0.7.9"
    with pytest.raises(ValueError, match="contract version"):
        validate_calibration(older)
    monkeypatch.setitem(contract.CALIBRATION_FORMATS, "1", ("0.7.0", None))
    assert validate_calibration(older)["contract_version"] == "0.7.9"
