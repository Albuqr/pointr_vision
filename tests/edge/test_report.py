"""v0 movement report (D-023): hand-built frames.csv / tracks.csv with known positions and times.
No camera, no weights, no real session data."""

import copy
import csv
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from services.edge.reports import cli
from services.edge.reports.build import build_report, format_summary, write_report
from services.edge.reports.movement import Params

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "tests" / "fixtures" / "contracts"
GROUP = "g-2026-10-13"


def schema(name: str) -> Draft202012Validator:
    doc = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(doc)


def example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.example.json").read_text(encoding="utf-8"))


def make_run(
    root: Path,
    frames: list[tuple],
    tracks: list[tuple],
    *,
    camera_id: str | None = "cam1",
    group_id: str | None = GROUP,
    events: list[dict] | None = None,
    status: str = "ended",
    detection: bool = True,
    finished: bool = True,
) -> Path:
    """Write a session folder with one run; returns the run folder.

    frames: (seq, t_recv, n_detections[, app_delay_ms]); tracks: (seq, track_id, x, y) with
    (x, y) the box's bottom-centre, so the expected positions are the numbers written here."""
    session_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
    folder = root / (f"{camera_id}_{session_id}" if camera_id else session_id)
    run_dir = folder / "runs" / run_id
    run_dir.mkdir(parents=True)
    session = copy.deepcopy(example("session"))
    session.update(
        session_id=session_id, camera_id=camera_id, group_id=group_id, status=status,
        runs=[run_id], events=events or [], ended_at=session["ended_at"] if finished else None,
    )  # fmt: skip
    run = copy.deepcopy(example("run"))
    run.update(run_id=run_id, session_id=session_id)
    if not detection:
        run.update(detector=None, tracker=None)
        run["runtime"].update(device=None, gpu=None)
    n = len(frames)
    run["counts"] = {"captured": n * 4, "processed": n, "dropped": n * 3, "unprocessed": 0,
                     "rec_dropped": None} if finished else None  # fmt: skip
    run["ended_at"] = "2026-10-13T12:02:00Z" if finished else None
    run["t0_wall"] = "2026-10-13T12:00:00Z"
    schema("session").validate(session)
    schema("run").validate(run)
    (folder / "session.json").write_text(json.dumps(session), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    with open(run_dir / "frames.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["seq", "t_recv", "t_proc_start", "t_proc_end", "app_delay_ms",
                    "n_detections", "n_tracks", "dropped_total"])  # fmt: skip
        for seq, t, ndet, *delay in frames:
            ms = delay[0] if delay else 110.0
            end = t + ms / 1000
            w.writerow([seq, t, end - 0.05, end, ms, ndet if detection else "",
                        0 if detection else "", 0])  # fmt: skip
    with open(run_dir / "tracks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["seq", "track_id", "x1", "y1", "x2", "y2", "confidence", "state", "athlete_id"])
        for seq, tid, x, y in tracks:
            w.writerow([seq, tid, x - 10, y - 100, x + 10, y, 0.9, "", ""])
    return run_dir


def dense(n: int, step: float = 0.5, ndet: int = 1) -> list[tuple]:
    """n processed frames, seq i at t = step * i, each with ndet detections."""
    return [(i, step * i, ndet) for i in range(n)]


def track_of(report, track_id: int) -> dict:
    return next(t for t in report.to_dict()["tracks"] if t["track_id"] == track_id)


def value(q: dict) -> float | None:
    return q["value"]


# -- per-track numbers --------------------------------------------------------------------------


def test_exact_path_length_speeds_and_activity(tmp_path):
    """A1: positions and times chosen so every number is known."""
    tracks = (
        [(i, 1, 100 * i, 500) for i in range(6)]  # 100 px per 0.5 s: 200 px/s, 5 intervals
        + [(i, 2, 640, 300) for i in range(4)]  # standing still
        + [(i, 6, x, 200) for i, x in enumerate([0, 10, 110, 410])]  # 20, 200, 600 px/s
    )
    report = build_report(make_run(tmp_path, dense(13), tracks))
    t1, t2, t6 = (track_of(report, i) for i in (1, 2, 6))
    assert (value(t1["first_seen"]), value(t1["last_seen"]), value(t1["visible"])) == (0, 2.5, 2.5)
    assert t1["n_samples"] == 6 and value(t1["median_sample_interval"]) == 0.5
    assert t1["n_valid_intervals"] == 5 and t1["n_gaps_excluded"] == 0
    assert value(t1["path_length"]) == pytest.approx(500)
    assert value(t1["valid_time"]) == pytest.approx(2.5)
    assert value(t1["mean_speed"]) == pytest.approx(200) and value(t1["max_speed"]) == 200
    assert t1["path_length"]["unit"] == "px" and t1["mean_speed"]["unit"] == "px/s"
    assert [value(t1["activity"][k]) for k in ("stationary", "walking", "running")] == [0, 100, 0]
    assert value(t2["path_length"]) == 0 and value(t2["mean_speed"]) == 0
    assert value(t2["activity"]["stationary"]) == 100
    assert value(t6["path_length"]) == pytest.approx(410)
    assert value(t6["max_speed"]) == pytest.approx(600)
    assert value(t6["mean_speed"]) == pytest.approx(410 / 1.5)
    shares = [value(t6["activity"][k]) for k in ("stationary", "walking", "running")]
    assert shares == pytest.approx([100 / 3] * 3)  # one interval of each, equal durations
    assert not t1["short"] and not t2["short"]  # 2.5 s and 1.5 s


def test_a_gap_longer_than_max_gap_is_excluded_and_counted(tmp_path):
    # samples at t = 0, .5, 1.0 | 3.0, 3.5, 4.0 : the jump of 800 px across 2 s is not a speed
    xs = {0: 0, 1: 100, 2: 200, 6: 1000, 7: 1100, 8: 1200}
    tracks = [(seq, 3, x, 400) for seq, x in xs.items()]
    run_dir = make_run(tmp_path, dense(13), tracks)
    t3 = track_of(build_report(run_dir), 3)
    assert t3["n_valid_intervals"] == 4 and t3["n_gaps_excluded"] == 1
    assert value(t3["gap_time"]) == pytest.approx(2.0)
    assert value(t3["path_length"]) == pytest.approx(400)  # not 1200
    assert value(t3["valid_time"]) == pytest.approx(2.0)
    assert value(t3["mean_speed"]) == pytest.approx(200) and value(t3["max_speed"]) == 200
    assert value(t3["visible"]) == 4.0  # first to last sample, gap included
    # a larger --max-gap takes the jump in as a (fast) interval
    wide = track_of(build_report(run_dir, params=Params(max_gap=3.0)), 3)
    assert wide["n_gaps_excluded"] == 0 and wide["n_valid_intervals"] == 5
    assert value(wide["max_speed"]) == pytest.approx(400)  # 800 px / 2 s, after smoothing


def test_a_single_sample_has_null_speed_with_a_reason(tmp_path):
    report = build_report(make_run(tmp_path, dense(5), [(2, 4, 300, 300)]))
    t = track_of(report, 4)
    assert t["n_samples"] == 1 and value(t["visible"]) == 0 and t["short"]
    for key in ("path_length", "mean_speed", "max_speed", "median_sample_interval"):
        assert t[key]["value"] is None and t[key]["reason"] == ("single sample"), key
    assert all(t["activity"][k]["value"] is None for k in t["activity"])
    assert "single sample" in format_summary(report)


def test_one_valid_interval_gives_a_path_but_no_speed(tmp_path):
    report = build_report(make_run(tmp_path, dense(5), [(0, 5, 0, 100), (1, 5, 30, 140)]))
    t = track_of(report, 5)
    assert value(t["path_length"]) == pytest.approx(50)  # 3-4-5
    assert t["mean_speed"]["value"] is None
    assert t["mean_speed"]["reason"] == "1 valid interval(s), fewer than 2"
    # one interval is not a share: no activity either, with the same reason
    assert t["activity"]["walking"]["value"] is None
    assert t["activity"]["walking"]["reason"] == t["mean_speed"]["reason"]


def test_all_gaps_means_no_numbers_not_zeros(tmp_path):
    report = build_report(make_run(tmp_path, dense(10), [(0, 7, 0, 0), (4, 7, 500, 0)]))
    t = track_of(report, 7)
    assert t["n_gaps_excluded"] == 1 and t["n_valid_intervals"] == 0
    assert t["path_length"]["value"] is None
    assert "within 1 s" in t["path_length"]["reason"]


def test_median_smoothing_removes_a_spike_and_can_be_switched_off(tmp_path):
    xs = [0, 100, 5000, 300, 400]  # the 5000 is a glitch
    tracks = [(i, 8, x, 100) for i, x in enumerate(xs)]
    run_dir = make_run(tmp_path, dense(6), tracks)
    smoothed = track_of(build_report(run_dir), 8)
    assert value(smoothed["path_length"]) == pytest.approx(400)  # 0,100,300,400,400
    raw = track_of(build_report(run_dir, params=Params(smooth_window=1)), 8)
    assert value(raw["path_length"]) == pytest.approx(100 + 4900 + 4700 + 100)


def test_two_sample_runs_are_not_flattened(tmp_path):
    """The window shrinks at the ends of a run: two samples keep their motion."""
    run_dir = make_run(tmp_path, dense(5), [(0, 9, 0, 0), (1, 9, 100, 0)])
    assert value(track_of(build_report(run_dir), 9)["path_length"]) == pytest.approx(100)


def test_position_is_the_box_bottom_centre(tmp_path):
    run_dir = make_run(tmp_path, dense(4), [(i, 1, 50 + 100 * i, 300 + 40 * i) for i in range(3)])
    assert value(track_of(build_report(run_dir), 1)["path_length"]) == pytest.approx(
        2 * np.hypot(100, 40)
    )


@dataclass(frozen=True)
class Metres:
    """A calibration stand-in: 1 px = 1 cm. The report code must not need to change."""

    unit: str = "m"
    calibrated: bool = True
    stationary_below: float = 0.4
    walking_below: float = 4.0

    def __call__(self, x, y):
        return x / 100, y / 100


def test_positions_go_through_the_position_function(tmp_path):
    run_dir = make_run(tmp_path, dense(8), [(i, 1, 100 * i, 500) for i in range(6)])
    report = build_report(run_dir, positions=Metres())
    d = report.to_dict()
    assert d["positions"] == {"unit": "m", "point": "bottom_centre", "calibrated": True}
    t = track_of(report, 1)
    assert t["path_length"] == {"value": pytest.approx(5.0), "unit": "m"}
    assert t["mean_speed"] == {"value": pytest.approx(2.0), "unit": "m/s"}
    assert value(t["activity"]["walking"]) == 100  # 2 m/s is between 0.4 and 4.0 m/s
    assert d["params"]["walking_below"] == {"value": 4.0, "unit": "m/s"}
    assert not any("uncalibrated pixels" in c for c in d["caveats"][:1])
    schema("report").validate(d)


def test_activity_thresholds_are_configurable(tmp_path):
    run_dir = make_run(tmp_path, dense(8), [(i, 1, 100 * i, 500) for i in range(6)])  # 200 px/s
    run_ = track_of(build_report(run_dir, params=Params(walking_below=150.0)), 1)
    assert value(run_["activity"]["running"]) == 100
    still = track_of(build_report(run_dir, params=Params(stationary_below=250.0)), 1)
    assert value(still["activity"]["stationary"]) == 100


# -- session level -----------------------------------------------------------------------------


def test_session_numbers(tmp_path):
    delays = [100.0, 200.0, 300.0, 400.0, 1000.0]
    frames = [(i, 1.0 * i, 2 if i < 3 else 0, delays[i]) for i in range(5)]
    events = [
        {"t_wall": "2026-10-13T12:00:10Z", "t_mono": 10.0, "kind": "source_lost", "detail": "x"},
        {"t_wall": "2026-10-13T11:59:59Z", "t_mono": None, "kind": "source_open_failed",
         "detail": None},
    ]  # fmt: skip
    tracks = [(0, 1, 0, 0), (1, 1, 1, 0), (2, 1, 2, 0), (0, 2, 5, 5)]
    d = build_report(make_run(tmp_path, frames, tracks, events=events)).to_dict()
    s = d["session"]
    assert d["camera_id"] == "cam1" and d["group_id"] == GROUP
    assert s["status"] == "ended" and s["detection"] is True
    assert s["duration"] == {"value": 120.0, "unit": "s"}  # t0_wall to ended_at
    assert (s["n_captured"], s["n_processed"], s["n_dropped"], s["n_unprocessed"]) == (20, 5, 15, 0)
    assert s["drop_rate"] == {"value": 75.0, "unit": "percent"}
    assert s["coverage"] == {"value": 60.0, "unit": "percent"}  # 3 of 5 frames
    first_start = 0.0 + 0.1 - 0.05
    last_end = 4.0 + 1.0
    assert s["processed_fps"]["value"] == pytest.approx(5 / (last_end - first_start))
    assert s["processed_fps"]["unit"] == "frames/s"
    p50, p95 = np.percentile(delays, [50, 95])
    assert s["app_delay_p50"] == {"value": pytest.approx(p50), "unit": "ms"}
    assert s["app_delay_p95"] == {"value": pytest.approx(p95), "unit": "ms"}
    assert s["app_delay_max"]["value"] == 1000.0
    assert s["frame_interval_median"]["value"] == 1.0 == s["frame_interval_max"]["value"]
    assert s["n_tracks"] == 2 and s["n_short_tracks"] == 1  # 2 s is not short; a single sample is
    assert [e["kind"] for e in s["events"]] == ["source_lost", "source_open_failed"]
    assert s["events"][0]["t_since_t0"] == {"value": 10.0, "unit": "s"}
    assert s["events"][1]["t_since_t0"] == {  # before t0
        "value": None, "unit": "s", "reason": "event precedes t0",
    }  # fmt: skip
    schema("report").validate(d)


def test_zero_detections_is_zero_coverage_not_a_crash(tmp_path):
    report = build_report(make_run(tmp_path, dense(6, ndet=0), []))
    d = report.to_dict()
    assert d["session"]["coverage"] == {"value": 0.0, "unit": "percent"}
    assert d["session"]["n_tracks"] == 0 and d["tracks"] == []
    schema("report").validate(d)
    assert "tracks 0" in format_summary(report)


def test_no_frames_at_all(tmp_path):
    d = build_report(make_run(tmp_path, [], [])).to_dict()
    s = d["session"]
    assert s["n_processed"] == 0
    for key in ("coverage", "processed_fps", "app_delay_p50", "frame_interval_max"):
        assert s[key]["value"] is None and s[key]["reason"], key
    schema("report").validate(d)


def test_detection_off_has_no_coverage(tmp_path):
    d = build_report(make_run(tmp_path, dense(5), [], detection=False)).to_dict()
    assert d["session"]["detection"] is False
    assert d["session"]["coverage"] == {"value": None, "unit": "percent",
                                        "reason": "detection was off"}  # fmt: skip
    schema("report").validate(d)


def test_a_run_that_did_not_end_still_reports(tmp_path):
    run_dir = make_run(
        tmp_path, dense(5), [(0, 1, 0, 0), (1, 1, 5, 0)], status="running", finished=False
    )
    d = build_report(run_dir).to_dict()
    s = d["session"]
    assert s["status"] == "running" and s["n_captured"] is None and s["n_dropped"] is None
    assert s["drop_rate"]["value"] is None and "did not end" in s["drop_rate"]["reason"]
    assert s["duration"]["value"] == pytest.approx(2.11)  # the last processed frame's end
    assert any("did not end" in c for c in d["caveats"])
    schema("report").validate(d)


def test_caveats_say_what_is_uncalibrated_and_unvalidated(tmp_path):
    d = build_report(make_run(tmp_path, dense(5), [(0, 1, 0, 0)])).to_dict()
    text = " ".join(d["caveats"])
    assert "uncalibrated pixels" in text and "not metres" in text
    assert "placeholders" in text and "not validated against ground truth" in text
    assert "Low processing rate" in text  # 5 frames over 2 s is below 5 fps


def test_detections_without_tracks_are_explained(tmp_path):
    d = build_report(make_run(tmp_path, dense(5), [])).to_dict()
    assert any("no track formed" in c for c in d["caveats"])


def test_track_rows_without_a_frame_are_skipped_and_said(tmp_path):
    d = build_report(make_run(tmp_path, dense(3), [(0, 1, 0, 0), (99, 1, 5, 0)])).to_dict()
    assert d["tracks"][0]["n_samples"] == 1
    assert any("no matching processed frame" in c for c in d["caveats"])


def test_summary_text_shows_the_tracks_and_the_caveats(tmp_path):
    tracks = [(i, 1, 100 * i, 500) for i in range(6)]
    text = format_summary(build_report(make_run(tmp_path, dense(8), tracks)))
    assert text.startswith("report cam1 ")
    assert "positions in px, uncalibrated" in text
    assert "200.0" in text and "0/100/0" in text  # mean speed, activity share
    assert "caveats:" in text and "tracks 1, 0 shorter than 1 s" in text


# -- files, schema, CLI ----------------------------------------------------------------------


def test_write_report_replaces_report_json_and_matches_the_schema(tmp_path):
    run_dir = make_run(tmp_path, dense(8), [(i, 1, 100 * i, 500) for i in range(6)])
    write_report(run_dir)
    first = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    schema("report").validate(first)
    assert first["contract_version"] == "0.7.0"
    write_report(run_dir, params=Params(max_gap=0.2))  # every interval is a gap
    second = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert (
        second["tracks"][0]["n_gaps_excluded"] == 5 and first["tracks"][0]["n_gaps_excluded"] == 0
    )
    assert not list(run_dir.glob("*.tmp"))


def test_the_report_needs_no_live_state_and_never_writes_outside_report_json(tmp_path):
    run_dir = make_run(tmp_path, dense(8), [(i, 1, 100 * i, 500) for i in range(6)])
    before = {p: p.read_bytes() for p in run_dir.parent.parent.rglob("*") if p.is_file()}
    write_report(run_dir)
    after = {p: p.read_bytes() for p in run_dir.parent.parent.rglob("*") if p.is_file()}
    assert set(after) - set(before) == {run_dir / "report.json"}
    assert all(after[p] == b for p, b in before.items())  # the session's own files untouched


def test_cli_single_session(tmp_path, capsys):
    run_dir = make_run(tmp_path, dense(8), [(i, 1, 100 * i, 500) for i in range(6)])
    session_dir = run_dir.parent.parent
    assert cli.main([str(session_dir)]) == 0
    out = capsys.readouterr().out
    assert "report cam1" in out and (run_dir / "report.json").exists()
    assert cli.main([str(session_dir), "--run", run_dir.name, "--max-gap", "0.2"]) == 0
    assert json.loads((run_dir / "report.json").read_text())["params"]["max_gap"]["value"] == 0.2


def test_cli_errors_exit_2_without_a_traceback(tmp_path, capsys):
    assert cli.main([str(tmp_path / "missing")]) == 2
    assert "cannot report" in capsys.readouterr().err
    run_dir = make_run(tmp_path, dense(3), [])
    assert cli.main([str(run_dir.parent.parent), "--run", "nope"]) == 2
    with pytest.raises(SystemExit):
        cli.main([])  # neither a session nor --group
    with pytest.raises(SystemExit):
        cli.main([str(tmp_path), "--group", "g"])
    with pytest.raises(SystemExit):
        cli.main(["--group", "g", "--run", "x"])
    with pytest.raises(SystemExit):
        cli.main([str(tmp_path), "--max-gap", "0"])
    with pytest.raises(SystemExit):
        cli.main([str(tmp_path), "--smooth", "4"])


def test_group_mode_prints_one_section_per_camera_and_fuses_nothing(tmp_path, capsys):
    laptop = make_run(tmp_path, dense(10), [(i, 1, 100 * i, 500) for i in range(6)],
                      camera_id="laptop")  # fmt: skip
    phone = make_run(tmp_path, dense(4, step=2.0), [(0, 1, 0, 0)], camera_id="phone1")
    other = make_run(tmp_path, dense(4), [], camera_id="cam9", group_id="another-group")
    assert cli.main(["--group", GROUP, "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2 camera(s)" in out
    assert out.index("report laptop") < out.index("report phone1")  # by camera_id
    assert "cam9" not in out
    for run_dir, camera in ((laptop, "laptop"), (phone, "phone1")):
        d = json.loads((run_dir / "report.json").read_text())
        schema("report").validate(d)
        assert d["camera_id"] == camera and d["group_id"] == GROUP
    assert d["session"]["n_processed"] == 4  # the phone's own numbers, not laptop + phone
    assert not (other / "report.json").exists()
    assert cli.main(["--group", "none", "--out", str(tmp_path)]) == 2
    assert "no session with group_id none" in capsys.readouterr().err


def test_module_entry_point_runs(tmp_path):
    import subprocess
    import sys

    run_dir = make_run(tmp_path, dense(4), [])
    done = subprocess.run(
        [sys.executable, "-m", "services.edge.report", str(run_dir.parent.parent)],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert "report cam1" in done.stdout


def test_report_example_validates_and_matches_a_built_report(tmp_path):
    ex = example("report")
    schema("report").validate(ex)
    run_dir = make_run(tmp_path, dense(8), [(i, 1, 100 * i, 500) for i in range(6)])
    built = build_report(run_dir).to_dict()
    assert set(ex) == set(built)
    assert set(ex["session"]) == set(built["session"])
    assert set(ex["tracks"][0]) == set(built["tracks"][0])
    assert set(ex["params"]) == set(built["params"])


# -- robustness and CLI guards (gate fixes) ------------------------------------------------------


def test_malformed_csv_rows_are_skipped_and_said(tmp_path):
    run_dir = make_run(tmp_path, dense(6), [(i, 1, 100 * i, 500) for i in range(4)])
    with open(run_dir / "tracks.csv", "a", encoding="utf-8") as f:
        f.write("4,1,1\n")  # a truncated last line
    with open(run_dir / "frames.csv", "a", encoding="utf-8") as f:
        f.write("99,1.0\n")
    d = build_report(run_dir).to_dict()
    assert d["tracks"][0]["n_samples"] == 4 and d["session"]["n_processed"] == 6
    assert any("2 malformed CSV row(s)" in c for c in d["caveats"])
    schema("report").validate(d)


def test_the_same_track_twice_in_one_frame_is_one_sample(tmp_path):
    rows = [(0, 1, 0, 0), (1, 1, 100, 0), (1, 1, 100, 0), (2, 1, 200, 0)]
    t = track_of(build_report(make_run(tmp_path, dense(4), rows)), 1)
    assert t["n_samples"] == 3 and t["n_gaps_excluded"] == 0


def test_one_processed_frame_has_no_rate_and_no_interval(tmp_path):
    s = build_report(make_run(tmp_path, dense(1), [])).to_dict()["session"]
    for key in ("processed_fps", "frame_interval_median", "frame_interval_max"):
        assert s[key]["value"] is None and "fewer than 2" in s[key]["reason"], key


def test_a_run_that_captured_nothing_does_not_say_it_did_not_end(tmp_path):
    run_dir = make_run(tmp_path, [], [])
    run = json.loads((run_dir / "run.json").read_text())
    run["counts"] = {"captured": 0, "processed": 0, "dropped": 0, "unprocessed": 0,
                     "rec_dropped": None}  # fmt: skip
    (run_dir / "run.json").write_text(json.dumps(run))
    reason = build_report(run_dir).to_dict()["session"]["drop_rate"]["reason"]
    assert reason == "no frames captured"


def test_the_console_summary_lists_the_longest_tracks_only(tmp_path):
    from services.edge.reports.build import MAX_TRACK_ROWS

    n = MAX_TRACK_ROWS + 5
    tracks = [(0, i, 0, 0) for i in range(n)] + [(1, 0, 50, 0)]  # track 0 is the only visible one
    report = build_report(make_run(tmp_path, dense(3), tracks))
    text = format_summary(report)
    assert f"... {n - MAX_TRACK_ROWS} shorter track(s) not shown" in text
    assert len(report.to_dict()["tracks"]) == n  # report.json keeps every track


def test_a_run_id_outside_the_session_is_refused(tmp_path, capsys):
    run_dir = make_run(tmp_path, dense(3), [])
    other = make_run(tmp_path, dense(3), [], camera_id="cam2")
    session_dir = run_dir.parent.parent
    outside = f"../../../{other.parent.parent.name}/runs/{other.name}"
    assert cli.main([str(session_dir), "--run", outside]) == 2
    assert "is not in" in capsys.readouterr().err
    assert not (other / "report.json").exists()


def test_group_mode_goes_on_after_a_broken_session(tmp_path, capsys):
    good = make_run(tmp_path, dense(4), [], camera_id="b_good")
    bad = make_run(tmp_path, dense(4), [], camera_id="a_bad")
    (bad / "frames.csv").unlink()
    assert cli.main(["--group", GROUP, "--out", str(tmp_path)]) == 2  # one camera failed
    captured = capsys.readouterr()
    assert "a_bad" in captured.err and "report b_good" in captured.out
    assert (good / "report.json").exists()


@pytest.mark.parametrize(
    "args",
    [["--walking-below", "30"], ["--stationary-below", "500"],
     ["--stationary-below", "100", "--walking-below", "100"], ["--min-intervals", "0"]],
)  # fmt: skip
def test_nonsense_thresholds_are_refused(tmp_path, args):
    with pytest.raises(SystemExit):
        cli.main([str(tmp_path), *args])


def test_a_report_interrupted_by_ctrl_c_keeps_the_session_exit_code(monkeypatch, capsys):
    from services.edge import main as app

    def interrupted(run_dir):
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "write_report", interrupted)
    app.print_report("x")  # must not raise
    assert "report interrupted" in capsys.readouterr().err
