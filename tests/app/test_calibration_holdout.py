"""The calibration API refuses point sets that cannot test themselves: a message, never a 500."""

import pytest
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from tests.app.test_api import FakeLauncher
from tests.fixtures.make_clips import make_clips


@pytest.fixture
def client_and_token(tmp_path):
    clip = make_clips(tmp_path)["moving"]
    config = CameraConfig(tmp_path / "config.json")
    config.write([{"camera_id": "clip", "source": str(clip), "link": "file"}])
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        token = client.get("/api/cameras/clip/calibration/frame").headers["x-frame-token"]
        yield client, token


def point(image, court, role):
    return {"image_px": list(image), "court_m": list(court), "role": role}


def payload(token, points, **extra):
    return {
        "frame_token": token,
        "court_kind": "custom",
        "length_m": 4,
        "width_m": 3,
        "max_check_error_m": 0.5,
        "points": points,
        **extra,
    }


GOOD_FIT = [
    point((0, 0), (0, 0), "calibration"),
    point((400, 0), (4, 0), "calibration"),
    point((400, 300), (4, 3), "calibration"),
    point((0, 300), (0, 3), "calibration"),
]


def test_collinear_fit_points_are_422_with_a_message_not_500(client_and_token):
    client, token = client_and_token
    line = [point((i * 100, 50), (i, 1), "calibration") for i in range(4)]
    line += [point((50, 200), (0.5, 2), "check"), point((250, 220), (2.5, 2.2), "check")]
    for url in ("/api/cameras/clip/calibration/fit", "/api/cameras/clip/calibration"):
        verb = client.post if url.endswith("fit") else client.put
        response = verb(url, json=payload(token, line))
        assert response.status_code == 422, response.text
        assert "collinear" in response.text


def test_a_check_point_on_a_fit_point_is_refused_when_saving(client_and_token):
    client, token = client_and_token
    checks = [point((400, 300), (4, 3), "check"), point((0, 300), (0, 3), "check")]
    response = client.put("/api/cameras/clip/calibration", json=payload(token, GOOD_FIT + checks))
    assert response.status_code == 422 and "same" in response.text


def test_an_error_limit_above_two_metres_is_refused(client_and_token):
    client, token = client_and_token
    checks = [point((100, 100), (1, 1), "check"), point((300, 200), (3, 2), "check")]
    response = client.put(
        "/api/cameras/clip/calibration",
        json=payload(token, GOOD_FIT + checks, max_check_error_m=100),
    )
    assert response.status_code == 422 and "at most 2.0" in response.text


def test_half_court_fit_accepts_baseline_and_midcourt_and_refuses_key_cluster(client_and_token):
    client, token = client_and_token
    bounds = {"court_kind": "fiba_half", "length_m": 14, "width_m": 15}
    spanning = [
        point((0, 0), (0, 0), "calibration"),
        point((400, 0), (14, 0), "calibration"),
        point((400, 300), (14, 15), "calibration"),
        point((0, 300), (0, 15), "calibration"),
        point((200, 150), (7, 7.5), "check"),
        point((165, 101), (5.8, 5.05), "check"),
    ]
    response = client.post(
        "/api/cameras/clip/calibration/fit", json=payload(token, spanning, **bounds)
    )
    assert response.status_code == 200, response.text
    assert response.json()["court"]["type"] == "fiba_half"
    assert response.json()["court"]["length_m"] == 14

    clustered = [
        point((0, 100), (0, 5.8), "calibration"),
        point((200, 100), (5.8, 5.8), "calibration"),
        point((200, 200), (5.8, 9.2), "calibration"),
        point((0, 200), (0, 9.2), "calibration"),
        point((60, 120), (1.7, 6.5), "check"),
        point((100, 180), (2.9, 8.5), "check"),
    ]
    response = client.post(
        "/api/cameras/clip/calibration/fit", json=payload(token, clustered, **bounds)
    )
    assert response.status_code == 422
    assert "20%" in response.text and "fit points too close together" in response.text
