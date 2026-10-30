"""A calibrated row whose point cannot be projected (on or beyond the horizon, or not finite)
has empty x_m, y_m and in_court in tracks.csv, and is excluded from the report."""

import csv
import json
import time
import uuid
from dataclasses import replace

import pytest

from services.edge.calibration.homography import CalibrationPositions
from services.edge.perception.types import TrackObs
from services.edge.reports.build import build_report
from services.edge.session.types import RunCounts
from services.edge.session.writer import FileSessionWriter
from tests.edge.fakes import meta, sample_run_meta
from tests.edge.test_report import dense, make_run, track_of, value
from tests.edge.test_session import rec

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
    document = calibration(matrix)
    run = replace(sample_run_meta(), calibration=document)
    writer.start(meta(), run, CalibrationPositions(document))
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
    assert value(track_of(report, 1)["path_length"]) == pytest.approx(50 / 3, abs=0.001)
    assert any("2 track row(s) could not be projected" in note for note in report.caveats)


# -- the writer survives any projection error -------------------------------------------------

NAN = float("nan")
SINGULAR = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
HUGE = [[1e308, 0.0, 0.0], [0.0, 1e308, 0.0], [0.0, 0.0, 1.0]]


def run_calibrated(tmp_path, boxes, positions, matrix=HORIZON):
    """Frames and tracks through a real writer; returns (writer, session.json, frames, tracks)."""
    writer = FileSessionWriter(tmp_path)
    run = replace(sample_run_meta(), calibration=calibration(matrix))
    writer.start(meta(), run, positions)
    writer.set_t0(time.perf_counter(), "2026-10-13T12:00:01Z")
    for seq, box in enumerate(boxes):
        writer.frame(rec(seq))
        writer.tracks(seq, [TrackObs(1, box, 0.9, None)])
    writer.close("ended", RunCounts(len(boxes), len(boxes), 0, 0))
    folder = writer.dir / "runs" / run.run_id
    read = lambda name: list(csv.DictReader(open(folder / name, newline="", encoding="utf-8")))  # noqa: E731
    return (
        writer,
        json.loads((writer.dir / "session.json").read_text()),
        read("frames.csv"),
        read("tracks.csv"),
    )


@pytest.mark.parametrize(
    "matrix, box",
    [
        (HORIZON, (0, 0, NAN, 50)),  # a NaN box
        (HUGE, (0, 0, 40, 50)),  # a 1e308 homography: finite, overflows when projected
        (SINGULAR, (0, 0, 40, 50)),  # a singular matrix
    ],
    ids=["nan-box", "1e308", "singular"],
)
def test_bad_projection_never_stops_the_writer(tmp_path, matrix, box):
    boxes = [(0, 0, 40, 50), box, (0, 0, 40, 50), box, (0, 0, 40, 50)]
    writer, session, frames, tracks = run_calibrated(
        tmp_path, boxes, CalibrationPositions(calibration(matrix)), matrix
    )
    assert session["status"] == "ended" and writer.error is None
    assert len(frames) == len(tracks) == 5  # every row is there
    for index in (1, 3):  # the bad rows have no position, never 0 or true
        assert tracks[index]["x_m"] == tracks[index]["y_m"] == tracks[index]["in_court"] == ""
    errors = [e for e in session["events"] if e["kind"] == "error"]
    assert errors and "no metre position" in errors[-1]["detail"]
    assert writer.unprojected >= 2


class Exploding:
    """A projector that raises, as a bug in a future map would."""

    calibration_id = "3f1c2a8e-5b7d-4e9a-8c21-6d4f0b9e7a13"

    def __call__(self, x, y):
        raise RuntimeError("boom")

    def in_court(self, x, y):
        return True


def test_a_raising_projector_gives_empty_positions_and_one_rate_limited_event(tmp_path):
    boxes = [(0, 0, 40, 50)] * 200
    writer, session, frames, tracks = run_calibrated(tmp_path, boxes, Exploding())
    assert session["status"] == "ended" and len(frames) == len(tracks) == 200
    assert all(row["x_m"] == "" and row["calibration_id"] for row in tracks)
    assert writer.unprojected == 200
    events = [e for e in session["events"] if e["kind"] == "error"]
    assert 1 <= len(events) <= 2  # the first failure, and the final count at close
    assert "boom" in events[0]["detail"] and "200 track row(s)" in events[-1]["detail"]


def test_a_bad_track_row_does_not_stop_the_writer_or_lose_its_frame(tmp_path):
    writer = FileSessionWriter(tmp_path)
    run = replace(sample_run_meta(), calibration=calibration())
    writer.start(meta(), run, CalibrationPositions(calibration()))
    writer.set_t0(time.perf_counter(), "2026-10-13T12:00:01Z")
    for seq in range(3):
        writer.frame(rec(seq))
        confidence = "not a number" if seq == 1 else 0.9
        writer.tracks(seq, [TrackObs(1, (0, 0, 40, 50), confidence, None)])
    writer.close("ended", RunCounts(3, 3, 0, 0))

    folder = writer.dir / "runs" / run.run_id
    with (folder / "frames.csv").open(newline="", encoding="utf-8") as stream:
        frames = list(csv.DictReader(stream))
    with (folder / "tracks.csv").open(newline="", encoding="utf-8") as stream:
        tracks = list(csv.DictReader(stream))
    session = json.loads((writer.dir / "session.json").read_text(encoding="utf-8"))
    assert session["status"] == "ended" and writer.error is None
    assert len(frames) == len(tracks) == 3
    assert tracks[1]["x_m"] == tracks[1]["y_m"] == tracks[1]["in_court"] == ""
    assert any("track row error" in event["detail"] for event in session["events"])


def test_the_writer_does_not_import_the_calibration_package():
    import services.edge.session.writer as writer_module

    assert not hasattr(writer_module, "CalibrationPositions")


def test_a_calibrated_run_without_positions_is_refused(tmp_path):
    run = replace(sample_run_meta(), calibration=calibration())
    with pytest.raises(ValueError, match="needs positions"):
        FileSessionWriter(tmp_path).start(meta(), run)
