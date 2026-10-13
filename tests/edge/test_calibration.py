import copy
import json
import uuid

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from services.edge.calibration.document import load_calibration, validate_calibration
from services.edge.calibration.homography import (
    fit_calibration,
    project_court_to_image,
    project_image_to_court,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


def point(x, y, role="calibration"):
    return {"image_px": [x * 100, y * 100], "court_m": [x, y], "role": role}


def points():
    return [
        point(0, 0),
        point(4, 0),
        point(4, 3),
        point(0, 3),
        point(1, 1, "check"),
        point(3, 2, "check"),
    ]


def test_known_homography_projects_exact_metres_and_round_trips():
    result = fit_calibration(points())
    assert project_image_to_court(result["homography_image_to_court"], (250, 175)) == pytest.approx(
        (2.5, 1.75)
    )
    image = project_court_to_image(result["homography_image_to_court"], (2.5, 1.75))
    assert image == pytest.approx((250, 175))
    assert result["calibration_mean_m"] < 1e-8
    assert result["check_mean_m"] < 1e-8


def test_preview_fit_can_project_with_four_fit_points_before_check_points():
    result = fit_calibration(points()[:4], require_checks=False)
    assert result["check_mean_m"] is None
    assert len(result["calibration_errors_m"]) == 4
    with pytest.raises(ValueError, match="two separate check"):
        fit_calibration(points()[:4])


def test_check_error_uses_held_out_points_not_fit_points():
    source = points()
    good = fit_calibration(source)
    source[-1]["court_m"] = [4, 4]
    bad = fit_calibration(source, enforce_limit=False)
    np.testing.assert_allclose(
        bad["homography_image_to_court"], good["homography_image_to_court"], atol=1e-8
    )
    assert bad["check_mean_m"] > 0.1
    assert bad["calibration_mean_m"] < 1e-8


@pytest.mark.parametrize(
    "source, message",
    [
        (points()[:5], "two separate check"),
        ([*points()[:3], *points()[4:]], "four calibration"),
    ],
)
def test_minimum_point_roles_are_required(source, message):
    with pytest.raises(ValueError, match=message):
        fit_calibration(source)


def test_high_error_requires_explicit_force_and_records_override():
    source = points()
    source[-1]["court_m"] = [4, 2]
    with pytest.raises(ValueError, match="exceeds"):
        fit_calibration(source, max_check_error_m=0.05)
    result = fit_calibration(source, max_check_error_m=0.05, save_anyway=True)
    assert result["forced"] is True


def test_calibration_document_is_validated_and_loadable(tmp_path):
    fixture = json.loads((ROOT / "tests/fixtures/contracts/calibration.example.json").read_text())
    Draft202012Validator(
        json.loads((ROOT / "contracts/calibration.schema.json").read_text())
    ).validate(fixture)
    validate_calibration(fixture)
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    assert load_calibration(path)["calibration_id"] == fixture["calibration_id"]
    invalid = copy.deepcopy(fixture)
    invalid["image_size"]["width"] = 0
    with pytest.raises(ValueError, match="dimensions"):
        validate_calibration(invalid)


def test_point_helper_fixture_uses_deterministic_coordinates():
    assert point(2, 1)["image_px"] == [200, 100]
    assert uuid.UUID("3f1c2a8e-5b7d-4e9a-8c21-6d4f0b9e7a13").version == 4
