"""The run module (R2a follow-up T11, #73, D-071): `plan_from_args` and `execute` for one camera (a
group of one), a group, a replay into a recorded session and a replay of a bare video file. Driven
in-process on synthetic clips with a fake detector: no camera, weights or network. The run paths'
lines, codes and files are pinned by test_run_characterisation; these tests pin what is new here."""

import _thread
import json
import threading
import time
from pathlib import Path

import pytest

from services.edge import group_main
from services.edge.capture.types import utc_now
from services.edge.group_runner import is_solo
from services.edge.run import execute as execute_module
from services.edge.run import wait
from services.edge.run.args import parse_args
from services.edge.run.execute import execute
from services.edge.run.perception import Perception
from services.edge.run.plan import PlanError, plan_from_args
from services.edge.run.report import Reporter
from services.edge.run.stop import (
    EXIT_CAPTURE_ERROR,
    EXIT_INTERRUPTED,
    EXIT_OPEN_FAILED,
    StopRequest,
)
from tests.edge.fakes import EvenFrameDetector, OneTrackPerDetection
from tests.edge.test_calibration_size import calibration_file
from tests.edge.test_session import load, rows


def loaded(detector=None):
    """The perception loader of a test: the fake detector, or nothing with detection off."""
    if detector is None:
        return lambda args: Perception()
    perception = Perception(detector, None, None, {"t_wall": utc_now(), "t_pc": 0.0})
    return lambda args: perception


def argv(clip, out, camera_id="cam1", *extra):
    return [
        "--source", str(clip), "--link", "file", "--camera-id", camera_id, "--out", str(out),
        "--no-record", *extra,
    ]  # fmt: skip


def run(cams, *, detector=None, tagged=False, stop=None, **kw):
    """Plan the arguments and execute the plan, as an entry point does."""
    plan = plan_from_args([parse_args(a) for a in cams])
    return plan, execute(
        plan,
        stop or StopRequest(),
        perception=kw.pop("perception", loaded(detector)),
        make_tracker=lambda args: OneTrackPerDetection(),
        reporter=Reporter(tagged),
        **kw,
    )


def sessions(out: Path):
    """(session.json, last run.json, its tracks rows) of each session folder, by camera id."""
    found = {}
    for folder in sorted(p for p in out.iterdir() if p.is_dir()):
        session = load(folder / "session.json")
        run_dir = folder / "runs" / session["runs"][-1]
        found[session["camera_id"]] = (session, load(run_dir / "run.json"), run_dir)
    return found


# -- a group of one ----------------------------------------------------------------------------


def test_a_group_of_one_has_no_matcher_no_appearance_and_no_group_block(
    clips, tmp_path, monkeypatch, capsys
):
    from services.edge import group_runner

    def never(*a, **kw):
        raise AssertionError("a group of one must not use the cross-camera machinery")

    for name in ("CourtMatcher", "CameraTracker", "SharedDetector", "describe"):
        monkeypatch.setattr(group_runner, name, never)
    detector = EvenFrameDetector()
    plan, outcome = run([argv(clips["moving"], tmp_path)], detector=detector)
    assert plan.solo and plan.matcher is None
    assert (outcome.exit_code, outcome.statuses) == (0, {"cam1": "ended"})
    [(session, run_json, run_dir)] = sessions(tmp_path).values()
    assert run_json["group"] is None and session["status"] == "ended"
    links = {t["link"] for t in rows(run_dir / "tracks.csv")}
    assert links == {"unshared"}
    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("session: ") for line in out)
    assert not [line for line in out if line.startswith("[cam1]")]  # untagged, as a single camera


def test_two_cameras_still_share_one_detector_with_a_capture_thread_each(clips, tmp_path):
    """ADR 0007: one detector for the group's cameras, called from each camera's own thread."""
    seen = set()

    class Spy(EvenFrameDetector):
        def detect(self, frame):
            seen.add((frame.source_id, threading.get_ident()))
            return super().detect(frame)

    cams = [argv(clips["moving"], tmp_path, "cam1"), argv(clips["frozen"], tmp_path, "cam2")]
    plan, outcome = run(cams, detector=Spy(), tagged=True)
    assert not plan.solo and plan.matcher is not None
    assert outcome.statuses == {"cam1": "ended", "cam2": "ended"}
    assert len({source for source, _ in seen}) == 2
    assert len({thread for _, thread in seen}) >= 2
    for _, run_json, _ in sessions(tmp_path).values():
        assert run_json["group"] is not None


