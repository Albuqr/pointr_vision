"""FR-013 / AC-013.1: the scoring tool reads labels.csv and a run's logs and prints H1, H3, H3b
and H4 next to their thresholds. Fixtures are built here with results worked out by hand (R1-A3).

Times: frames run at 10 fps, so frame seq n is at t_video n / 10."""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from services.edge import score
from services.edge.contract import LABELS_COLUMNS, SHOTS_COLUMNS
from services.edge.session.writer import FRAMES_COLUMNS, TRACKS_COLUMNS

ROOT = Path(__file__).resolve().parents[2]
RUN = "11111111-1111-4111-8111-111111111111"


def write_csv(path: Path, columns, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, columns, restval="")
        w.writeheader()
        w.writerows(rows)


def make_session(
    tmp_path: Path, labels=(), shots=None, tracks=None, n_frames=5000, t_video=True, offset=0.0,
    blank=(),
) -> Path:  # fmt: skip
    """offset: t_video of frame 0, so the join cannot be faked with seq / 10. blank: seqs of frames
    the recorder dropped (empty t_video)."""
    folder = tmp_path / "session"
    run_dir = folder / "runs" / RUN
    run_dir.mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({"runs": [RUN]}))
    write_csv(
        run_dir / "frames.csv",
        FRAMES_COLUMNS,
        [
            {"seq": n, "t_video": f"{n / 10 + offset:.3f}" if t_video and n not in blank else ""}
            for n in range(n_frames)
        ],
    )
    write_csv(
        folder / "labels.csv",
        LABELS_COLUMNS,
        [dict(zip(LABELS_COLUMNS, row, strict=False)) for row in labels],
    )
    if shots is not None:
        write_csv(
            run_dir / "shots.csv",
            SHOTS_COLUMNS,
            [{"shot_id": i + 1, "seq": round((t - offset) * 10), "call": call, "call_source": src}
             for i, (t, call, src) in enumerate(shots)],
        )  # fmt: skip
    if tracks is not None:
        write_csv(
            run_dir / "tracks.csv",
            TRACKS_COLUMNS,
            [{"seq": round((t - offset) * 10), "track_id": tid, "player_number": num}
             for t, tid, num in tracks],
        )  # fmt: skip
    return folder


# -- labels.csv --------------------------------------------------------------------------------


def test_reads_labels(tmp_path):
    folder = make_session(tmp_path, [(10.2, "attempt", 23, ""), (10.9, "make", "", "swish")])
    labels = score.load_labels(folder / "labels.csv")
    assert [(lab.time_s, lab.event, lab.player_number) for lab in labels] == [
        (10.2, "attempt", 23),
        (10.9, "make", None),
    ]


@pytest.mark.parametrize(
    "row,why",
    [
        ((1.0, "dunk", ""), "event"),
        (("soon", "attempt", ""), "time_s"),
        ((1.0, "attempt", "x"), "player_number"),
        ((-1.0, "attempt", ""), "time_s"),
    ],
)
def test_bad_label_rows_are_refused_with_the_line(tmp_path, row, why):
    folder = make_session(tmp_path, [(5.0, "attempt", ""), row])
    with pytest.raises(score.ScoreError, match=rf"labels.csv line 3.*{why}"):
        score.load_labels(folder / "labels.csv")


def test_labels_need_the_contract_columns(tmp_path):
    folder = make_session(tmp_path)
    (folder / "labels.csv").write_text("time,event\n1,attempt\n")
    with pytest.raises(score.ScoreError, match="columns"):
        score.load_labels(folder / "labels.csv")


# -- H1: worked by hand ------------------------------------------------------------------------

H1_LABELS = [
    (10.0, "attempt", ""), (10.8, "make", ""),
    (20.0, "attempt", ""), (20.8, "miss", ""),
    (30.0, "attempt", ""), (30.8, "make", ""),
    (40.0, "attempt", ""), (40.8, "make", ""),
    (50.0, "attempt", ""), (50.8, "miss", ""),
]  # fmt: skip
H1_SHOTS = [
    (10.2, "make", "video"),  # found, right
    (20.5, "miss", "video"),  # found, right
    (30.0, "miss", "video"),  # found, called wrong (label: make)
    (40.0, "uncertain", "video"),  # found, uncertain: counts wrong
    # nothing near t=50: that attempt is missed
    (70.0, "make", "video"),  # no attempt label: a false attempt
]


