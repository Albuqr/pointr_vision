"""The report of a calibrated run: unprojectable rows are excluded and counted, they are not
"malformed CSV rows", and the caveats name the calibration and its held-out error."""

import uuid

from services.edge.reports.build import build_report
from tests.edge.test_report import dense, make_run

HORIZON = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -0.01, 1.0]]  # w = 0 at y = 100


def calibration(error=0.12):
    return {
        "calibration_id": str(uuid.uuid4()),
        "check_error_m": error,
        "homography_image_to_court": HORIZON,
        "court": {"length_m": 28, "width_m": 15},
        "image_size": {"width": 640, "height": 360},
    }


def test_unprojectable_rows_are_counted_apart_from_malformed_rows(tmp_path):
    rows = [(0, 1, 10, 40), (1, 1, 20, 40), (2, 1, 30, 100), (3, 1, 40, 150), (4, 1, 50, 40)]
    report = build_report(make_run(tmp_path, dense(5), rows, calibration=calibration()))
    notes = " ".join(report.caveats)
    assert "2 track row(s) could not be projected" in notes
    assert "excluded from path length and speeds" in notes
    assert "malformed" not in notes  # a projection failure is not a broken CSV


def test_calibrated_caveats_name_the_calibration_and_its_held_out_error(tmp_path):
    cal = calibration(0.123)
    report = build_report(make_run(tmp_path, dense(5), [(0, 1, 10, 40)], calibration=cal))
    text = " ".join(report.caveats)
    assert cal["calibration_id"] in text and "0.123 m" in text


def test_uncalibrated_report_has_no_calibration_caveat(tmp_path):
    report = build_report(make_run(tmp_path, dense(5), [(0, 1, 10, 40)]))
    assert not any(c.startswith("Calibration ") for c in report.caveats)
