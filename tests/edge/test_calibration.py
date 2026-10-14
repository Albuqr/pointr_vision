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
    with pytest.raises(ValueError, match="image_size/width"):
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


def test_half_court_perspective_fit_checks_known_points_within_one_micrometre():
    import cv2

    court = np.float32([[0, 0], [14, 0], [14, 15], [0, 15]])
    image = np.float32([[300, 900], [1100, 900], [1000, 300], [450, 300]])
    to_image = cv2.getPerspectiveTransform(court, image).astype(np.float64)

    def point_at(x, y, role="calibration"):
        px, py = cv2.perspectiveTransform(np.float64([[[x, y]]]), to_image)[0, 0]
        return {"image_px": [float(px), float(py)], "court_m": [x, y], "role": role}

    source = [
        point_at(0, 0), point_at(14, 0), point_at(14, 15), point_at(0, 15),
        point_at(7, 7.5, "check"), point_at(5.8, 5.05, "check"),
    ]
    result = fit_calibration(source, court_dimensions=(14, 15))
    assert result["check_mean_m"] < 1e-6
    assert result["check_max_m"] < 1e-6


def test_half_court_fit_rejects_key_cluster_and_accepts_baseline_to_midcourt():
    key = [point(0, 5.8), point(5.8, 5.8), point(5.8, 9.2), point(0, 9.2)]
    key += [point(2, 6, "check"), point(3, 8, "check")]
    message = (
        "20%.*fit points too close together, add the baseline corners or midcourt line points "
        "or measured floor marks"
    )
    with pytest.raises(ValueError, match=message):
        fit_calibration(key, court_dimensions=(14, 15))

    spanning = [point(0, 0), point(14, 0), point(14, 15), point(0, 15)]
    spanning += [point(7, 7.5, "check"), point(5.8, 5.05, "check")]
    fit_calibration(spanning, court_dimensions=(14, 15))


def test_in_court_uses_full_or_half_bounds_without_clamping_positions():
    half = positions_for([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    half.length_m = 14.0
    full = positions_for([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    full.length_m = 28.0
    assert half(14.5, 7.5) == (14.5, 7.5)
    assert not half.in_court(14.5, 7.5)
    assert full.in_court(14.5, 7.5)


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


@pytest.mark.parametrize("scale", [1e-12, 1e12])
def test_projection_is_invariant_to_homography_scale(scale):
    scaled = [[value * scale for value in row] for row in HORIZON]
    assert project_image_to_court(scaled, (40.0, 50.0)) == pytest.approx((80.0, 100.0))
    assert positions_for(scaled)(40.0, 100.0) is None


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
    document["homography_image_to_court"][2] = [0.0, -0.01, 1.0]  # saved points cross w = 0
    with pytest.raises(ValueError, match="horizon"):
        validate_calibration(document)


def test_validator_normalizes_an_equivalent_homography_with_reversed_global_sign():
    document = json.loads((ROOT / "tests/fixtures/contracts/calibration.example.json").read_text())
    document["homography_image_to_court"] = [
        [-value for value in row] for row in document["homography_image_to_court"]
    ]
    validated = validate_calibration(document)
    np.testing.assert_allclose(
        validated["homography_image_to_court"],
        [[0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 1.0]],
    )


def test_fit_refuses_duplicate_image_points_even_with_save_anyway():
    source = points()
    source[1]["image_px"] = list(source[0]["image_px"])  # two fit points at one pixel
    with pytest.raises(ValueError, match="same image position"):
        fit_calibration(source, save_anyway=True, enforce_limit=False)


# -- hold-out integrity ---------------------------------------------------------------------


def test_check_point_at_a_fit_points_court_position_is_refused():
    """The reviewed hole: a 3 m mislabel passed with check error 4e-7 because both 'check'
    points were the fit points again."""
    source = points()
    source[0]["court_m"] = [3.0, 3.0]  # one corner mislabelled by 3 m
    source[4] = {**source[1], "role": "check"}  # a check point on a fit point's mark
    source[5] = {**source[2], "role": "check"}
    with pytest.raises(ValueError, match="same (court|image) position"):
        fit_calibration(source, save_anyway=True)


@pytest.mark.parametrize("offset", [0.5, 1.0])
def test_check_point_within_one_fit_pixel_is_refused_even_at_another_court_position(offset):
    source = points()
    source[4] = {
        **source[4],
        "image_px": [source[0]["image_px"][0] + offset, source[0]["image_px"][1]],
    }
    with pytest.raises(ValueError, match="same image position"):
        fit_calibration(source)


def test_two_check_points_on_one_mark_are_refused():
    source = points()
    source[5] = {**source[4]}
    with pytest.raises(ValueError, match="same (court|image) position"):
        fit_calibration(source)


def test_collinear_fit_points_are_a_clean_error_not_a_crash():
    source = [point(x, 5, "calibration") for x in range(4)] + points()[4:]
    with pytest.raises(ValueError, match="collinear or bunched"):
        fit_calibration(source)


def test_fit_points_bunched_in_a_sliver_are_refused():
    sliver = [
        {"image_px": [0, 0], "court_m": [0, 0], "role": "calibration"},
        {"image_px": [1000, 0], "court_m": [10, 0], "role": "calibration"},
        {"image_px": [1000, 5], "court_m": [10, 0.05], "role": "calibration"},
        {"image_px": [0, 5], "court_m": [0, 0.05], "role": "calibration"},
    ] + points()[4:]
    with pytest.raises(ValueError, match="collinear or bunched"):
        fit_calibration(sliver)


@pytest.mark.parametrize("limit", [2.5, 100.0, float("inf"), 0.0])
def test_the_error_limit_is_capped_at_two_metres(limit):
    with pytest.raises(ValueError, match="at most 2.0 m"):
        fit_calibration(points(), max_check_error_m=limit)


def fixture_document():
    return json.loads((ROOT / "tests/fixtures/contracts/calibration.example.json").read_text())


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d["errors"].update(check_mean_m=0.01), "check_mean_m does not match"),
        (lambda d: d["points"][4].update(residual_m=0.3), "residual does not match"),
        (lambda d: d.update(forced=True), "forced flag does not match"),
        (lambda d: d.update(max_check_error_m=5.0), "maximum of 2.0"),
        (lambda d: d["points"][4].update(court_m=list(d["points"][0]["court_m"])), "same"),
    ],
)
def test_validator_recomputes_errors_and_holdout_instead_of_trusting_the_file(edit, message):
    document = fixture_document()
    edit(document)
    with pytest.raises(ValueError, match=message):
        validate_calibration(document)


# -- RANSAC: which fit points were left out, and the threshold ---------------------------------


def test_fit_reports_the_ransac_threshold_and_no_dropped_points_for_a_clean_fit():
    result = fit_calibration(perspective_points())
    assert result["ransac_threshold_m"] == 0.1
    assert result["ransac_dropped_points"] == []


def test_fit_reports_which_point_ransac_left_out():
    source = perspective_points()
    outlier = {**source[5], "role": "calibration", "court_m": [2.0, 12.0]}  # wrong court position
    source = [*source[:5], outlier]  # four good fit points, one check, one outlier fit point
    result = fit_calibration(source, enforce_limit=False, require_checks=False)
    # five fit points, one of them inconsistent: RANSAC keeps four (which four is its choice, so
    # the report names the one it left out, by its index in the list that was passed in)
    [dropped] = result["ransac_dropped_points"]
    assert dropped in (0, 1, 2, 3, 5) and source[dropped]["role"] == "calibration"
