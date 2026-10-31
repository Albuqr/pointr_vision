"""Group replay (R2a 08, D-060): replaying a recorded group adds one run to every camera's session,
processing the videos together in the live run's group time, and gives the live run's shared IDs on
the same frames. In-process with synthetic calibrated clips and a scripted fake detector; the
command line by subprocess with --no-detect. No camera, weights or network."""

import csv
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import FileSource
from services.edge.group_runner import GroupCamera, run_group
from services.edge.matcher import CourtMatcher, MatcherParams
from services.edge.perception.loop import NO_DETECTIONS
from services.edge.perception.types import Detections
from services.edge.replay.group import live_matcher, resolve_group
from services.edge.replay.resolve import ReplayError
from services.edge.run.args import parse_args
from services.edge.run.meta import RunSettings, run_meta
from tests.edge.fakes import OneTrackPerDetection
from tests.edge.test_group_runner import calibration_for
from tests.edge.test_session import load, rows, validate

ROOT = Path(__file__).resolve().parents[2]
ARGS = parse_args(["--source", "unused"])  # the CLI's defaults
SETTINGS = RunSettings(None, None)
CONFIG = HealthConfig()
# two people far apart: neither camera links, so which ID each gets depends on who came first
FAR = {"cam1": [10.0, 20.0, 110.0, 220.0], "cam2": [400.0, 200.0, 500.0, 340.0]}
NEAR = {"cam1": [10.0, 20.0, 110.0, 220.0], "cam2": [12.0, 20.0, 112.0, 220.0]}  # one person
STILL = MatcherParams(max_offset_s=5.0, max_speed_mps=0.0)
FPS = 15.0  # the clips' rate, so the recorder's


class Scripted:
    """One person per camera at a chosen box, from a chosen frame on and not in the `gone` frames.
    The camera is read from the source: the clip live, the session folder (`cam1_...`) on a
    replay."""

    threshold, det_size, device = 0.5, 384, "cpu"

    def __init__(self, boxes, start=None, gone=None):
        self.boxes, self.start, self.gone = boxes, start or {}, gone or {}

    def detect(self, frame):
        cid = "cam1" if "moving" in frame.source_id or "cam1_" in frame.source_id else "cam2"
        if frame.seq < self.start.get(cid, 0) or frame.seq in self.gone.get(cid, ()):
            return NO_DETECTIONS
        return Detections(
            np.array([self.boxes[cid]], np.float32),
            np.array([0.9], np.float32),
            np.array([1], np.int64),
        )


def record_group(clips, tmp_path, detector, params=STILL, make_tracker=None, matcher=None) -> Path:
    """A live group run of two calibrated cameras, paced like cameras, recorded."""
    out = tmp_path / "out"
    cameras = [
        GroupCamera(cid, FileSource(str(clips[clip]), realtime=True), "file", cal)
        for cid, clip, cal in (
            ("cam1", "moving", calibration_for(tmp_path, "cam1")),
            ("cam2", "frozen", calibration_for(tmp_path, "cam2")),
        )
    ]
    statuses = run_group(
        "g1", cameras, detector, make_tracker or (lambda c: OneTrackPerDetection()), out, CONFIG,
        lambda c, info: run_meta(SETTINGS, info, CONFIG, detector, OneTrackPerDetection(), None),
        record=True, matcher=matcher or CourtMatcher(params),
    )  # fmt: skip
    assert statuses == {"cam1": "ended", "cam2": "ended"}
    return out


def replay_group(out: Path, detector, matcher=None) -> dict[str, str]:
    group = resolve_group("g1", out)
    targets = {c.camera_id: c.replay.target for c in group.cameras}
    return run_group(
        group.group_id, group.cameras, detector, lambda c: OneTrackPerDetection(), out, CONFIG,
        lambda c, info: run_meta(
            SETTINGS, info, CONFIG, detector, OneTrackPerDetection(), None, targets[c]
        ),
        record=False, matcher=matcher or live_matcher(group.params, ARGS.track_lost_secs),
    )  # fmt: skip


