"""The one rule that turns a box into a court position: bottom-centre, the frame-size guard and
the reasons there is no position. The writer, the tracker and the report all use it."""

import pytest

from services.edge.placement import OUTSIDE_VIEW, Placement, Placer, bottom_centre


class Map:
    calibration_id = "cal-1"

    def __init__(self, project=lambda x, y: (x / 10, y / 10), inside=True):
        self.project, self.inside, self.calls = project, inside, []

    def __call__(self, x, y):
        self.calls.append((x, y))
        return self.project(x, y)

    def in_court(self, x, y):
        return self.inside


SIZE = (640, 360)


def test_bottom_centre_is_the_middle_of_the_bottom_edge():
    assert bottom_centre((10, 20, 110, 220)) == (60.0, 220)


def test_a_box_is_placed_at_its_bottom_centre_in_court_metres():
    positions = Map()
    placement = Placer(positions, SIZE).place((10, 20, 110, 220), SIZE)
    assert placement == Placement((6.0, 22.0), True, None)
    assert positions.calls == [(60.0, 220.0)]  # projected once


def test_in_court_is_the_maps_verdict():
    assert Placer(Map(inside=False), SIZE).place((0, 0, 10, 10), SIZE).in_court is False


def test_a_frame_of_another_size_has_no_position_and_is_not_projected():
    positions = Map()
    placer = Placer(positions, SIZE)
    placement = placer.place((0, 0, 10, 10), (320, 180))
    assert placement == Placement(None, None, placer.size_problem((320, 180)))
    assert "320x180" in placement.why and "640x360" in placement.why
    assert placer.size_problem(SIZE) is None
    assert positions.calls == []


@pytest.mark.parametrize(
    "project, why",
    [
        (lambda x, y: None, OUTSIDE_VIEW),
        (lambda x, y: 1 / 0, "ZeroDivisionError"),
    ],
    ids=["no-position", "raises"],
)
def test_a_point_the_map_cannot_project_gets_a_reason_not_an_error(project, why):
    placement = Placer(Map(project), SIZE).place((0, 0, 10, 10), SIZE)
    assert placement.xy is None and placement.in_court is None
    assert why in placement.why


@pytest.mark.parametrize("box", [(1.0, 2.0), "box", (0, 0, "x", 5)], ids=["short", "text", "nan"])
def test_a_box_that_cannot_be_read_gets_a_reason_not_an_error(box):
    placement = Placer(Map(), SIZE).place(box, SIZE)
    assert placement.xy is None and placement.why


def test_the_calibration_id_is_the_maps_and_never_raises():
    assert Placer(Map(), SIZE).calibration_id == "cal-1"
    assert Placer(object(), SIZE).calibration_id == ""