def test_h1_matches_the_hand_calculation(tmp_path):
    folder = make_session(tmp_path, H1_LABELS, shots=H1_SHOTS)
    h1 = score.score_h1(folder, RUN)
    # 5 attempts, 4 found (80%); of those 4, 2 called right (50%), 1 uncertain; 1 false attempt
    assert (h1.attempts, h1.found, h1.scored, h1.right) == (5, 4, 4, 2)
    assert (h1.uncertain, h1.false_attempts, h1.no_outcome) == (1, 1, 0)
    assert h1.found_rate == pytest.approx(0.8) and h1.right_rate == pytest.approx(0.5)
    assert h1.verdict == "stop vision-only"  # the worse rate, 50%, is under 70%
    assert h1.source == "video"


def test_h1_passes_at_both_thresholds(tmp_path):
    labels = [(10.0 * i, "attempt", "") for i in range(1, 11)]
    labels += [(10.0 * i + 0.8, "make", "") for i in range(1, 11)]
    shots = [(10.0 * i, "make", "video") for i in range(1, 11)]
    h1 = score.score_h1(make_session(tmp_path, labels, shots=shots), RUN)
    assert (h1.found, h1.right, h1.verdict) == (10, 10, "continue")


def test_h1_between_70_and_85_says_add_the_sensor(tmp_path):
    labels = [(10.0 * i, "attempt", "") for i in range(1, 11)]
    labels += [(10.0 * i + 0.8, "make", "") for i in range(1, 11)]
    shots = [(10.0 * i, "make", "video") for i in range(1, 9)]  # 8 of 10 found, all right
    h1 = score.score_h1(make_session(tmp_path, labels, shots=shots), RUN)
    assert h1.found_rate == pytest.approx(0.8) and h1.verdict == "add the rim sensor"


def test_tolerance_is_inclusive_and_matching_is_one_to_one(tmp_path):
    labels = [(10.0, "attempt", ""), (10.5, "make", "")]
    shots = [(11.0, "make", "video"), (11.0, "make", "video")]  # both exactly 1.0 s away
    folder = make_session(tmp_path, labels, shots=shots)
    h1 = score.score_h1(folder, RUN, tolerance=1.0)
    assert (h1.found, h1.false_attempts) == (1, 1)
    h1 = score.score_h1(folder, RUN, tolerance=0.9)
    assert (h1.found, h1.false_attempts) == (0, 2)


def test_attempt_without_an_outcome_label_is_not_scored_for_the_call(tmp_path):
    labels = [(10.0, "attempt", ""), (20.0, "attempt", ""), (20.8, "make", "")]
    shots = [(10.0, "make", "video"), (20.0, "make", "video")]
    h1 = score.score_h1(make_session(tmp_path, labels, shots=shots), RUN)
    assert (h1.found, h1.scored, h1.right, h1.no_outcome) == (2, 1, 1, 1)


def test_sensor_calls_are_reported_as_video_plus_sensor(tmp_path):
    labels = [(10.0, "attempt", ""), (10.8, "make", "")]
    shots = [(10.0, "make", "video+sensor")]
    assert score.score_h1(make_session(tmp_path, labels, shots=shots), RUN).source == "video+sensor"


def test_h1_without_shots_is_not_scorable(tmp_path):
    folder = make_session(tmp_path, H1_LABELS)
    assert score.score_h1(folder, RUN) is None


def test_labels_cannot_join_without_t_video(tmp_path):
    folder = make_session(tmp_path, H1_LABELS, shots=H1_SHOTS, t_video=False)
    with pytest.raises(score.ScoreError, match="t_video"):
        score.score_h1(folder, RUN)


# -- H3b: worked by hand -----------------------------------------------------------------------

H3B_LABELS = [
    (100.0, "leave", 7), (130.0, "return", 7),  # the number is back on the same track: kept
    (100.0, "leave", 8), (140.0, "return", 8),  # never on a track after the return: lost
    (200.0, "leave", 9), (230.0, "return", 9),  # never numbered before leaving: not assessable
    (300.0, "leave", 10), (330.0, "return", 10),  # seen again only after the window: lost
    (400.0, "leave", 11), (430.0, "return", 11),  # back on a NEW track, same number: kept
]  # fmt: skip
H3B_TRACKS = [
    (98.0, 3, 7), (99.9, 3, 7), (130.5, 3, 7),
    (99.0, 4, 8),
    (299.0, 5, 10), (340.0, 5, 10),
    (399.0, 6, 11), (430.5, 12, 11),
]  # fmt: skip