def digests(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def runs(out: Path) -> dict[str, list[tuple[dict, Path]]]:
    """camera_id -> [(run.json, run folder)] in session.json order: the live run first."""
    found = {}
    for folder in (p for p in out.iterdir() if p.is_dir()):
        session = load(folder / "session.json")
        found[session["camera_id"]] = [
            (load(folder / "runs" / r / "run.json"), folder / "runs" / r) for r in session["runs"]
        ]
    return found


def ids_by_video_frame(run_dir: Path, fps: float) -> dict[int, list[tuple[int, str]]]:
    """Video frame index -> the (track_id, link) rows of that frame, for the frames this run
    processed and that are in the video."""
    index = {
        f["seq"]: round(float(f["t_video"]) * fps)
        for f in rows(run_dir / "frames.csv")
        if f["t_video"]
    }
    out: dict[int, list[tuple[int, str]]] = {}
    for t in rows(run_dir / "tracks.csv"):
        if t["seq"] in index:
            out.setdefault(index[t["seq"]], []).append((int(t["track_id"]), t["link"]))
    return out


def replay_ids_equal_live(out: Path) -> int:
    """Assert every camera's replay gives the live run's (track_id, link) rows on the video
    frames both processed; returns how many frames were compared."""
    compared = 0
    for cid, ((_, live_dir), (_, replay_dir)) in runs(out).items():
        live_ids = ids_by_video_frame(live_dir, FPS)
        replay_ids = ids_by_video_frame(replay_dir, FPS)
        assert live_ids, f"{cid}: the live run has no tracks"
        for k, rows_ in live_ids.items():
            assert replay_ids[k] == rows_, f"{cid} video frame {k}"
            compared += 1
    return compared


def test_a_group_replay_adds_one_run_per_camera_and_leaves_the_originals_byte_identical(
    clips, tmp_path
):
    detector = Scripted(NEAR)
    out = record_group(clips, tmp_path, detector)
    folders = [p for p in out.iterdir() if p.is_dir()]
    before = {p.name: digests(p) for p in folders}
    sessions_before = {p.name: load(p / "session.json") for p in folders}

    assert replay_group(out, detector) == {"cam1": "ended", "cam2": "ended"}

    found = runs(out)
    assert set(found) == {"cam1", "cam2"}
    replay_runs = []
    for folder in folders:
        session = load(folder / "session.json")
        live_id, replay_id = session["runs"]
        assert session == {**sessions_before[folder.name], "runs": [live_id, replay_id]}
        after = digests(folder)
        # every file of the original run, the video and session.json except its runs list
        assert {k: v for k, v in after.items() if replay_id not in k and k != "session.json"} == {
            k: v for k, v in before[folder.name].items() if k != "session.json"
        }
        run = load(folder / "runs" / replay_id / "run.json")
        validate("run", run)
        assert run["mode"] == "replay" and run["counts"]["processed"] == 30
        assert run["input"]["sha256"] == session["recording"]["sha256"]
        assert run["calibration"] == load(folder / "runs" / live_id / "run.json")["calibration"]
        replay_runs.append((session, run))
    groups = [run["group"] for _, run in replay_runs]
    live_group = found["cam1"][0][0]["group"]
    assert groups[0] == groups[1] and groups[0]["group_run_id"] != live_group["group_run_id"]
    assert groups[0]["params"] == live_group["params"]  # the live run's matcher
    assert sorted(groups[0]["cameras"], key=lambda c: c["camera_id"]) == sorted(
        ({"camera_id": s["camera_id"], "session_id": s["session_id"], "run_id": r["run_id"]}
         for s, r in replay_runs),
        key=lambda c: c["camera_id"],
    )  # fmt: skip


def test_a_replay_with_a_saved_calibration_gives_the_live_runs_court_positions(clips, tmp_path):
    detector = Scripted(NEAR)
    out = record_group(clips, tmp_path, detector)
    replay_group(out, detector)
    for cid, ((_, live_dir), (_, replay_dir)) in runs(out).items():

        def positions(run_dir):
            return {
                (r["seq"], r["track_id"]): (r["x_m"], r["y_m"])
                for r in rows(run_dir / "tracks.csv")
            }

        live_pos = positions(live_dir)
        assert live_pos and all(x and y for x, y in live_pos.values()), cid
        assert positions(replay_dir) == live_pos, cid


@pytest.mark.parametrize("malformed", [False, True], ids=["singular", "malformed-block"])
def test_a_singular_saved_calibration_replays_that_camera_uncalibrated_with_an_error_event(
    clips, tmp_path, malformed
):
    detector = Scripted(NEAR)
    out = record_group(clips, tmp_path, detector)
    live_cam2 = runs(out)["cam2"][0][0]["calibration"]
    (live, live_dir) = runs(out)["cam1"][0]
    if malformed:
        live["calibration"] = []
    else:
        live["calibration"]["homography_image_to_court"] = [[1, 0, 0], [0, 0, 0], [0, 0, 1]]
    (live_dir / "run.json").write_text(json.dumps(live), encoding="utf-8")

    assert replay_group(out, detector) == {"cam1": "ended", "cam2": "ended"}

    found = runs(out)
    (_, _), (replay, replay_dir) = found["cam1"]
    assert replay["mode"] == "replay" and not replay["calibration"]
    assert not any(t["x_m"] for t in rows(replay_dir / "tracks.csv"))
    folder = replay_dir.parent.parent
    events = load(folder / "session.json")["events"]
    [problem] = [e for e in events if "calibration not used" in (e.get("detail") or "")]
    assert problem["kind"] == "error"
    assert replay["checks"][0]["result"] == "failed"
    assert any(e["kind"] == "startup_check_failed" for e in events)
    assert found["cam2"][1][0]["calibration"] == live_cam2


@pytest.mark.parametrize(
    "boxes, start, gone",
    [
        (FAR, {"cam2": 10}, None),
        (FAR, {"cam1": 10}, None),
        (NEAR, {"cam2": 10}, None),
        # gone 20 frames (1.3 s live, longer than lost_s): back with a new ID live, and in the
        # replay only if it keeps the live run's times (at file speed the gap is far shorter)
        (FAR, {"cam2": 5}, {"cam1": range(8, 28)}),
    ],
    ids=["cam1-first", "cam2-first", "one-person", "lost-and-back"],
)
def test_the_replays_shared_ids_equal_the_live_runs_on_the_same_frames(
    clips, tmp_path, boxes, start, gone
):
    detector = Scripted(boxes, start, gone)
    out = record_group(clips, tmp_path, detector)
    replay_group(out, detector)
    assert replay_ids_equal_live(out) >= 20


class ForcedLag:
    """Makes the live cameras' processing order differ from their receive order at video frame
    10 (D-072): both cameras' trackers meet there, and the camera whose frame was received first
    waits until the other camera's frame has passed the matcher. Each camera has its own tracker
    thread and the detector lock is free by then, so nothing waits on anything but this."""

    def __init__(self):
        self.t_recv: dict[str, float] = {}
        self.passed = {"cam1": threading.Event(), "cam2": threading.Event()}
        self._meet = threading.Barrier(2)

    def tracker(self, camera_id):
        lag = self

        class Tracker(OneTrackPerDetection):
            def update(self, dets, frame):
                if frame.seq == 10:
                    lag.meet(camera_id, frame.t_recv)
                return super().update(dets, frame)

        return Tracker()

    def meet(self, camera_id, t_recv):
        self.t_recv[camera_id] = t_recv
        try:
            self._meet.wait(10)
        except threading.BrokenBarrierError:
            return  # the test then says the order was not forced
        first = min(self.t_recv, key=self.t_recv.get)
        if camera_id == first:
            self.passed["cam2" if first == "cam1" else "cam1"].wait(10)

    def matcher(self, params):
        """A matcher that records its calls and says when a camera's frame 10 has passed it."""
        lag, calls = self, []

        class Spy(CourtMatcher):
            def update(self, camera_id, t_recv, tracks):
                out = super().update(camera_id, t_recv, tracks)
                calls.append((camera_id, t_recv))
                if sum(c == camera_id for c, _ in calls) == 11:  # video frame 10, nothing dropped
                    lag.passed[camera_id].set()
                return out

        return Spy(params), calls


def test_the_replay_follows_the_live_matcher_order_when_it_differs_from_receive_order(
    clips, tmp_path
):
    detector = Scripted(NEAR, {"cam2": 10})
    lag = ForcedLag()
    matcher, live_calls = lag.matcher(STILL)
    out = record_group(clips, tmp_path, detector, make_tracker=lag.tracker, matcher=matcher)

    # the live run really processed frame 10 against the order it was received in
    assert set(lag.t_recv) == {"cam1", "cam2"}, "both cameras reached video frame 10"
    at = {c: [i for i, (cc, _) in enumerate(live_calls) if cc == c][10] for c in lag.t_recv}
    received_first = min(lag.t_recv, key=lag.t_recv.get)
    assert at[received_first] > at["cam2" if received_first == "cam1" else "cam1"]
    replay_group(out, detector)
    assert replay_ids_equal_live(out) >= 20


def live_calls(out: Path) -> list[tuple[str, float]]:
    """The live run's matcher calls in the order it made them: (camera_id, group time)."""
    calls = []
    for cid, found in runs(out).items():
        live, live_dir = found[0]
        for f in rows(live_dir / "frames.csv"):
            assert f["match_seq"], f"{cid} seq {f['seq']}: a processed frame has a matcher call"
            calls.append((int(f["match_seq"]), cid, live["t0_mono"] + float(f["t_recv"])))
    assert sorted(n for n, _, _ in calls) == list(range(len(calls)))  # one counter, no gaps
    return [(cid, t) for _, cid, t in sorted(calls)]


def test_the_replay_matcher_gets_the_live_runs_group_times_in_the_live_call_order(clips, tmp_path):
    detector = Scripted(FAR, {"cam2": 5})
    out = record_group(clips, tmp_path, detector)
    calls = []

    class Spy(CourtMatcher):
        def update(self, camera_id, t_recv, tracks):
            calls.append((camera_id, t_recv))
            return super().update(camera_id, t_recv, tracks)

    replay_group(out, detector, matcher=Spy(STILL))
    live = live_calls(out)
    assert len(calls) == len(live) == 60
    assert [c for c, _ in calls] == [c for c, _ in live]
    assert all(abs(a - b) < 1e-9 for (_, a), (_, b) in zip(calls, live, strict=True))
    for found in runs(out).values():  # the replay numbers its own calls too
        _, replay_dir = found[1]
        numbers = [int(f["match_seq"]) for f in rows(replay_dir / "frames.csv")]
        assert numbers == sorted(numbers) and len(set(numbers)) == 30


def rewrite_live_frames(out: Path, camera_id: str, edit) -> None:
    """Apply edit(fieldnames, rows) -> (fieldnames, rows) to a camera's live frames.csv."""
    _, live_dir = runs(out)[camera_id][0]
    path = live_dir / "frames.csv"
    names = list(rows(path)[0])
    names, new_rows = edit(names, rows(path))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, names, extrasaction="ignore")
        w.writeheader()
        w.writerows(new_rows)


