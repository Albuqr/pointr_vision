"""The fixed-size markings of a court (key, circle, basket offset) keep their size on a custom
court; markings that do not fit a small court are left out."""

import math
from pathlib import Path

import pytest

from services.edge.calibration.court import court_lines, court_model

ROOT = Path(__file__).resolve().parents[2]
NOT_ON_A_LINE = {"centre_circle", "near_basket_floor", "far_basket_floor"}


def vertices(court):
    return {(round(x, 9), round(y, 9)) for line in court_lines(court) for x, y in line}


@pytest.mark.parametrize("size", [(26, 14), (30, 16.5), (14, 15)])
def test_every_landmark_is_where_the_diagram_draws_a_feature(size):
    """The diagram is drawn from court_lines: each landmark must be a vertex of a drawn line,
    the centre of the drawn circle, or (basket) a point on the court's centre axis."""
    court = court_model("custom", *size)
    drawn = vertices(court)
    for name, (x, y) in court.landmarks.items():
        if name == "centre_circle":
            circle = max(court_lines(court), key=len)
            assert all(math.dist((x, y), p) == pytest.approx(1.8) for p in circle)
        elif name in NOT_ON_A_LINE:
            assert y == pytest.approx(court.width_m / 2)
        else:
            assert (round(x, 9), round(y, 9)) in drawn, name


def test_every_drawn_vertex_is_inside_the_court():
    for size in [(26, 14), (4, 3), (14, 15)]:
        court = court_model("custom", *size)
        for line in court_lines(court):
            for x, y in line:
                assert -1e-9 <= x <= court.length_m + 1e-9 and -1e-9 <= y <= court.width_m + 1e-9


def test_custom_court_keeps_fixed_length_markings_fixed():
    court = court_model("custom", 26.0, 14.0)
    landmarks = court.landmarks
    assert landmarks["near_key_far_left"] == pytest.approx(
        (5.8, 4.55)
    )  # 7 - 2.45, not 5.05 * 14/15
    assert landmarks["near_key_far_right"] == pytest.approx((5.8, 9.45))
    assert landmarks["far_key_near_left"] == pytest.approx((26 - 5.8, 4.55))
    assert landmarks["near_basket_floor"] == pytest.approx((1.575, 7.0))
    assert landmarks["far_basket_floor"] == pytest.approx((26 - 1.575, 7.0))
    assert landmarks["centre_circle"] == pytest.approx((13.0, 7.0))
    key_widths = {
        round(abs(landmarks[f"{side}_key_far_right"][1] - landmarks[f"{side}_key_far_left"][1]), 9)
        for side in ("near", "far")
    }
    assert key_widths == {4.9}
    circle = max(court_lines(court), key=len)
    assert max(p[0] for p in circle) - min(p[0] for p in circle) == pytest.approx(3.6, abs=0.01)


def test_markings_that_do_not_fit_a_small_court_are_left_out_with_their_landmarks():
    court = court_model("custom", 4.0, 3.0)
    assert "near_key_far_left" not in court.landmarks and "far_basket_floor" not in court.landmarks
    assert {"corner_near_left", "corner_far_right", "centre_circle"} <= set(court.landmarks)
    assert len(court_lines(court)) == 2  # boundary and centre line: no key, no circle


def test_centre_circle_is_omitted_when_its_diameter_exceeds_court_length():
    court = court_model("custom", 3.0, 5.0)
    assert len(court_lines(court)) == 2
    assert all(0 <= x <= 3.0 and 0 <= y <= 5.0 for line in court_lines(court) for x, y in line)


def test_fiba_half_landmarks_reuse_all_full_court_landmarks_at_x_at_most_14():
    full = court_model("fiba_full")
    half = court_model("fiba_half", 14, 15)
    expected = {name: point for name, point in full.landmarks.items() if point[0] <= 14}
    assert {name: half.landmarks[name] for name in expected} == expected
    assert half.landmarks["midcourt_near_corner"] == (14.0, 0.0)
    assert half.landmarks["midcourt_far_corner"] == (14.0, 15.0)
    assert half.landmarks["midcourt_center"] == (14.0, 7.5)
    assert (half.length_m, half.width_m) == (14.0, 15.0)
    assert all(0 <= x <= 14 and 0 <= y <= 15 for line in court_lines(half) for x, y in line)
