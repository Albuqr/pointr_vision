"""One contract version in the code, equal to the docs; the calibration loader accepts the
versions it lists."""

import copy
import json
import re
from pathlib import Path

import pytest

from services.edge.calibration import document as calibration_document
from services.edge.calibration.document import validate_calibration
from services.edge.contract import CONTRACT_VERSION
from services.edge.session import writer

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = json.loads(
    (ROOT / "tests/fixtures/contracts/calibration.example.json").read_text(encoding="utf-8")
)


def test_the_code_version_is_the_documents_version_and_defined_once():
    text = (ROOT / "docs/DATA_CONTRACTS.md").read_text(encoding="utf-8")
    assert re.search(rf"contract[_ ]version[^\n]*{re.escape(CONTRACT_VERSION)}", text, re.I)
    assert writer.CONTRACT_VERSION is CONTRACT_VERSION
    assert calibration_document.CONTRACT_VERSION is CONTRACT_VERSION
    for path in ("services/app/server.py", "services/edge/session/writer.py"):
        assert not re.search(r'["\']\d+\.\d+\.\d+["\']', (ROOT / path).read_text(encoding="utf-8"))


def test_a_listed_older_version_loads_and_an_unlisted_one_is_refused(monkeypatch):
    older = copy.deepcopy(EXAMPLE)
    older["contract_version"] = "0.7.9"
    with pytest.raises(ValueError, match="contract version"):
        validate_calibration(older)
    monkeypatch.setattr(calibration_document, "ACCEPTED_VERSIONS", (CONTRACT_VERSION, "0.7.9"))
    assert validate_calibration(older)["contract_version"] == "0.7.9"
