"""PHASE_03 B12: a camera that sees only part of the court is calibrated from the landmarks it
sees. A synthetic pinhole camera on the sideline sees one half of a FIBA full court; the fit and
check points are its projections of that half's landmarks (no camera, no weights)."""

import math
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from services.edge import contract
from services.edge.calibration.court import court_model
from services.edge.calibration.document import load_calibration
from services.edge.calibration.homography import CalibrationPositions
from services.edge.perception.loop import NO_DETECTIONS
from services.edge.perception.types import Detections
from tests.app import test_api
from tests.edge.test_session import EvenFrameDetector, load, run_main, session_files, validate
from tests.fixtures.make_clips import HEIGHT, WIDTH, make_clips

ROOT = Path(__file__).resolve().parents[2]
COURT = court_model("fiba_full")
# Seen from the sideline, these four spread floor marks are foreshortened into a thin band of
# the image (spread ratio about 0.09), the shape the 0.1 image-spread rule refused (D-050).
FIT = ("centre_line_right", "centre_circle", "near_key_near_left", "near_key_near_right")
CHECK = ("near_key_far_left", "near_basket_floor")


def sideline_camera(position=(7.0, -4.0, 3.0), target=(7.0, 7.5, 0.0), hfov_deg=90.0):
    """Court metres (x, y, 0) -> image pixels of a pinhole camera at `position` aimed at `target`,
    at the fixture clip's size; None for a point behind the camera or outside the frame."""
    position, target = np.asarray(position), np.asarray(target)
    focal = (WIDTH / 2) / math.tan(math.radians(hfov_deg) / 2)
    intrinsics = np.array([[focal, 0, WIDTH / 2], [0, focal, HEIGHT / 2], [0, 0, 1]])
    forward = (target - position) / np.linalg.norm(target - position)
    right = np.cross(forward, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    rotation = np.stack([right, np.cross(forward, right), forward])

    def project(court_m):
        camera = rotation @ (np.array([court_m[0], court_m[1], 0.0]) - position)
        if camera[2] <= 0:
            return None
        u, v, _ = intrinsics @ (camera / camera[2])
        return (float(u), float(v)) if 0 <= u < WIDTH and 0 <= v < HEIGHT else None

    return project


def partial_view_points():
    project = sideline_camera()
    points = []
    for role, names in (("calibration", FIT), ("check", CHECK)):
        for name in names:
            court_m = COURT.landmarks[name]
            image_px = project(court_m)
            assert image_px is not None, f"{name} must be in the synthetic frame"
            points.append({"image_px": list(image_px), "court_m": list(court_m), "role": role})
    return points


def test_the_synthetic_camera_sees_one_half_only():
    project = sideline_camera()
    seen = [name for name, point in COURT.landmarks.items() if project(point) is not None]
    assert seen and all(COURT.landmarks[name][0] <= COURT.length_m / 2 for name in seen)
    assert "corner_far_left" not in seen and "far_basket_floor" not in seen


def test_the_fit_points_fill_a_thin_image_band_the_old_ratio_refused():
    from services.edge.calibration.homography import _spread

    fit = [p for p in partial_view_points() if p["role"] == "calibration"]
    assert _spread([p["image_px"] for p in fit]) < 0.1 <= _spread([p["court_m"] for p in fit])


client = test_api.client  # the Studio API fixture, with its fake launcher


def save_partial_calibration(client, tmp_path):
    clip = make_clips(tmp_path)["moving"]
    client.post("/api/cameras", json={"camera_id": "cam1", "source": str(clip), "link": "file"})
    frame = client.get("/api/cameras/cam1/calibration/frame")
    payload = {
        "frame_token": frame.headers["x-frame-token"],
        "court_kind": "fiba_full",
        "length_m": 28,
        "width_m": 15,
        "max_check_error_m": 0.5,
        "points": partial_view_points(),
    }
    fitted = client.post("/api/cameras/cam1/calibration/fit", json=payload)
    assert fitted.status_code == 200, fitted.text
    saved = client.put("/api/cameras/cam1/calibration", json=payload)
    assert saved.status_code == 200, saved.text
    return saved.json(), Path(saved.json()["path"]), clip


def test_partial_view_calibration_saves_and_reports_each_check_error(client, tmp_path):
    result, path, _ = save_partial_calibration(client, tmp_path)
    assert len(result["check_errors_m"]) == len(CHECK)
    assert result["check_mean_m"] == pytest.approx(np.mean(result["check_errors_m"]))
    assert result["check_max_m"] == pytest.approx(max(result["check_errors_m"]))
    assert result["check_mean_m"] < 1e-6  # exact synthetic projections
    assert result["point_errors_m"][len(FIT) :] == result["check_errors_m"]
    document = result["calibration"]
    Draft202012Validator(contract.schema("calibration")).validate(document)
    checks = [p for p in document["points"] if p["role"] == "check"]
    assert [p["residual_m"] for p in checks] == pytest.approx(result["check_errors_m"])
    assert document["errors"]["check_mean_m"] == pytest.approx(result["check_mean_m"])
    assert load_calibration(path)["calibration_id"] == document["calibration_id"]


def test_saved_partial_calibration_projects_the_seen_area():
    from services.edge.calibration.homography import fit_calibration

    fitted = fit_calibration(partial_view_points())
    positions = CalibrationPositions(
        {"calibration_id": "x", "court": {"length_m": 28.0, "width_m": 15.0}, **fitted}
    )
    project = sideline_camera()
    for court_m in [(3.0, 3.0), (10.0, 12.0), (12.0, 6.0)]:  # floor in the seen half
        image_px = project(court_m)
        assert positions(*image_px) == pytest.approx(court_m, abs=1e-6)
        assert positions.in_court(*court_m)


def test_partial_calibration_records_metre_tracks_and_a_valid_run_block(
    client, monkeypatch, tmp_path, clips
):
    result, path, _ = save_partial_calibration(client, tmp_path)
    floor = (6.0, 9.0)  # in the seen half
    u, v = sideline_camera()(floor)

    class OnePersonAtTheFloorPoint(EvenFrameDetector):
        def detect(self, frame):
            if frame.seq % 2:
                return NO_DETECTIONS
            box = np.array([[u - 10, v - 60, u + 10, v]], np.float32)  # bottom centre at (u, v)
            return Detections(box, np.array([0.9], np.float32), np.array([1]))

    out = tmp_path / "out"
    code = run_main(
        monkeypatch,
        out,
        "--source",
        str(clips["moving"]),
        "--link",
        "file",
        "--camera-id",
        "cam1",
        "--calibration",
        str(path),
        detector=OnePersonAtTheFloorPoint(),
    )
    assert code == 0
    _, run, _, tracks = session_files(out)
    validate("run", run)
    assert run["calibration"]["calibration_id"] == result["calibration"]["calibration_id"]
    assert run["calibration"]["check_error_m"] == pytest.approx(result["check_mean_m"])
    assert run["calibration"]["court"] == {"type": "fiba_full", "length_m": 28, "width_m": 15}
    first = tracks[0]
    assert (float(first["x_m"]), float(first["y_m"])) == pytest.approx(floor, abs=1e-3)
    assert first["in_court"] == "true"
    assert load(path)["camera_id"] == "cam1"
