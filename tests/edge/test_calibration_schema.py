"""validate_calibration enforces calibration.schema.json: whatever it accepts every consumer can
load, and what it rejects fails here, not later inside the preview or the writer."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.calibration.document import validate_calibration
from tests.app.test_api import FakeLauncher
from tests.fixtures.make_clips import make_clips

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts/calibration.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads(
    (ROOT / "tests/fixtures/contracts/calibration.example.json").read_text(encoding="utf-8")
)


def mutated(edit):
    document = copy.deepcopy(EXAMPLE)
    edit(document)
    return document


SCHEMA_VIOLATIONS = {
    "no landmarks": lambda d: d["court"].pop("landmarks"),
    "extra point key": lambda d: d["points"][0].update(label="corner"),
    "extra top-level key": lambda d: d.update(note="x"),
    "extra court key": lambda d: d["court"].update(surface="wood"),
    "fiba court of another size": lambda d: d["court"].update(kind="fiba_full", length_m=3.0),
    "camera id with a space": lambda d: d.update(camera_id="cam 1"),
    "created_at without Z": lambda d: d.update(created_at="2026-10-13 12:00:00"),
    "landmark with three numbers": lambda d: d["court"]["landmarks"].update(bad=[1, 2, 3]),
    "bool as a residual": lambda d: d["points"][0].update(residual_m=True),
}


@pytest.mark.parametrize("name", SCHEMA_VIOLATIONS)
def test_whatever_the_schema_rejects_the_validator_rejects(name):
    document = mutated(SCHEMA_VIOLATIONS[name])
    assert list(Draft202012Validator(SCHEMA).iter_errors(document)), "not a violation"
    with pytest.raises(ValueError, match="calibration"):
        validate_calibration(document)


def test_a_file_without_landmarks_fails_validation_not_the_preview():
    document = mutated(lambda d: d["court"].pop("landmarks"))
    with pytest.raises(ValueError, match="landmarks"):
        validate_calibration(document)


def test_the_example_still_validates_and_builds_the_preview_court():
    from services.edge.calibration.court import court_model

    validate_calibration(EXAMPLE)
    court = EXAMPLE["court"]
    court_model(court["kind"], court["length_m"], court["width_m"], court["landmarks"])


def test_saved_files_contain_only_schema_keys_even_if_the_client_sends_more(tmp_path):
    clip = make_clips(tmp_path)["moving"]
    config = CameraConfig(tmp_path / "config.json")
    config.write([{"camera_id": "clip", "source": str(clip), "link": "file"}])
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        token = client.get("/api/cameras/clip/calibration/frame").headers["x-frame-token"]

        def point(image, court, role):
            return {
                "image_px": image,
                "court_m": court,
                "role": role,
                "label": "typed by hand",  # a key the schema does not allow
                "id": "p1",
            }

        points = [
            point([0, 0], [0, 0], "calibration"),
            point([400, 0], [4, 0], "calibration"),
            point([400, 300], [4, 3], "calibration"),
            point([0, 300], [0, 3], "calibration"),
            point([100, 100], [1, 1], "check"),
            point([300, 200], [3, 2], "check"),
        ]
        saved = client.put(
            "/api/cameras/clip/calibration",
            json={
                "frame_token": token,
                "court_kind": "custom",
                "length_m": 4,
                "width_m": 3,
                "max_check_error_m": 0.5,
                "points": points,
            },
        )
        assert saved.status_code == 200, saved.text
        document = client.get("/api/cameras/clip/calibration").json()
    Draft202012Validator(SCHEMA).validate(document)
    assert all(set(p) == {"image_px", "court_m", "role", "residual_m"} for p in document["points"])
