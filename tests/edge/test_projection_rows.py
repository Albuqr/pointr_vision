"""A calibrated row whose point cannot be projected (on or beyond the horizon, or not finite)
has empty x_m, y_m and in_court in tracks.csv, and is excluded from the report."""

import csv
import time
import uuid
from dataclasses import replace

import pytest

from services.edge.perception.types import TrackObs
from services.edge.reports.build import build_report
from services.edge.session.types import RunCounts
from services.edge.session.writer import FileSessionWriter
from tests.edge.test_report import dense, make_run, track_of, value
from tests.edge.test_session import meta, run_meta

HORIZON = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -0.01, 1.0]]  # w = 1 - 0.01 * y, 0 at y = 100


def calibration(matrix=HORIZON):
    return {
        "calibration_id": str(uuid.uuid4()),
        "check_error_m": 0.1,
        "homography_image_to_court": matrix,
        "court": {"length_m": 28.0, "width_m": 15.0},
        "image_size": {"width": 640, "height": 360},
    }


def tracks_csv(tmp_path, boxes, matrix=HORIZON):
    writer = FileSessionWriter(tmp_path)
    run = replace(run_meta(), calibration=calibration(matrix))
    writer.start(meta(), run)
    writer.set_t0(time.perf_counter(), "2026-10-13T12:00:01Z")
    for seq, box in enumerate(boxes):
        writer.tracks(seq, [TrackObs(1, box, 0.9, None)])
    writer.close("ended", RunCounts(len(boxes), len(boxes), 0, 0))
    with open(writer.dir / "runs" / run.run_id / "tracks.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_writer_leaves_horizon_rows_empty_instead_of_the_court_corner(tmp_path):
    ahead, on_horizon, beyond = tracks_csv(
        tmp_path, [(0, 0, 40, 50), (0, 0, 40, 100), (0, 0, 40, 150)]
    )
    assert (ahead["x_m"], ahead["y_m"], ahead["in_court"]) == ("40.0000", "100.0000", "false")
    for row in (on_horizon, beyond):
        assert row["x_m"] == row["y_m"] == row["in_court"] == ""
        assert row["position_method"] == "box_bottom_center" and row["calibration_id"]


def test_report_excludes_unprojectable_rows_from_path_and_says_so(tmp_path):
    # y = 100 is the horizon: those rows must not become (0, 0) points
    rows = [(0, 1, 10, 40), (1, 1, 20, 40), (2, 1, 30, 100), (3, 1, 40, 100), (4, 1, 50, 40)]
    run_dir = make_run(tmp_path, dense(5), rows, calibration=calibration())
    report = build_report(run_dir)
    # kept samples are (16.67, 66.67), (33.33, 66.67) and (83.33, 66.67) m; the 1.5 s interval
    # that spans the dropped pair is over max_gap, so only the first step counts
    assert value(track_of(report, 1)["path_length"]) == pytest.approx(50 / 3)
    assert any("2 track row(s) could not be projected" in note for note in report.caveats)