# -- planning ----------------------------------------------------------------------------------


def test_planning_fails_with_exit_2(clips, tmp_path, capsys):
    cases = [
        argv(tmp_path / "missing.mp4", tmp_path),
        [*argv(clips["moving"], tmp_path), "--link", "usb"],  # contradicts a file source
        ["--replay", str(tmp_path / "nothing"), "--out", str(tmp_path)],
    ]
    for case in cases:
        with pytest.raises(PlanError) as error:
            plan_from_args([parse_args(case)])
        assert error.value.report(Reporter()) == EXIT_OPEN_FAILED
    err = capsys.readouterr().err
    assert "error: source_open_failed: cannot open source" in err
    assert "error: config_conflict: --link usb contradicts a file source" in err


def test_an_entry_point_plans_before_it_loads_the_model(clips, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(group_main, "load_perception", lambda a, d: pytest.fail("the model loaded"))
    monkeypatch.setattr(group_main, "resolve_device", lambda requested: ("cpu", None))
    cams = [
        json.dumps(argv(clips["moving"], tmp_path, "cam1")),
        json.dumps(argv(tmp_path / "missing.mp4", tmp_path, "cam2")),
    ]
    assert group_main.main(cams) == EXIT_OPEN_FAILED
    assert "[cam2] error: source_open_failed: cannot open source" in capsys.readouterr().err


def test_a_plan_error_is_reported_as_the_run_reports_everything(tmp_path, capsys):
    error = PlanError.source("x.mp4", RuntimeError("no such file"), "cam2")
    assert error.report(Reporter(tagged=False)) == EXIT_OPEN_FAILED
    plain = capsys.readouterr()
    assert "- source_open_failed: no such file" in plain.out  # the event line a lone camera prints
    assert "error: source_open_failed: cannot open source 'x.mp4': no such file" in plain.err
    assert error.report(Reporter(tagged=True)) == EXIT_OPEN_FAILED
    tagged = capsys.readouterr()
    assert (
        tagged.out == "" and "[cam2] error: source_open_failed: cannot open source: " in tagged.err
    )


def test_the_three_kinds_of_camera(clips, tmp_path):
    live = plan_from_args([parse_args(argv(clips["moving"], tmp_path))])
    assert [c.kind for c in live.cameras] == ["live"]
    file = plan_from_args([parse_args(["--replay", str(clips["moving"]), "--out", str(tmp_path)])])
    assert [c.kind for c in file.cameras] == ["replay_file"] and file.cameras[0].camera_id is None
    record = [a for a in argv(clips["moving"], tmp_path / "rec") if a != "--no-record"]
    run([record], detector=EvenFrameDetector())
    [(session, _, _)] = sessions(tmp_path / "rec").values()
    replay = ["--replay", session["session_id"], "--out", str(tmp_path / "rec")]
    into = plan_from_args([parse_args(replay)])
    assert is_solo(into.cameras) and [c.kind for c in into.cameras] == ["replay_session"]


# -- replays through execute -------------------------------------------------------------------


def test_a_bare_video_file_replays_into_a_new_session(clips, tmp_path, capsys):
    plan, outcome = run([["--replay", str(clips["moving"]), "--out", str(tmp_path)]],
                        detector=EvenFrameDetector())  # fmt: skip
    assert (outcome.exit_code, outcome.statuses) == (0, {None: "ended"})
    [(session, run_json, run_dir)] = sessions(tmp_path).values()
    assert session["camera_id"] is None and session["status"] == "ended"
    assert run_json["mode"] == "replay" and run_json["input"]["sha256"]
    assert run_json["group"] is None and len(session["runs"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("session: ") for line in out)
    assert not [line for line in out if line.startswith("[")]


def test_a_replay_adds_a_run_to_the_recorded_session_and_uses_its_calibration(clips, tmp_path):
    out = tmp_path / "rec"
    calibration = calibration_file(tmp_path)
    live = [a for a in argv(clips["moving"], out) if a != "--no-record"]
    _, recorded = run([[*live, "--calibration", str(calibration)]], detector=EvenFrameDetector())
    assert recorded.exit_code == 0
    [(session, first, _)] = sessions(out).values()
    assert first["calibration"] is not None and first["mode"] == "live"
    plan, outcome = run([["--replay", session["session_id"], "--out", str(out)]],
                        detector=EvenFrameDetector())  # fmt: skip
    assert [c.kind for c in plan.cameras] == ["replay_session"]
    assert outcome.exit_code == 0
    [(session, last, _)] = sessions(out).values()
    assert len(session["runs"]) == 2 and last["mode"] == "replay"
    assert last["calibration"] is not None and last["group"] is None  # decision 9
    assert session["status"] == "ended"


# -- every opened session gets a final status --------------------------------------------------


def two_cameras(clips, tmp_path, extra_first=(), extra_second=()):
    return [
        argv(clips["moving"], tmp_path, "cam1", *extra_first),
        argv(clips["frozen"], tmp_path, "cam2", *extra_second),
    ]


def statuses_on_disk(out):
    return {cid: s["status"] for cid, (s, _, _) in sessions(out).items()}


def test_a_waiter_that_fails_ends_every_session_with_status_error(clips, tmp_path):
    def broken(pipelines, stop, tick):
        raise RuntimeError("waiter exploded")

    plan, outcome = run(two_cameras(clips, tmp_path), detector=EvenFrameDetector(), tagged=True,
                        waiter=broken)  # fmt: skip
    assert outcome.exit_code == EXIT_CAPTURE_ERROR
    assert outcome.statuses == {"cam1": "error", "cam2": "error"}
    assert statuses_on_disk(tmp_path) == {"cam1": "error", "cam2": "error"}


@pytest.mark.parametrize("ui", [True, False], ids=["studio-stop", "ctrl-c"])
def test_a_stop_while_waiting_ends_every_session_by_the_one_table(clips, tmp_path, ui):
    def stopped(pipelines, stop, tick):
        raise KeyboardInterrupt

    stop = StopRequest("ui" if ui else None)
    _, outcome = run(two_cameras(clips, tmp_path), detector=EvenFrameDetector(), tagged=True,
                     waiter=stopped, stop=stop)  # fmt: skip
    status = "ended" if ui else "interrupted"
    assert outcome.exit_code == (0 if ui else EXIT_INTERRUPTED)
    assert outcome.statuses == {"cam1": status, "cam2": status}
    assert statuses_on_disk(tmp_path) == {"cam1": status, "cam2": status}


def test_a_stop_before_any_session_has_no_status_to_give(clips, tmp_path, capsys):
    def interrupted(args):
        raise KeyboardInterrupt

    _, outcome = run([argv(clips["moving"], tmp_path)], perception=interrupted,
                     stop=StopRequest("ui"))  # fmt: skip
    assert (outcome.exit_code, outcome.statuses) == (0, {})
    assert "stopped:" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_a_preview_that_cannot_start_ends_every_session_with_status_error(
    clips, tmp_path, monkeypatch, capsys
):
    """The HTTP preview starts when a session opens, so a failure to bind is a setup failure: the
    sessions already open end `error`, and the preview that did start is closed."""
    started, closed = [], []
    start = execute_module.start_http_preview

    def second_one_fails(port, pipeline):
        if started:
            raise OSError("address already in use")
        started.append(start(port, pipeline))
        closed.append(started[0].close)
        monkeypatch.setattr(started[0], "close", lambda: closed.append("closed"))
        return started[0]

    monkeypatch.setattr(execute_module, "start_http_preview", second_one_fails)
    cams = two_cameras(clips, tmp_path, ("--http-preview", "0"), ("--http-preview", "0"))
    _, outcome = run(cams, detector=EvenFrameDetector(), tagged=True)
    assert outcome.exit_code == EXIT_CAPTURE_ERROR
    assert outcome.statuses == {"cam1": "error", "cam2": "error"}
    assert statuses_on_disk(tmp_path) == {"cam1": "error", "cam2": "error"}
    assert len(started) == 1 and closed[1:] == ["closed"]
    closed[0]()  # the real close, so the test leaves no server behind
    captured = capsys.readouterr()
    assert "error: exited: the group did not run: address already in use" in captured.err
    assert "Traceback" not in captured.err


# -- waiters -----------------------------------------------------------------------------------


def test_the_benchmark_waiter_ends_a_run_at_its_deadline(clips, tmp_path, capsys):
    """The clip plays at its own 15 fps for 2 s; a 0.4 s benchmark ends the run before it does."""
    cams = [[*argv(clips["moving"], tmp_path), "--benchmark", "0.4"]]
    plan = plan_from_args([parse_args(c) for c in cams])
    assert plan.benchmark == 0.4
    started = time.perf_counter()
    _, outcome = run(cams, detector=EvenFrameDetector(), waiter=wait.benchmark(plan.benchmark))
    assert outcome.exit_code == 0 and time.perf_counter() - started < 1.9
    [(_, run_json, _)] = sessions(tmp_path).values()
    assert run_json["counts"]["captured"] < 30
    assert "(0.4 s requested)" in capsys.readouterr().out


def test_the_preview_waiter_runs_the_window_on_the_calling_thread(clips, tmp_path, monkeypatch):
    calls = []

    def window(latest, done, hud, health_state, until, title):
        calls.append((threading.current_thread(), until, title, callable(latest), callable(hud)))
        done.wait(10)

    monkeypatch.setattr(wait, "run_preview", window)
    _, outcome = run([argv(clips["moving"], tmp_path)], detector=EvenFrameDetector(),
                     waiter=wait.preview("Pointr cam1 (q to quit)"))  # fmt: skip
    assert outcome.exit_code == 0
    [(thread, until, title, has_latest, has_hud)] = calls
    assert thread is threading.main_thread() and until is None
    assert title == "Pointr cam1 (q to quit)" and has_latest and has_hud


def test_the_preview_waiter_takes_one_camera_only(clips, tmp_path):
    """A window shows one camera; asked for two it fails the run, and both sessions still end."""
    cams = two_cameras(clips, tmp_path)
    _, outcome = run(cams, detector=EvenFrameDetector(), tagged=True, waiter=wait.preview())
    assert outcome.exit_code == EXIT_CAPTURE_ERROR
    assert statuses_on_disk(tmp_path) == {"cam1": "error", "cam2": "error"}


def test_a_stop_from_the_processing_thread_reaches_the_main_thread_waiter(clips, tmp_path):
    class Stopping(EvenFrameDetector):
        def detect(self, frame):
            if frame.seq == 2:
                _thread.interrupt_main()
                time.sleep(0.3)
            return super().detect(frame)

    _, outcome = run([argv(clips["moving"], tmp_path)], detector=Stopping())
    assert outcome.exit_code == EXIT_INTERRUPTED and outcome.statuses == {"cam1": "interrupted"}


# -- a group of one fails as a single camera does -----------------------------------------------


def test_a_detector_failure_in_a_group_of_one_is_one_error_event_and_no_group_message(
    clips, tmp_path, capsys
):
    _, outcome = run([argv(clips["moving"], tmp_path)], detector=EvenFrameDetector(fail_at=4))
    assert (outcome.exit_code, outcome.statuses) == (EXIT_CAPTURE_ERROR, {"cam1": "error"})
    [(session, _, _)] = sessions(tmp_path).values()
    assert [e["kind"] for e in session["events"]] == ["error"]
    assert "did not run" not in capsys.readouterr().err


def test_a_source_that_fails_to_open_in_a_group_of_one_is_a_source_open_failure(
    clips, tmp_path, monkeypatch, capsys
):
    import cv2

    from services.edge.capture.sources import FileSource

    def explode(self):
        raise cv2.error("backend exploded")

    monkeypatch.setattr(FileSource, "open", explode)
    _, outcome = run([argv(clips["moving"], tmp_path)], detector=EvenFrameDetector())
    assert (outcome.exit_code, outcome.statuses) == (EXIT_OPEN_FAILED, {})
    captured = capsys.readouterr()
    assert "- source_open_failed: backend exploded" in captured.out
    assert "error: source_open_failed: cannot open source" in captured.err
    assert not list(tmp_path.iterdir())
