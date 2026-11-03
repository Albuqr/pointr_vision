"""camera_view: every state and error case as a table row, with no process, file or log."""

import json
from dataclasses import replace

import pytest

from services.app.camera_status import camera_view
from services.edge.launcher import Camera, ChildProgress
from services.edge.session.folder import RunSnapshot, SessionSnapshot, _freeze

SECRET = "rtsp://admin:hunter2@192.168.1.5/stream"


def progress(**fields) -> ChildProgress:
    base = {
        "cam": Camera("cam1", SECRET, "wifi", http_preview_port=5000),
        "alive": True,
        "session_dir": None,
        "failure": None,
        "failure_kind": None,
        "run_errors": (),
        "tail": (),
        "exit_code": None,
        "preview_port": 5000,
        "preview_ready": False,
        "stop_sent": False,
        "loading_model": False,
        "token": object(),
    }
    return ChildProgress(**{**base, **fields})


def session(status="running", ready=None, events=(), runs=True, data=True) -> SessionSnapshot:
    path = __import__("pathlib").Path("s")
    run = RunSnapshot(path / "runs" / "r1", _freeze({"ready": ready}), ())
    doc = {"status": status, "events": list(events)}
    return SessionSnapshot(
        path, _freeze(doc) if data else None, () if data else ("session.json: bad",),
        (run,) if runs and data else None,
    )  # fmt: skip


WITH_SESSION = {"session_dir": "s"}


@pytest.mark.parametrize(
    "fields, snap, expected",
    [
        ({}, None, "starting"),
        ({"loading_model": True}, None, "loading_model"),
        (WITH_SESSION, session(ready={}), "waiting_first_frame"),
        (WITH_SESSION, session(ready=None), "waiting_first_frame"),
        (WITH_SESSION, session(runs=False), "waiting_first_frame"),
        (WITH_SESSION, session(ready={"first_frame": "t"}), "recording"),
        (WITH_SESSION, session(ready={"first_frame": "t", "first_preview": "t"}), "preview_ready"),
        ({"stop_sent": True}, None, "stopping"),
        ({"stop_sent": True, "alive": False}, None, "interrupted"),
        ({"alive": False}, None, "error"),
        ({"alive": False, **WITH_SESSION}, session(), "error"),
        ({"failure": "boom", "alive": False}, None, "error"),
        ({"failure": "boom"}, session(status="ended"), "ended"),  # the written end wins
        (WITH_SESSION, session(status="error"), "error"),
        (WITH_SESSION, session(status="ended"), "ended"),
        ({"alive": False, **WITH_SESSION}, session(status="interrupted"), "interrupted"),
        (WITH_SESSION, session(data=False), "error"),
    ],
)
def test_state(fields, snap, expected):
    assert camera_view(progress(**fields), snap, [], {}).state == expected


@pytest.mark.parametrize(
    "fields, snap, expected",
    [
        ({}, None, None),
        ({"failure": f"cannot open {SECRET}", "alive": False}, None, "cannot open rtsp://***@"),
        ({"alive": False}, None, "the camera process exited without writing a session end"),
        (
            {"alive": False, **WITH_SESSION},
            session(),
            "the camera process exited without writing a session end",
        ),
        (
            WITH_SESSION,
            session(status="error", events=[{"kind": "error", "detail": f"x {SECRET}"}]),
            "x rtsp://***@",
        ),
        (WITH_SESSION, session(status="error"), "the camera stopped without ending its session"),
        (WITH_SESSION, session(status="ended"), None),
    ],
)
def test_error(fields, snap, expected):
    error = camera_view(progress(**fields), snap, [], {}).error
    if expected is None:
        assert error is None
    else:
        assert error.startswith(expected) and "hunter2" not in error


def test_the_view_is_one_value_of_the_progress_it_was_given():
    first = progress(alive=False, failure="boom")
    assert camera_view(first, None, [], {}).problem.token is first.token