def test_h3b_matches_the_hand_calculation(tmp_path):
    folder = make_session(tmp_path, H3B_LABELS, tracks=H3B_TRACKS)
    h3b = score.score_h3b(folder, RUN)
    # 5 returns; 4 assessable (7, 8, 10, 11); 2 kept (7, and 11 on a new track)
    assert (h3b.returns, h3b.assessed, h3b.kept, h3b.not_assessable) == (5, 4, 2, 1)
    assert h3b.rate == pytest.approx(0.5)
    assert not h3b.passed


def test_h3b_reads_the_number_not_the_temporary_track_id(tmp_path):
    """After a long absence the tracker gives a new id; a correct identity layer still returns 7."""
    labels = [(100.0, "leave", 7), (130.0, "return", 7)]
    folder = make_session(tmp_path, labels, tracks=[(99.0, 3, 7), (130.5, 41, 7)])
    h3b = score.score_h3b(folder, RUN)
    assert (h3b.assessed, h3b.kept) == (1, 1)


def test_h3b_joins_through_t_video_not_seq(tmp_path):
    folder = make_session(tmp_path, H3B_LABELS, tracks=H3B_TRACKS, offset=5.0)
    h3b = score.score_h3b(folder, RUN)
    assert (h3b.assessed, h3b.kept) == (4, 2)


def test_h3b_without_player_numbers_is_not_scorable(tmp_path):
    folder = make_session(tmp_path, H3B_LABELS, tracks=[(98.0, 3, ""), (130.5, 3, "")])
    assert score.score_h3b(folder, RUN) is None


def test_h3b_with_no_return_labels_is_not_scorable(tmp_path):
    folder = make_session(tmp_path, H1_LABELS, tracks=H3B_TRACKS)
    assert score.score_h3b(folder, RUN) is None


# -- the report --------------------------------------------------------------------------------