def replay_events(out: Path, kind: str) -> dict[str, list[dict]]:
    found = {}
    for folder in (p for p in out.iterdir() if p.is_dir()):
        session = load(folder / "session.json")
        found[session["camera_id"]] = [e for e in session["events"] if e["kind"] == kind]
    return found


def test_a_recording_without_match_seq_replays_in_receive_order_and_says_so(clips, tmp_path):
    detector = Scripted(NEAR, {"cam2": 10})
    out = record_group(clips, tmp_path, detector)
    live = live_calls(out)
    for cid in ("cam1", "cam2"):  # a recording from before 0.27.0
        rewrite_live_frames(
            out, cid, lambda names, rs: ([n for n in names if n != "match_seq"], rs)
        )
    calls = []

    class Spy(CourtMatcher):
        def update(self, camera_id, t_recv, tracks):
            calls.append((camera_id, t_recv))
            return super().update(camera_id, t_recv, tracks)

    assert replay_group(out, detector, matcher=Spy(STILL)) == {"cam1": "ended", "cam2": "ended"}

    assert len(calls) == 60  # every frame, as before
    assert [t for _, t in calls] == sorted(t for _, t in live)  # in group-time order
    events = replay_events(out, "replay_order_approximate")
    assert set(events) == {"cam1", "cam2"}
    for cid, found in events.items():
        [event] = found
        assert event["t_mono"] is None and "match_seq" in event["detail"], cid