def test_no_problem_while_a_camera_is_running_normally():
    assert camera_view(progress(**WITH_SESSION), session(), [], {}).problem is None


def test_a_start_failure_is_an_error_problem_with_kind_source_and_exit_code():
    p = camera_view(
        progress(failure="no session", failure_kind="start_timeout", alive=False, exit_code=3),
        None,
        [],
        {},
    ).problem
    assert p.is_error and p.event_kind == "start_timeout"
    assert p.message == "The camera took too long to open, so it was stopped."
    assert "exit code: 3" in p.detail and "source: rtsp://***@" in p.detail


@pytest.mark.parametrize("status, kind", [("ended", "stopped"), ("interrupted", "interrupted")])
def test_a_normal_end_is_not_an_error_and_adds_its_event_only_once(status, kind):
    ended = progress(alive=False, **WITH_SESSION)
    problem = camera_view(ended, session(status=status), [], {}).problem
    assert not problem.is_error and problem.event_kind == kind
    written = session(status=status, events=[{"kind": kind, "detail": "ui"}])
    assert camera_view(ended, written, [], {}).problem.event_kind is None


def test_a_stop_without_a_written_end_says_so_and_is_not_an_error():
    problem = camera_view(progress(stop_sent=True, alive=False), None, [], {}).problem
    assert not problem.is_error
    assert "without writing a session end" in problem.message


def test_run_errors_are_listed_only_with_a_session_and_masked():
    with_errors = {"run_errors": ("disk full",)}
    assert camera_view(progress(**with_errors), None, [], {}).run_errors == ()
    [only] = camera_view(progress(**WITH_SESSION, **with_errors), session(), [], {}).run_errors
    assert only.error == "disk full" and "hunter2" not in only.detail


FRAMES = [
    {"t_proc_start": "0", "t_proc_end": "1", "n_detections": "2", "n_tracks": "3"},
    {"t_proc_start": "1", "t_proc_end": "2", "n_detections": "4", "n_tracks": "5",
     "dropped_total": "6"},
]  # fmt: skip


def test_figures_come_from_the_frames_and_the_live_status_overrides_them():
    p = progress(**WITH_SESSION, preview_ready=True)
    view = camera_view(p, session(), FRAMES, {})
    assert (view.processed_fps, view.people, view.tracks, view.drops) == (1.0, 4, 5, 6)
    live = {"health": "DARK", "processed_fps": 9.0, "people": 1, "preview_drops": 2}
    view = camera_view(p, session(), FRAMES, live)
    assert (view.health, view.processed_fps, view.people, view.preview_drops) == ("DARK", 9.0, 1, 2)
    assert view.tracks == 5
    # an unconfirmed preview port ignores whatever status.json said
    quiet = camera_view(replace(p, preview_ready=False), session(), FRAMES, live)
    assert quiet.preview_port is None and quiet.health == "OK" and quiet.preview_drops == 0


def test_unreadable_frame_figures_fall_back_to_none_and_zero():
    view = camera_view(progress(), None, [{"t_proc_end": "oops"}], {})
    assert (view.processed_fps, view.people, view.tracks, view.drops) == (None, 0, 0, 0)


def test_health_follows_the_last_health_event_and_last_event_is_masked():
    events = [
        {"kind": "source_lost", "detail": None},
        {"kind": "frozen_frames", "detail": f"at {SECRET}"},
    ]
    view = camera_view(progress(**WITH_SESSION), session(events=events), [], {})
    assert view.health == "FROZEN"
    assert "hunter2" not in json.dumps(view.last_event)


def test_camera_view_takes_no_file_or_log(monkeypatch):
    import builtins

    def refuse(*a, **k):
        raise AssertionError("camera_view touched a file")

    monkeypatch.setattr(builtins, "open", refuse)
    camera_view(progress(**WITH_SESSION), session(), FRAMES, {})
