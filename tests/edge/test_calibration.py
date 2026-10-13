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


# -- projection guard: explicit homogeneous divide (OpenCV 5 returns (0, 0) where w = 0) ----------

HORIZON = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -0.01, 1.0]]  # w = 1 - 0.01 * y: 0 at y = 100


def perspective_points():
    """Six points seen through a real perspective (a trapezoid), not a scale-only affine."""
    import cv2

    court = np.float32([[0, 0], [28, 0], [28, 15], [0, 15]])
    image = np.float32([[300, 900], [1700, 900], [1450, 300], [550, 300]])
    to_image = cv2.getPerspectiveTransform(court, image)

    def seen(x, y, role):
        u, v = cv2.perspectiveTransform(np.float64([[[x, y]]]), to_image.astype(np.float64))[0, 0]
        return {"image_px": [float(u), float(v)], "court_m": [x, y], "role": role}

    fit = [seen(0, 0, "calibration"), seen(28, 0, "calibration"), seen(28, 15, "calibration")]
    fit.append(seen(0, 15, "calibration"))
    return [*fit, seen(14, 7.5, "check"), seen(5.8, 5.05, "check")]


def positions_for(matrix):
    from services.edge.calibration.homography import CalibrationPositions

    return CalibrationPositions(
        {
            "calibration_id": "3f1c2a8e-5b7d-4e9a-8c21-6d4f0b9e7a13",
            "homography_image_to_court": matrix,
            "court": {"length_m": 28.0, "width_m": 15.0},
        }
    )


def test_true_perspective_fit_recovers_metres_and_check_error():
    result = fit_calibration(perspective_points())
    assert result["calibration_mean_m"] < 1e-6 and result["check_mean_m"] < 1e-6
    far = perspective_points()[2]
    assert project_image_to_court(result["homography_image_to_court"], far["image_px"]) == (
        pytest.approx((28, 15), abs=1e-6)
    )


def test_point_on_the_horizon_has_no_position_instead_of_the_origin():
    positions = positions_for(HORIZON)
    assert positions(40.0, 50.0) == pytest.approx(
        (80.0, 100.0)
    )  # in front: w = 0.5, a normal divide
    assert positions(40.0, 100.0) is None  # w = 0: OpenCV 5 would say (0, 0), the court corner
    with pytest.raises(ValueError):
        project_image_to_court(HORIZON, (40.0, 100.0))


def test_point_beyond_the_horizon_is_invalid_not_mirrored():
    assert positions_for(HORIZON)(40.0, 150.0) is None  # w < 0
    assert positions_for(HORIZON)(40.0, 99.9999999) is None  # w below the epsilon


@pytest.mark.parametrize("x, y", [(float("nan"), 10.0), (10.0, float("inf"))])
def test_non_finite_point_has_no_position(x, y):
    assert positions_for(HORIZON)(x, y) is None


@pytest.mark.parametrize(
    "matrix",
    [
        [[0, 0, 0], [0, 0, 0], [0, 0, 1]],  # singular
        [[1e308, 0, 0], [0, 1e308, 0], [0, 0, 1]],  # finite, but cond 1e308
        [[1, 0, 0], [0, 1, 0], [0, 0, float("nan")]],
    ],
)
def test_validate_rejects_singular_ill_conditioned_and_non_finite_homographies(matrix):
    document = json.loads((ROOT / "tests/fixtures/contracts/calibration.example.json").read_text())
    document["homography_image_to_court"] = matrix
    with pytest.raises(ValueError):
        validate_calibration(document)


def test_validate_rejects_a_homography_whose_points_are_beyond_the_horizon():
    document = json.loads((ROOT / "tests/fixtures/contracts/calibration.example.json").read_text())
    document["homography_image_to_court"] = [
        [-v for v in row] for row in document["homography_image_to_court"]
    ]  # w < 0
    with pytest.raises(ValueError, match="horizon"):
        validate_calibration(document)


def test_fit_refuses_duplicate_image_points_even_with_save_anyway():
    source = points()
    source[1]["image_px"] = list(source[0]["image_px"])  # two fit points at one pixel
    with pytest.raises(ValueError, match="singular|conditioned|RANSAC"):
        fit_calibration(source, save_anyway=True, enforce_limit=False)
