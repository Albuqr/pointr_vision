"""validate_calibration enforces calibration.schema.json: whatever it accepts every consumer can
load, and what it rejects fails here, not later inside the preview or the writer."""

import copy
import json
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.calibration.document import load_calibration, validate_calibration
from services.edge.calibration.homography import fit_calibration, point_residuals
from tests.app.test_api import FakeLauncher
from tests.fixtures.make_clips import make_clips

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts/calibration.schema.json").read_text(encoding="utf-8"))
PACKAGED_SCHEMA = files("services.edge.calibration").joinpath("calibration.schema.json")
EXAMPLE = json.loads(
    (ROOT / "tests/fixtures/contracts/calibration.example.json").read_text(encoding="utf-8")
)


def test_runtime_schema_is_packaged_and_matches_the_contract_copy():
    assert json.loads(PACKAGED_SCHEMA.read_text(encoding="utf-8")) == SCHEMA


def mutated(edit):
    document = copy.deepcopy(EXAMPLE)
    edit(document)
    return document


def half_calibration_for(points):
    from services.edge.calibration.court import court_model

    fitted = fit_calibration(points)
    court = court_model("fiba_half", 14, 15)
    document = copy.deepcopy(EXAMPLE)
    document["court"] = {
        "kind": "fiba_half",
        "type": "fiba_half",
        "length_m": court.length_m,
        "width_m": court.width_m,
        "landmarks": {name: list(point) for name, point in court.landmarks.items()},
    }
    document["image_size"] = {"width": 1600, "height": 1600}
    document["homography_image_to_court"] = fitted["homography_image_to_court"]
    residuals = point_residuals(document["homography_image_to_court"], points)
    document["points"] = [
        {**point, "residual_m": residual} for point, residual in zip(points, residuals, strict=True)
    ]
    document["errors"] = {
        "calibration_mean_m": fitted["calibration_mean_m"],
        "check_mean_m": fitted["check_mean_m"],
        "check_max_m": fitted["check_max_m"],
    }
    return document


def half_floor_points(clustered):
    court = (
        [(0, 5.8), (5.8, 5.8), (5.8, 9.2), (0, 9.2)]
        if clustered
        else [(0, 0), (14, 0), (14, 15), (0, 15)]
    )
    checks = [(2, 6), (3, 8)] if clustered else [(7, 7.5), (5.8, 5.05)]
    return [
        {
            "image_px": [x * 100, y * 100],
            "court_m": [x, y],
            "role": "calibration" if index < 4 else "check",
        }
        for index, (x, y) in enumerate([*court, *checks])
    ]


SCHEMA_VIOLATIONS = {
    "no landmarks": lambda d: d["court"].pop("landmarks"),
    "extra point key": lambda d: d["points"][0].update(label="corner"),
    "extra top-level key": lambda d: d.update(note="x"),
    "extra court key": lambda d: d["court"].update(surface="wood"),
    "fiba court of another size": lambda d: d["court"].update(
        kind="fiba_full", type="fiba_full", length_m=3.0
    ),
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
    court_model(court["type"], court["length_m"], court["width_m"], court["landmarks"])


@pytest.mark.parametrize("kind", ["fiba_full", "custom"])
def test_older_calibration_with_kind_only_remains_valid(kind):
    legacy = copy.deepcopy(EXAMPLE)
    legacy["contract_version"] = "0.9.0"
    legacy["court"].pop("type")
    legacy["court"]["kind"] = kind
    if kind == "fiba_full":
        from services.edge.calibration.court import court_model

        full = court_model("fiba_full")
        legacy["court"].update(length_m=28, width_m=15, landmarks=full.landmarks)
    validated = validate_calibration(legacy)
    assert validated["court"]["type"] == kind
    assert "type" not in legacy["court"]  # reading never rewrites the saved input object


@pytest.mark.parametrize("version", ["0.10.0", "0.11.0", "0.12.0", "0.13.0"])
def test_a_calibration_saved_under_an_earlier_version_still_loads(version):
    """0.11.0 to 0.14.0 change no calibration format, so files saved under them stay usable."""
    saved = copy.deepcopy(EXAMPLE)
    saved["contract_version"] = version
    assert validate_calibration(saved)["calibration_id"] == EXAMPLE["calibration_id"]


@pytest.mark.parametrize("version", ["0.14.0", "0.15.0", "0.16.0", "0.17.0", "0.18.0"])
def test_a_calibration_saved_under_0_14_to_0_18_validates_and_loads(version, tmp_path):
    """Those bumps changed run.json, sessions and API fields, not the calibration format (B6)."""
    saved = copy.deepcopy(EXAMPLE)
    saved["contract_version"] = version
    assert validate_calibration(saved)["contract_version"] == version
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert load_calibration(path)["calibration_id"] == EXAMPLE["calibration_id"]


def test_half_court_calibration_schema_accepts_type_and_bounds():
    half = half_calibration_for(half_floor_points(clustered=False))
    Draft202012Validator(SCHEMA).validate(half)
    assert validate_calibration(half)["court"]["type"] == "fiba_half"


def test_saved_half_court_calibration_rejects_fit_points_clustered_in_the_key(tmp_path):
    saved = half_calibration_for(half_floor_points(clustered=True))
    path = tmp_path / "clustered-half-calibration.json"
    path.write_text(json.dumps(saved), encoding="utf-8")

    with pytest.raises(ValueError, match="20%.*fit points too close together"):
        load_calibration(path)


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