def test_a_frame_with_no_match_seq_is_not_processed_by_the_replay(clips, tmp_path):
    detector = Scripted(NEAR)
    out = record_group(clips, tmp_path, detector)
    skipped = {"3", "4"}

    def blank(names, rs):
        return names, [{**r, "match_seq": ""} if r["seq"] in skipped else r for r in rs]

    rewrite_live_frames(out, "cam1", blank)
    calls = []

    class Spy(CourtMatcher):
        def update(self, camera_id, t_recv, tracks):
            calls.append(camera_id)
            return super().update(camera_id, t_recv, tracks)

    replay_group(out, detector, matcher=Spy(STILL))

    assert calls.count("cam1") == 28 and calls.count("cam2") == 30
    assert not any(replay_events(out, "replay_order_approximate").values())  # the order is exact
    (_, _), (_, replay_dir) = runs(out)["cam1"]
    frames = {f["seq"]: f for f in rows(replay_dir / "frames.csv")}
    assert len(frames) == 30  # nothing is silently dropped: the frame is logged, with no tracks
    assert all(frames[s]["match_seq"] == "" and frames[s]["n_tracks"] == "0" for s in skipped)
    assert not any(t["seq"] in skipped for t in rows(replay_dir / "tracks.csv"))


def test_a_target_that_is_no_group_is_none_and_a_mixed_group_is_refused(clips, tmp_path):
    out = record_group(clips, tmp_path, Scripted(NEAR))
    assert resolve_group("nope", out) is None
    folder = next(p for p in out.iterdir() if p.is_dir())
    session = load(folder / "session.json")
    live = folder / "runs" / session["runs"][0] / "run.json"
    run = load(live)
    run["group"]["group_run_id"] = "another"
    live.write_text(json.dumps(run), encoding="utf-8")
    with pytest.raises(ReplayError, match="group run"):
        resolve_group("g1", out)
    (live.parent / "frames.csv").unlink()  # a session not as written: refused, not a traceback
    with pytest.raises(ReplayError, match="cannot be replayed"):
        resolve_group("g1", out)


