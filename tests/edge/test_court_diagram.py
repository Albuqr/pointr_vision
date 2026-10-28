"""The Studio diagram is drawn from the court model the fit uses, so a click on a drawn feature
gives the right metres."""

import math
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.calibration.court import court_lines, court_model
from tests.app.test_api import FakeLauncher

ROOT = Path(__file__).resolve().parents[2]
NOT_ON_A_LINE = {"centre_circle", "near_basket_floor", "far_basket_floor"}


def vertices(court):
    return {(round(x, 9), round(y, 9)) for line in court_lines(court) for x, y in line}


def test_fiba_landmarks_are_the_published_marking_positions():
    landmarks = court_model().landmarks
    assert landmarks["near_key_far_left"] == pytest.approx((5.8, 5.05))
    assert landmarks["near_key_far_right"] == pytest.approx((5.8, 9.95))
    assert landmarks["far_key_far_left"] == pytest.approx((28.0, 5.05))
    assert landmarks["far_key_near_left"] == pytest.approx((22.2, 5.05))
    assert landmarks["near_basket_floor"] == pytest.approx((1.575, 7.5))
    assert landmarks["far_basket_floor"] == pytest.approx((26.425, 7.5))
    assert landmarks["centre_circle"] == pytest.approx((14.0, 7.5))


@pytest.mark.parametrize("size", [(28, 15)])
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
    for size in [(28, 15)]:
        court = court_model("custom", *size)
        for line in court_lines(court):
            for x, y in line:
                assert -1e-9 <= x <= court.length_m + 1e-9 and -1e-9 <= y <= court.width_m + 1e-9


@pytest.fixture
def client(tmp_path):
    config = CameraConfig(tmp_path / "config.json")
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as test_client:
        yield test_client


def test_the_studio_gets_its_diagram_from_the_court_model_endpoint(client):
    body = client.get("/api/court", params={"kind": "custom", "length_m": 28, "width_m": 15}).json()
    court = court_model("custom", 28.0, 15.0)
    assert body["landmarks"].keys() == court.landmarks.keys()
    for name, point in body["landmarks"].items():
        assert tuple(point) == pytest.approx(court.landmarks[name])
    assert [[tuple(p) for p in line] for line in body["lines"]] == court_lines(court)
    refused = client.get("/api/court", params={"kind": "fiba_full", "length_m": 26, "width_m": 14})
    assert refused.status_code == 422


def test_half_court_diagram_endpoint_uses_the_same_landmarks_and_lines_as_fit(client):
    response = client.get(
        "/api/court", params={"kind": "fiba_half", "length_m": 14, "width_m": 15}
    )
    assert response.status_code == 200
    body = response.json()
    court = court_model("fiba_half", 14, 15)
    assert body["kind"] == "fiba_half"
    assert {name: tuple(point) for name, point in body["landmarks"].items()} == court.landmarks
    assert [[tuple(point) for point in line] for line in body["lines"]] == court_lines(court)


def test_the_diagram_is_not_hand_drawn_in_the_ui_source():
    source = (ROOT / "services/app/ui/src/studio.tsx").read_text(encoding="utf-8")
    assert "M1 75H279" not in source and "fibaPoints" not in source
    assert "/api/court" in source
