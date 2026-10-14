"""The report of a calibrated run: unprojectable rows are excluded and counted, they are not
"malformed CSV rows", and the caveats name the calibration and its held-out error."""

import csv
import uuid

import pytest

from services.edge.reports.build import build_report, write_report
from services.edge.reports.movement import Params
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


def test_unprojectable_tracks_do_not_look_like_a_failure_to_form_tracks(tmp_path):
    run_dir = make_run(
        tmp_path,
        dense(5),
        [(seq, 1, 10 + seq * 10, 100) for seq in range(5)],
        calibration=calibration(),
    )
    report = build_report(run_dir)
    text = " ".join(report.caveats)
    assert "track rows were present, but none had a valid projected position" in text.lower()
    assert "no track formed" not in text.lower()


def test_uncalibrated_report_has_no_calibration_caveat(tmp_path):
    report = build_report(make_run(tmp_path, dense(5), [(0, 1, 10, 40)]))
    assert not any(c.startswith("Calibration ") for c in report.caveats)


def test_report_honours_empty_positions_written_after_a_frame_size_change(tmp_path):
    run_dir = make_run(
        tmp_path,
        dense(5),
        [(seq, 1, 10 + seq * 10, 40) for seq in range(5)],
        calibration=calibration(),
    )
    tracks_path = run_dir / "tracks.csv"
    with tracks_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
        columns = rows[0].keys()
    rows[2]["x_m"] = rows[2]["y_m"] = rows[2]["in_court"] = ""
    with tracks_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    report = write_report(run_dir, params=Params(max_gap=0.75))
    track = report.tracks[0]
    # Only the valid adjacent pairs on either side count; the missing sample must not be
    # silently reconstructed from its pixel box and bridge the gap.
    assert track.n_samples == 4
    assert track.path_length == pytest.approx(100 / 3, abs=0.001)
    assert any("1 track row(s) could not be projected" in note for note in report.caveats)