def cli(out: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "services.edge.main", "--no-detect", "--out", str(out), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )  # fmt: skip


def test_the_command_replays_a_group_by_its_id_and_one_session_alone_as_before(clips, tmp_path):
    out = tmp_path / "out"
    for cid, clip in (("cam1", "moving"), ("cam2", "frozen")):  # a group, one process per camera
        args = ["--source", str(clips[clip]), "--link", "file", "--camera-id", cid]
        assert cli(out, *args, "--group-id", "g1").returncode == 0
    folders = sorted(p for p in out.iterdir() if p.is_dir())
    before = {p.name: digests(p / "runs") for p in folders}

    result = cli(out, "--replay", "g1")
    assert result.returncode == 0, result.stderr
    found = runs(out)
    assert {cid: len(r) for cid, r in found.items()} == {"cam1": 2, "cam2": 2}
    [group] = {json.dumps(r[1][0]["group"], sort_keys=True) for r in found.values()}
    assert json.loads(group)["group_id"] == "g1"
    for p in folders:  # the live runs are untouched
        assert {k: v for k, v in digests(p / "runs").items() if k in before[p.name]} == before[
            p.name
        ]

    result = cli(out, "--replay", str(folders[0]))  # one session of the group: as before
    assert result.returncode == 0, result.stderr
    session = load(folders[0] / "session.json")
    assert len(session["runs"]) == 3
    assert load(folders[0] / "runs" / session["runs"][2] / "run.json")["group"] is None


@pytest.mark.parametrize("option", [["--calibration", "x.json"], ["--camera-id", "cam9"]])
def test_the_command_refuses_a_calibration_or_camera_id_for_a_group(clips, tmp_path, option):
    out = tmp_path / "out"
    for cid, clip in (("cam1", "moving"), ("cam2", "frozen")):
        args = ["--source", str(clips[clip]), "--link", "file", "--camera-id", cid]
        assert cli(out, *args, "--group-id", "g1").returncode == 0
    result = cli(out, "--replay", "g1", *option)
    assert result.returncode != 0 and option[0] in result.stderr
    assert "error: config_conflict: a group replay takes" in result.stderr
    assert all(len(r) == 1 for r in runs(out).values())