def test_AC_013_1_report_prints_every_hypothesis_beside_its_threshold(tmp_path):
    folder = make_session(tmp_path, [*H1_LABELS, *H3B_LABELS], shots=H1_SHOTS, tracks=H3B_TRACKS)
    result = subprocess.run(
        [sys.executable, "-m", "services.edge.score", str(folder)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    lines = {line.split()[0]: line for line in result.stdout.splitlines() if line.startswith("H")}
    assert set(lines) >= {"H1", "H3", "H3b", "H4"}
    assert "4/5" in lines["H1"] and "80.0%" in lines["H1"] and ">= 85%" in lines["H1"]
    assert "2/4" in lines["H1"] and ">= 90%" in lines["H1"]
    assert "2/4" in lines["H3b"] and ">= 80%" in lines["H3b"] and "FAIL" in lines["H3b"]
    assert "not scorable" in lines["H3"] and ">= 80%" in lines["H3"]
    assert "not scorable" in lines["H4"] and "0.5 m" in lines["H4"]
    assert "fewer than 30" in result.stdout  # 5 attempts: not decisive


def test_missing_labels_is_an_error_not_a_traceback(tmp_path):
    folder = make_session(tmp_path)
    (folder / "labels.csv").unlink()
    result = subprocess.run(
        [sys.executable, "-m", "services.edge.score", str(folder)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "labels.csv" in result.stderr and "Traceback" not in result.stderr


def test_h1_joins_through_t_video_not_seq(tmp_path):
    """Frame 0 is at 5.0 s of the video, so a shot's time is not seq / 10."""
    folder = make_session(tmp_path, H1_LABELS, shots=H1_SHOTS, offset=5.0)
    h1 = score.score_h1(folder, RUN)
    assert (h1.attempts, h1.found, h1.right, h1.false_attempts) == (5, 4, 2, 1)


def test_shot_on_a_frame_the_recorder_dropped_is_unplaced_not_an_error(tmp_path):
    blank = {102}  # the frame of the 10.2 s shot has no video time
    folder = make_session(tmp_path, H1_LABELS, shots=H1_SHOTS, blank=blank)
    h1 = score.score_h1(folder, RUN)
    assert h1.unplaced == 1
    assert (h1.found, h1.false_attempts) == (3, 1)  # it is neither matched nor a false attempt


def test_labels_saved_by_excel_with_a_bom_are_read(tmp_path):
    folder = make_session(tmp_path)
    (folder / "labels.csv").write_bytes(
        b"\xef\xbb\xbftime_s,event,player_number,note\r\n10.2,attempt,23,\r\n"
    )
    assert [lab.event for lab in score.load_labels(folder / "labels.csv")] == ["attempt"]


def counted_session(tmp_path, n=10, found=10, right=10):
    labels = [(10.0 * i, "attempt", "") for i in range(1, n + 1)]
    labels += [(10.0 * i + 0.8, "make", "") for i in range(1, n + 1)]
    shots = [(10.0 * i, "make" if i <= right else "miss", "video") for i in range(1, found + 1)]
    return make_session(tmp_path, labels, shots=shots)


@pytest.mark.parametrize(
    "found,right,verdict",
    [
        (17, 17, "continue"),  # 17 of 20 = 85% found, all right: both thresholds met exactly
        (16, 16, "add the rim sensor"),  # 80% found
        (10, 9, "continue"),  # 10 of 10 found, 9 right = 90%: the threshold is inclusive
        (10, 8, "add the rim sensor"),  # 80% right
        (14, 14, "add the rim sensor"),  # 14 of 20 = 70%: the floor is inclusive
        (13, 13, "stop vision-only"),  # 65%
    ],
)
def test_h1_thresholds_are_inclusive(tmp_path, found, right, verdict):
    n = 20 if found > 10 else 10
    h1 = score.score_h1(counted_session(tmp_path, n=n, found=found, right=right), RUN)
    assert h1.verdict == verdict


def run_report(folder: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "services.edge.score", str(folder), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_report_marks_pass_and_fail(tmp_path):
    out = run_report(counted_session(tmp_path))
    assert "| PASS: continue" in next(line for line in out.splitlines() if line.startswith("H1"))
    out = run_report(counted_session(tmp_path / "b", found=5, right=5))
    assert "| FAIL: stop vision-only" in next(
        line for line in out.splitlines() if line.startswith("H1")
    )


def test_tolerance_option_changes_the_match(tmp_path):
    labels = [(10.0, "attempt", ""), (10.5, "make", "")]
    folder = make_session(tmp_path, labels, shots=[(10.6, "make", "video")])
    assert "within 1 s" in run_report(folder)
    assert "attempts found 1/1" in run_report(folder)
    assert "attempts found 0/1" in run_report(folder, "--tolerance", "0.5")


def add_run(folder: Path, shots) -> str:
    """A second run (a replay) with its own shots, appended to session.json."""
    second = "22222222-2222-4222-8222-222222222222"
    run_dir = folder / "runs" / second
    run_dir.mkdir()
    (run_dir / "frames.csv").write_bytes((folder / "runs" / RUN / "frames.csv").read_bytes())
    write_csv(
        run_dir / "shots.csv",
        SHOTS_COLUMNS,
        [{"shot_id": 1, "seq": round(t * 10), "call": c, "call_source": "video"} for t, c in shots],
    )
    (folder / "session.json").write_text(json.dumps({"runs": [RUN, second]}))
    return second


def test_the_latest_run_is_scored_by_default_and_a_run_can_be_chosen(tmp_path):
    labels = [(10.0, "attempt", ""), (10.8, "make", "")]
    folder = make_session(tmp_path, labels, shots=[(10.0, "miss", "video")])
    add_run(folder, [(10.0, "make")])
    assert score.score_h1(folder).right == 1  # the second run: called make
    assert score.score_h1(folder, RUN).right == 0  # the first: called miss
    with pytest.raises(score.ScoreError, match="no run"):
        score.score_h1(folder, "00000000-0000-4000-8000-000000000000")


def test_report_warns_when_the_run_ends_before_the_labels(tmp_path):
    """A partial run (an interrupted replay) must not pass for a complete one."""
    folder = make_session(tmp_path, H1_LABELS, shots=H1_SHOTS, n_frames=250)  # frames end at 25 s
    out = run_report(folder)
    assert "note: labels run to 50.8 s but the run's frames end at 24.9 s" in out
    assert "note: labels run to" not in run_report(make_session(tmp_path / "b", H1_LABELS))
