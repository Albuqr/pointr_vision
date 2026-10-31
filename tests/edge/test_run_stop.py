"""T9 (#71): the one stop table (services/edge/run/stop.py). The entry points' behaviour at each
phase is pinned end to end in test_run_characterisation.py, including a Studio stop passing
through a group replay. These are the table and its helpers."""

import threading

import pytest

from services.edge import contract
from services.edge.run import stop as stop_module
from services.edge.run.stop import (
    EXIT_INTERRUPTED,
    StopRequest,
    stop_before_session,
    stop_end,
    stop_source,
)


@pytest.mark.parametrize(
    "ui,session,kind,detail,status,code",
    [
        (True, False, "stopped", contract.UI_STOP_DETAIL, None, 0),
        (False, False, "interrupted", "Ctrl+C", None, EXIT_INTERRUPTED),
        (True, True, "stopped", contract.UI_STOP_DETAIL, "ended", 0),
        (False, True, "interrupted", "Ctrl+C", "interrupted", EXIT_INTERRUPTED),
    ],
)
def test_the_table_maps_every_stop_to_status_event_and_exit_code(
    ui, session, kind, detail, status, code
):
    end = stop_end(ui=ui, session=session)
    assert (end.kind, end.detail, end.status, end.exit_code) == (kind, detail, status, code)
    event = end.event(None if not session else 1.5)
    assert (event.kind, event.detail) == (kind, detail)
    assert event.t_mono == (1.5 if session else None)  # no run yet, no t0 (D-014)


def test_a_stop_before_any_session_prints_its_event_and_returns_its_exit_code():
    printed = []
    emit = lambda ev, t0: printed.append((ev.kind, t0))  # noqa: E731
    assert stop_before_session(StopRequest("ui"), emit) == 0
    assert stop_before_session(StopRequest(), emit) == EXIT_INTERRUPTED
    assert printed == [("stopped", None), ("interrupted", None)]


def test_only_a_stop_ui_line_is_a_studio_stop():
    assert stop_source("stop ui\n") == "ui"
    assert stop_source("stop\n") is None
    assert stop_source("") is None
    assert StopRequest("ui").ui and not StopRequest().ui


def test_ctrl_c_is_held_then_released():
    arrived = threading.Event()
    previous = stop_module.hold_ctrl_c(arrived)
    try:
        stop_module.signal.raise_signal(stop_module.signal.SIGINT)  # only sets the event
        assert arrived.is_set()
    finally:
        stop_module.release_ctrl_c(previous)
    with pytest.raises(KeyboardInterrupt):
        stop_module.signal.raise_signal(stop_module.signal.SIGINT)
