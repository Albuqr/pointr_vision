"""What one camera looks like to the operator, worked out in one place and with no I/O.

Studio reads the child's progress, the session snapshot, the recent frames and the preview's
status.json, hands them to `camera_view`, and applies the result (the camera log, the audit
trail). Nothing here reads a file, asks a process or writes a log, so every case is a table row.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.edge.launcher import ChildProgress
from services.edge.session.folder import SessionSnapshot
from services.edge.session.writer import mask_credentials

FINISHED = ("ended", "interrupted", "error")  # session.json statuses written at the end
HEALTH_BY_EVENT = {
    "source_lost": "LOST",
    "source_recovered": "OK",
    "frozen_frames": "FROZEN",
    "dark_frames": "DARK",
}


@dataclass(frozen=True)
class RunError:
    """An error line the camera printed while recording (the camera keeps recording)."""

    error: str
    detail: str


@dataclass(frozen=True)
class Problem:
    """Why a camera ended or never recorded; Studio logs it once per child.

    `is_error`: set the camera's last error and add an `event_kind` event. Otherwise it is a
    normal end: audit it, and add the event only when `event_kind` is set (the session file did
    not already carry one).
    """

    token: object
    is_error: bool
    message: str
    detail: str
    event_kind: str | None
    event_detail: str | None


@dataclass(frozen=True)
class CameraView:
    camera_id: str
    name: str
    state: str
    error: str | None
    health: str
    processed_fps: float | None
    people: int
    tracks: int
    drops: int
    preview_drops: int
    preview_port: int | None
    last_event: Mapping | None
    session_folder: str | None
    calibration: Mapping | None
    run_errors: tuple[RunError, ...]
    problem: Problem | None


def camera_view(
    progress: ChildProgress,
    session: SessionSnapshot | None,
    frames: Sequence[Mapping[str, Any]],
    live: Mapping[str, Any],
) -> CameraView:
    """`session` was read after `progress`; `live` is the preview's status.json ({} if none)."""
    cam = progress.cam
    document = session.document() if session else {}
    written = session.status if session else None  # None when session.json is unreadable
    status = written
    if session and session.data is None:
        status = "error"
        document = {
            "status": "error",
            "events": [{"kind": "error", "detail": "; ".join(session.problems)}],
        }
    events = document.get("events") or []
    latest = session.latest_run if session else None
    ready = (latest.ready if latest else None) or {}

    state = _state(progress, status, ready)
    error = _error(progress, state, events, status)
    fps, people, tracks, drops = _frame_figures(frames)
    health = "OK"
    for event in events:
        health = HEALTH_BY_EVENT.get(event.get("kind"), health)
    port = progress.confirmed_preview_port
    if port and live:
        health = live.get("health", health)
        fps = live.get("processed_fps", fps)
        people = live.get("people", people) or 0
        tracks = live.get("tracks", tracks) or 0
        drops = live.get("drops", drops) or 0
    last = events[-1] if events else None
    if last is not None and last.get("detail") is not None:
        last = {**last, "detail": mask_credentials(str(last.get("detail")))}
    calibration = document.get("calibration")
    return CameraView(
        camera_id=cam.camera_id,
        name=cam.name or cam.camera_id,
        state=state,
        error=error,
        health=health,
        processed_fps=fps,
        people=people,
        tracks=tracks,
        drops=drops,
        preview_drops=live.get("preview_drops", 0) if port else 0,
        preview_port=port,
        last_event=last,
        session_folder=str(progress.session_dir) if progress.session_dir else None,
        calibration=(
            {
                "calibration_id": calibration.get("calibration_id"),
                "check_error_m": calibration.get("check_error_m"),
            }
            if calibration
            else None
        ),
        run_errors=_run_errors(progress),
        problem=_problem(progress, state, written, events),
    )


def latest_frames_path(session: SessionSnapshot | None) -> Path | None:
    """Where the frame log of the session's last listed run is, for the caller to read."""
    run = session.latest_run if session else None
    return run.path / "frames.csv" if run else None


def _state(progress: ChildProgress, status: str | None, ready: Mapping) -> str:
    """From the child's output, session.json status and run.json `ready` (D-052)."""
    if status in ("ended", "interrupted"):
        return status
    if progress.failure is not None or status == "error":
        return "error"
    if progress.stop_sent:
        return "stopping" if progress.alive else "interrupted"
    if not progress.alive:  # gone with no end written: it died, or it never recorded
        return "error"
    if not progress.session_dir:
        return "loading_model" if progress.loading_model else "starting"
    if not ready.get("first_frame"):
        return "waiting_first_frame"
    return "preview_ready" if ready.get("first_preview") else "recording"


def _error(progress, state, events, status) -> str | None:
    """Why a camera is in error, credentials masked; a start failure shows in any state."""
    reason = progress.failure
    if state != "error":
        return mask_credentials(reason or "") or None
    if not reason and not progress.alive and status not in FINISHED:
        return "the camera process exited without writing a session end"
    if not reason:
        last = events[-1].get("detail") if events else None
        reason = last or "the camera stopped without ending its session"
    return mask_credentials(str(reason))


def _frame_figures(frames) -> tuple[float | None, int, int, int]:
    try:
        frame = frames[-1] if frames else {}
        elapsed = (
            float(frame.get("t_proc_end", 0)) - float(frames[0].get("t_proc_start", 0))
            if frames
            else 0
        )
        return (
            len(frames) / elapsed if elapsed > 0 else None,
            int(frame.get("n_detections") or 0),
            int(frame.get("n_tracks") or 0),
            int(frame.get("dropped_total") or 0),
        )
    except (ValueError, KeyError, TypeError):
        return None, 0, 0, 0


def _source(progress) -> str:
    return mask_credentials(str(progress.cam.source))


def _run_errors(progress) -> tuple[RunError, ...]:
    if not progress.session_dir:
        return ()
    return tuple(
        RunError(error, f"source: {_source(progress)}\nreason: {error}")
        for error in progress.run_errors
    )


def _problem(progress, state, status, events) -> Problem | None:
    failure = progress.failure
    if failure is None and progress.alive and status not in FINISHED:
        return None
    kind = progress.failure_kind or "exited"
    if failure is not None and kind == "start_timeout":
        message = "The camera took too long to open, so it was stopped."
    elif failure is not None:
        message = "The camera could not start recording."
    else:
        message = "The camera stopped recording because of an error."
    lines = [f"source: {_source(progress)}"]
    reason = None
    if failure is not None:
        lines += [f"failure kind: {kind}", f"reason: {failure}"]
    else:
        lines.append(f"session status: {status}")
        if state == "error":
            reason = _error(progress, state, events, status)
            if not progress.alive and status not in FINISHED:
                message = reason
        elif progress.stop_sent and status not in ("ended", "interrupted"):
            message = "The camera was stopped; its process exited without writing a session end."
        else:
            message = f"The camera recording ended with status {state}."
        lines.append(f"reason: {reason if state == 'error' else message}")
    if progress.exit_code is not None:
        lines.append(f"exit code: {progress.exit_code}")
    if progress.tail:
        lines.append(f"output (last {len(progress.tail)} lines):")
        lines.extend(progress.tail)
    detail = "\n".join(lines)
    if failure is None and state != "error":
        event_kind = "stopped" if state == "ended" else "interrupted"
        seen = any(event.get("kind") == event_kind for event in events)
        return Problem(
            progress.token, False, message, detail, None if seen else event_kind, message
        )
    return Problem(
        progress.token,
        True,
        message,
        detail,
        kind if failure is not None else "error",
        failure if failure is not None else message,
    )
