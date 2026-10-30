"""T4 (#66): a characterisation table of what the four run entry points do today, driven only
through those entry points: `main.main` (one camera, live, session replay and file replay),
`group_main.main` (a live group) and `main.main --replay <group_id>` (a group replay,
`replay/group.py`).

One row is one scenario: path x stop (none, or Studio's / a plain stop before the model loads,
while the sessions open, mid-run) x fault. Each row pins the exit code, every session's final
status, event kinds, run count, `group` block, calibration, checks and track link values, and the
required (and forbidden) stdout / stderr lines.

Rows marked `xfail(strict=True)` assert the INTENDED behaviour where today's paths drift apart (the
brief's C2 drift, C1 table and owner decisions 6, 8, 9, 11, 12); the reason names the ticket that
fixes it, and that ticket flips the row. Everything else is pinned as it is today.

Stops and faults are independent dimensions below, with interaction rows where a requested stop
preempts a scripted model/detector fault. This is not the full stop-by-fault Cartesian product:
the brief does not define precedence for simultaneous independent failures and stops. In
particular, a model/source failure can prevent setup or mid-run from ever being reached.

Combinations that cannot happen are not rows:
- two cameras by session replay or file replay: `--replay` takes one session or one file; two
  cameras replay as a group replay (a group id);
- one camera routed through group_main is not used by today's launcher; explicit group-of-one
  rows below characterize that callable path and T11's promised migration;
- a group replay never takes `--calibration` / `--camera-id` (it refuses them), and its
  calibration refusal is the one the live run saved (the singular-homography row);
- the operator's refusal (`--calibration-failed`) is a start-time argument of a live run.

No camera, model weights or network: fake detector and tracker, short synthetic clips.
"""

import _thread
import csv
import dataclasses
import json
import re
import shutil
import signal
import threading
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import pytest

from fixtures import make_clips as clip_maker
from services.edge import contract
from services.edge import group_main as group_cli
from services.edge import main as cli
from services.edge.camera_pipeline import CameraPipeline
from services.edge.capture.sources import FileSource
from services.edge.replay import group as replay_group
from tests.edge.fakes import EvenFrameDetector, OneTrackPerDetection

SHORT_FRAMES = 8  # 0.5 s of video at the clips' 15 fps
UI, PLAIN = "ui", "plain"
BEFORE_MODEL, SETUP, MID_RUN = "before_model", "setup", "mid_run"
SINGLE, GROUP, SESSION_REPLAY, FILE_REPLAY, GROUP_REPLAY = (
    "single",
    "group",
    "session_replay",
    "file_replay",
    "group_replay",
)
# what a path is, today
CAMERAS = {
    SINGLE: ("cam1",),
    FILE_REPLAY: ("-",),  # a new session from a bare file: no camera id
    SESSION_REPLAY: ("cam1",),
    GROUP: ("cam1", "cam2"),
    GROUP_REPLAY: ("cam1", "cam2"),
}
RUNS = {SINGLE: 1, FILE_REPLAY: 1, SESSION_REPLAY: 2, GROUP: 1, GROUP_REPLAY: 2}  # runs when done
IS_GROUP = {GROUP, GROUP_REPLAY}
INTO_SESSION = {SESSION_REPLAY, GROUP_REPLAY}  # the run is added to a recorded session
EXIT_OK, EXIT_ERROR, EXIT_OPEN, EXIT_STOPPED = (
    0,
    cli.EXIT_CAPTURE_ERROR,
    cli.EXIT_OPEN_FAILED,
    cli.EXIT_INTERRUPTED,
)
ALL_LINKS = frozenset({"position", "appearance", "unshared"})


# -- the table's vocabulary --------------------------------------------------------------------


@dataclass(frozen=True)
class Sess:
    """What one session folder looks like after the run (events and runs: the whole session;
    group, calibrated, checks, links: the newest run)."""

    status: str
    events: tuple[str, ...] = ()  # kinds in session.json, sorted
    runs: int = 1
    group: bool = False  # run.json `group` is a block (else null)
    calibrated: bool = False  # run.json `calibration` is a block (else null)
    checks: tuple[str, ...] | None = None  # run.json `checks` as "name:result"; None is null
    links: frozenset[str] = frozenset({"unshared"})  # tracks.csv `link` values (see test)


@dataclass(frozen=True)
class Row:
    path: str
    stop: tuple[str, str] | None = None  # (UI | PLAIN, BEFORE_MODEL | SETUP | MID_RUN)
    fault: str | None = None
    label: str = ""  # tells apart rows of the same path, stop and fault
    extra: tuple[str, ...] = ()  # more arguments (of the first camera in a group)
    code: int = 0
    sessions: dict[str, Sess] = field(default_factory=dict)  # by camera id; {} none
    out: tuple[str, ...] = ()  # regexes, each matching a stdout line
    err: tuple[str, ...] = ()  # regexes, each matching a stderr line
    absent: tuple[str, ...] = ()  # regexes no stdout line may match
    xfail: str | None = None

    @property
    def id(self) -> str:
        parts = [self.path]
        if self.stop:
            parts.append(f"{self.stop[0]}-stop-{self.stop[1]}")
        parts += [p for p in (self.fault, self.label) if p]
        return "-".join(parts)


# -- expectations of each path -----------------------------------------------------------------


def sess(path: str, status: str = "ended", events=(), *, ran: bool = True, **kw) -> dict[str, Sess]:
    """The sessions of `path` when the run ended `status` with these extra events. A replay leaves
    the session's status as it was and adds only an interrupted or error event to session.json
    (writer.start_run). ran=False: the run never started, so a replay path still has only the live
    run (its session unchanged)."""
    if path in INTO_SESSION:
        status, events = "ended", [e for e in events if e in ("interrupted", "error")]
    out = {}
    for cam in CAMERAS[path]:
        base = {
            "status": status,
            "events": tuple(sorted(events)),
            "runs": RUNS[path] if ran else RUNS[path] - 1,
            "group": path in IS_GROUP,
            "calibrated": path == GROUP_REPLAY,  # the live group was calibrated (see `recorded`)
            "links": (
                frozenset({"appearance", "unshared"})
                if path == GROUP
                else ALL_LINKS
                if path == GROUP_REPLAY
                else frozenset({"unshared"})
            ),
        }
        if path == GROUP:  # no calibration: each camera matches by appearance only (D-058)
            base["events"] = tuple(sorted((*events, "appearance_only")))
        out[cam] = Sess(**{**base, **kw})
    return out


def unchanged(path: str) -> dict[str, Sess]:
    """The sessions of a run that ended before it started: none for a live path, the recorded
    ones (one live run, no new event) for a replay path."""
    if path in (SINGLE, GROUP, FILE_REPLAY):  # a file replay's new session is not made yet
        return {}
    return sess(path, ran=False)


def lines_of(path: str, status: str, cams=None) -> tuple[str, ...]:
    """The status lines of a finished run, as each path prints them today."""
    cams = cams or CAMERAS[path]
    if path in (SINGLE, SESSION_REPLAY, FILE_REPLAY):  # untagged, the whole set
        return (
            r"^device: cpu",
            r"^source: ",
            r"^health: ",
            r"^versions: ",
            r"^session: ",
            rf"^session {status}: ",
            r"^t0_wall=.* captured=.* failed_reads=.* events=\{",
        )
    if path == GROUP:  # tagged, no source/health/versions line and no events count
        return (
            r"^device: cpu",
            *(rf"^\[{c}\] session: " for c in cams),
            *(rf"^\[{c}\] session {status}: " for c in cams),
            *(rf"^\[{c}\] t0_wall=.* failed_reads=\d+ processed=" for c in cams),
        )
    return (r"^device: cpu", *(rf"^\[{c}\] session: " for c in cams))  # group replay: no summary


def stop_row(path: str, who: str, phase: str) -> Row:
    ui = who == UI
    stop = (who, phase)
    if phase == BEFORE_MODEL:  # no session yet: main's pre-session end, on every path
        line = re.escape(f"stopped: {contract.UI_STOP_DETAIL}" if ui else "interrupted: Ctrl+C")
        return Row(
            path,
            stop,
            code=EXIT_OK if ui else EXIT_STOPPED,
            sessions=unchanged(path),
            out=(rf"^\[.*\] - {line}$",),
            absent=(r"session",),
        )
    status = "ended" if ui else "interrupted"
    kind = "stopped" if ui else "interrupted"
    row = Row(
        path,
        stop,
        code=EXIT_OK if ui else EXIT_STOPPED,
        sessions=sess(path, status, (kind,)),
        out=lines_of(path, status),
    )
    if path == GROUP_REPLAY and ui:  # drift: run_replay never passes ui_stop (brief C2)
        return dataclasses.replace(
            row,
            out=(),
            xfail="T9: one stop table on every path, incl. a group replay (a Studio stop is "
            "a normal end: ended, stopped event, exit 0)",
        )
    return row


# -- the rows ----------------------------------------------------------------------------------

DRIFT_T8_REFUSAL = (
    "T8: calibration intake: a refusal at open is not fatal for one camera (decision 6) and is "
    "recorded as a failed calibration check plus startup_check_failed (decision 8)"
)
DRIFT_T9_MODEL = (
    "T9: perception extraction: a model-load failure prints the event line and the error: line "
    "on every path"
)
DRIFT_T11_LINES = (
    "T11: group of one / execute: a group keeps the source:, health: and versions: lines "
    "and the events count"
)
DRIFT_T11_BENCH = "T11: group of one / execute: groups accept --benchmark per camera (decision 12)"
DRIFT_T8_REPLAY = "T8: a single replay uses the live run's calibration (decision 9)"

ALL_PATHS = (SINGLE, GROUP, SESSION_REPLAY, FILE_REPLAY, GROUP_REPLAY)
ROWS: list[Row] = []

# no stop, no fault
for p in ALL_PATHS:
    ROWS.append(
        Row(
            p,
            code=EXIT_OK,
            sessions=sess(p),
            out=lines_of(p, "ended"),
            absent=(r"^\[cam\d\] ",) if p not in IS_GROUP else (r"^session",),
        )
    )
ROWS.append(
    Row(
        GROUP,
        label="group-of-one",
        sessions={"cam1": Sess("ended")},
        out=lines_of(SINGLE, "ended"),
        absent=(r"^\[cam1\] ",),
        xfail=(
            "T11: a group of one has null group, unshared links, and untagged single-camera lines"
        ),
    )
)
ROWS.append(
    Row(
        GROUP,
        label="single-camera-lines",
        code=EXIT_OK,
        sessions=sess(GROUP),
        out=(
            *(rf"^\[{c}\] {what}" for c in CAMERAS[GROUP] for what in ("source: ", "health: ")),
            *(rf"^\[{c}\] versions: " for c in CAMERAS[GROUP]),
            *(rf"^\[{c}\] t0_wall=.* events=\{{" for c in CAMERAS[GROUP]),
        ),
        xfail=DRIFT_T11_LINES,
    )
)
ROWS.append(
    Row(
        SINGLE,
        label="benchmark",
        extra=("--benchmark", "0.3"),
        code=EXIT_OK,
        sessions=sess(SINGLE),
        out=(r"^benchmark: .*s run \(0\.3 s requested\)", r"^benchmark: app delay ms"),
    )
)
ROWS.append(
    Row(
        GROUP,
        label="benchmark",
        extra=("--benchmark", "0.3"),
        code=EXIT_OK,
        sessions=sess(GROUP),
        # Decision 12 promises per-camera benchmark results, not a literal prefix format.
        out=(r"benchmark: .*s run \(0\.3 s requested\)", r"benchmark: app delay ms"),
        xfail=DRIFT_T11_BENCH,
    )
)

# a stop at each phase, both kinds
for p in ALL_PATHS:
    for who in (UI, PLAIN):
        for phase in (BEFORE_MODEL, SETUP, MID_RUN):
            ROWS.append(stop_row(p, who, phase))

# model load fails
for p in ALL_PATHS:
    row = Row(
        p,
        fault="model_load",
        code=EXIT_ERROR,
        sessions=unchanged(p),
        out=(r"^\[.*\] - error: model load failed: .*weights download failed",),
        err=(r"^error: model load failed: .*weights download failed",),
    )
    if p in (GROUP, GROUP_REPLAY):  # group: the error: line only, the event line is missing
        row = dataclasses.replace(row, xfail=DRIFT_T9_MODEL)
    ROWS.append(row)

# the source cannot be opened (a missing file; the session's video gone; a file that is no video)
for p in ALL_PATHS:
    if p == GROUP:
        row = Row(
            p,
            fault="source_open",
            code=EXIT_OPEN,
            out=(r"^\[cam2\] error: cannot open source",),
        )
    else:
        row = Row(
            p,
            fault="source_open",
            code=EXIT_OPEN,
            sessions=unchanged(p),
            out=(r"^\[.*\] - source_open_failed: ",),
            err=(r"^error: cannot open source ",),
        )
    ROWS.append(row)

# an OpenCV error while a source opens (a backend that explodes)
for p in ALL_PATHS:
    if p in (GROUP, GROUP_REPLAY):  # pin today's generic failure; no decided replacement code
        ROWS.append(
            Row(
                p,
                fault="cv2_open",
                code=EXIT_ERROR,
                sessions=unchanged(p),
                err=(r"^error: the group .*backend exploded",),
            )
        )
    else:
        ROWS.append(
            Row(
                p,
                fault="cv2_open",
                code=EXIT_OPEN,
                sessions=unchanged(p),
                out=(r"^\[.*\] - source_open_failed: .*backend exploded",),
                err=(r"^error: cannot open source .*backend exploded",),
            )
        )

# an OpenCV error in the middle of the run (the decoder fails on the third read)
for p in ALL_PATHS:
    ROWS.append(
        Row(
            p,
            fault="cv2_run",
            code=EXIT_ERROR,
            sessions=sess(p, "error", ("error",)),
            out=(r"^\[.*\] \+[\d.]+s error: capture stopped: .*decoder exploded",),
        )
    )

# the detector fails (the shared detector's SharedCodeError in a group)
for p in ALL_PATHS:
    ROWS.append(
        Row(
            p,
            fault="detector",
            code=EXIT_ERROR,
            # a group: the processing error, then the group's own event, in each session
            sessions=sess(p, "error", ("error", "error") if p in IS_GROUP else ("error",)),
            out=(r"inference exploded",),
            err=(r"^error: the group (replay )?did not run",) if p in IS_GROUP else (),
        )
    )

# calibration refused
ROWS += [
    Row(  # refused at open: wrong size. Today fatal, no session
        SINGLE,
        fault="calibration_edge",
        code=EXIT_OK,
        sessions=sess(
            SINGLE, events=("error", "startup_check_failed"), checks=("calibration:failed",)
        ),
    ),
    Row(
        FILE_REPLAY,
        fault="calibration_edge",
        code=EXIT_OK,
        sessions=sess(
            FILE_REPLAY, events=("error", "startup_check_failed"), checks=("calibration:failed",)
        ),
    ),
    Row(
        SESSION_REPLAY,
        fault="calibration_edge",
        code=EXIT_OK,
        sessions=sess(
            SESSION_REPLAY, events=("error", "startup_check_failed"), checks=("calibration:failed",)
        ),
    ),
    Row(  # a group: uncalibrated with an event, but no failed check
        GROUP,
        fault="calibration_edge",
        code=EXIT_OK,
        sessions={
            **sess(GROUP),
            "cam1": Sess(
                "ended",
                ("appearance_only", "error", "startup_check_failed"),
                group=True,
                checks=("calibration:failed",),
                links=ALL_LINKS,
            ),
        },
    ),
    Row(  # the operator started it uncalibrated after Studio refused it (D-057)
        SINGLE,
        fault="calibration_operator",
        code=EXIT_OK,
        sessions=sess(SINGLE, events=("startup_check_failed",), checks=("calibration:failed",)),
        out=(r"^\[.*\] - startup_check_failed: calibration: operator refused",),
    ),
    Row(
        GROUP,
        fault="calibration_operator",
        code=EXIT_OK,
        sessions={
            **sess(GROUP),
            "cam1": Sess(
                "ended",
                ("appearance_only", "startup_check_failed"),
                group=True,
                checks=("calibration:failed",),
                links=ALL_LINKS,
            ),
        },
        out=(r"^\[cam1\] \[.*\] - startup_check_failed: calibration: operator refused",),
    ),
    Row(  # Studio's saved document was invalid: an error event, no check
        SINGLE,
        fault="calibration_problem",
        code=EXIT_OK,
        sessions=sess(SINGLE, events=("error",)),
        out=(r"^\[.*\] - error: calibration not used: file is corrupt",),
    ),
    Row(  # a usable calibration: positions, and the run says it was calibrated
        SINGLE,
        fault="calibration_ok",
        code=EXIT_OK,
        sessions=sess(SINGLE, calibrated=True),
    ),
    Row(  # --calibration on a replay of a session
        SESSION_REPLAY,
        fault="calibration_ok",
        code=EXIT_OK,
        sessions=sess(SESSION_REPLAY, calibrated=True),
    ),
    Row(  # no --calibration: the live run's one (decision 9)
        SESSION_REPLAY,
        fault="calibration_live",
        code=EXIT_OK,
        sessions=sess(SESSION_REPLAY, calibrated=True),
    ),
    Row(  # the saved homography is singular: cam1 replays uncalibrated, with an event (B5, #62)
        GROUP_REPLAY,
        fault="calibration_singular",
        code=EXIT_OK,
        sessions={
            **sess(GROUP_REPLAY),
            "cam1": Sess(
                "ended",
                ("error",),  # appearance_only too, but a replay keeps only error/interrupted
                checks=("calibration:failed",),
                runs=2,
                group=True,
                links=ALL_LINKS,
            ),
        },
    ),
]

# Pin the existing drift as well as the desired outcome. Otherwise an xfail at the first
# assertion could hide unrelated changes to the files or events on that same path.
for intended in tuple(ROWS):
    if not intended.xfail:
        continue
    label = f"{intended.label}-today" if intended.label else "today"
    today = dataclasses.replace(intended, label=label, xfail=None)
    if intended.fault == "model_load":
        today = dataclasses.replace(today, out=(), err=(r"^error: .*weights download failed",))
    elif intended.path == GROUP_REPLAY and intended.stop:
        today = dataclasses.replace(
            today, code=EXIT_STOPPED, sessions=sess(GROUP_REPLAY, "interrupted", ("interrupted",))
        )
    elif intended.fault == "calibration_edge":
        if intended.path == GROUP:
            today = dataclasses.replace(
                today,
                sessions={
                    **sess(GROUP),
                    "cam1": Sess(
                        "ended",
                        ("appearance_only", "error"),
                        group=True,
                        links=frozenset({"appearance", "unshared"}),
                    ),
                },
            )
        else:
            today = dataclasses.replace(
                today,
                code=EXIT_ERROR,
                sessions=unchanged(intended.path),
                err=(r"^error: calibration cannot be used:",),
            )
    elif intended.fault == "calibration_live":
        today = dataclasses.replace(today, sessions=sess(SESSION_REPLAY))
    elif intended.label == "group-of-one":
        today = dataclasses.replace(
            today,
            sessions={"cam1": Sess("ended", group=True)},
            out=lines_of(GROUP, "ended", ("cam1",)),
            absent=(r"^session:",),
        )
    elif intended.label == "single-camera-lines":
        today = dataclasses.replace(today, out=lines_of(GROUP, "ended"))
    elif intended.label == "benchmark":
        today = dataclasses.replace(today, out=lines_of(GROUP, "ended"), absent=(r"benchmark:",))
    else:
        raise AssertionError(f"No current-behaviour expectation for {intended.id}")
    ROWS.append(today)

# A requested stop prevents a later scripted fault from running. These rows pin that
# ordering without inventing precedence for truly simultaneous faults and interrupts.
# A mid-run stop can drain queued frames and still hit fail_at=4: that interaction has no
# decided outcome and is deliberately not modelled as a preempted detector failure.
for path in ALL_PATHS:
    for who in (UI, PLAIN):
        for phase in (BEFORE_MODEL, SETUP):
            ROWS.append(dataclasses.replace(stop_row(path, who, phase), fault="detector"))
        ROWS.append(dataclasses.replace(stop_row(path, who, BEFORE_MODEL), fault="model_load"))

# Calibration-focused and stop-drift rows must also announce each newly opened run.
# Existing replay fixtures alone do not imply this invocation opened a run.
ROWS = [
    dataclasses.replace(
        row, out=lines_of(row.path, next(iter(row.sessions.values())).status, row.sessions)
    )
    if not row.out and row.sessions and all(s.runs == RUNS[row.path] for s in row.sessions.values())
    else row
    for row in ROWS
]


def params():
    return [
        pytest.param(
            r,
            id=r.id,
            marks=[pytest.mark.xfail(strict=True, reason=r.xfail, raises=AssertionError)],
        )
        if r.xfail
        else pytest.param(r, id=r.id)
        for r in ROWS
    ]


# -- the harness -------------------------------------------------------------------------------


class RowDetector(EvenFrameDetector):
    """The fake detector, plus the two things a row does through it: fail, or ask for a stop
    from the processing thread (the run is then really mid-run: the main thread gets Ctrl+C)."""

    device = "cpu"

    def __init__(self, fail_at: int | None = None, stop_mid_run: bool = False):
        super().__init__(fail_at)
        self._stop_mid_run = stop_mid_run
        self.stop_acknowledged = threading.Event()

    def detect(self, frame):
        if self._stop_mid_run:
            self._stop_mid_run = False
            _thread.interrupt_main()
            # Keep the run alive until its public lifecycle acknowledges the interrupt;
            # a fixed sleep races the scheduler, especially under parallel test execution.
            if not self.stop_acknowledged.wait(5):
                raise RuntimeError("test harness: main thread did not acknowledge mid-run stop")
        return super().detect(frame)


def install(mp, detector, *, load_error: Exception | None = None, before_load=None) -> None:
    """Fake perception for every entry point: no torch, no weights."""

    def load(args, device):
        if before_load:
            before_load()
        if load_error:
            raise load_error
        return detector, OneTrackPerDetection()

    for module in (cli, group_cli, replay_group):
        mp.setattr(module, "resolve_device", lambda requested: ("cpu", None))
        mp.setattr(module, "load_perception", load)
    for module in (group_cli, replay_group):
        mp.setattr(module, "create_tracker", lambda args: OneTrackPerDetection())


def stop_request(mp, who: str) -> None:
    """The stop channel both mains build: Studio's (source "ui") or a plain one."""
    request = cli.StopRequest("ui" if who == UI else None)
    mp.setattr(cli, "StopRequest", lambda: request)
    mp.setattr(group_cli, "StopRequest", lambda: request)


def signal_after_first_session_opens(mp) -> None:
    """A real SIGINT, as the stdin watcher delivers, right after the first session opens."""
    original, calls = CameraPipeline.open_session, []

    def wrapper(self, *args, **kwargs):
        calls.append(1)
        result = original(self, *args, **kwargs)
        if len(calls) == 1:
            signal.raise_signal(signal.SIGINT)
        return result

    mp.setattr(CameraPipeline, "open_session", wrapper)


def short_clip(folder: Path, name: str, shift: int = 0) -> Path:
    frames = [clip_maker.scene(i + shift) for i in range(SHORT_FRAMES)]
    return clip_maker.write_clip(folder / name, frames)


def calibration_for(folder: Path, camera_id: str) -> Path:
    """Synthetic contract example adapted to the fixture clip, without importing other tests."""
    example = Path(__file__).parents[1] / "fixtures/contracts/calibration.example.json"
    doc = load(example)
    doc.update(camera_id=camera_id, image_size={"width": 640, "height": 360})
    path = folder / f"calibration_{camera_id}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def clips_pair(tmp_path_factory) -> tuple[Path, Path]:
    folder = tmp_path_factory.mktemp("short")
    return short_clip(folder, "a.mp4"), short_clip(folder, "b.mp4", shift=3)


def group_argv(clip_a, clip_b, out, first_extra=(), record=False) -> list[str]:
    def cam(cid, clip, extra=()):
        args = [f"--source={clip}", "--link=file", f"--camera-id={cid}", "--group-id=g1"]
        args += [f"--out={out}", *(() if record else ("--no-record",)), *extra]
        return json.dumps(args)

    return [cam("cam1", clip_a, first_extra), cam("cam2", clip_b)]


def single_argv(clip, out, extra=(), record=False) -> list[str]:
    args = ["--source", str(clip), "--link", "file", "--camera-id", "cam1", "--out", str(out)]
    return [*args, *(() if record else ("--no-record",)), *extra]


@pytest.fixture(scope="module")
def recorded(tmp_path_factory, clips_pair) -> dict[str, Path]:
    """Live runs recorded once through the entry points: a session, a calibrated session and a
    calibrated two-camera group. Each row copies the one it replays."""
    root = tmp_path_factory.mktemp("recorded")
    a, b = clips_pair
    calibrations = {cid: calibration_for(root, cid) for cid in ("cam1", "cam2")}
    with pytest.MonkeyPatch.context() as mp:
        install(mp, RowDetector())
        assert cli.main(single_argv(a, root / "session", record=True)) == 0
        calibrated = single_argv(
            a, root / "calibrated", ("--calibration", str(calibrations["cam1"])), True
        )
        assert cli.main(calibrated) == 0
        cams = [
            json.dumps(
                [
                    f"--source={clip}",
                    "--link=file",
                    f"--camera-id={cid}",
                    "--group-id=g1",
                    f"--out={root / 'group'}",
                    f"--calibration={calibrations[cid]}",
                ]
            )  # fmt: skip
            for cid, clip in (("cam1", a), ("cam2", b))
        ]
        assert group_cli.main(cams) == 0
    return {name: root / name for name in ("session", "calibrated", "group")}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def observe(out: Path) -> tuple[dict[str, Sess], dict[str, set[str]]]:
    """Every session folder under out: its Sess, and the link values apart (they are compared as
    a subset where timing decides them)."""
    found, links = {}, {}
    for folder in sorted(p for p in out.iterdir() if p.is_dir()) if out.is_dir() else []:
        session = load(folder / "session.json")
        run_dir = folder / "runs" / session["runs"][-1]
        run = load(run_dir / "run.json")
        # A session replay preserves session.status; finalization of its new run is visible
        # separately through ended_at and counts (run.json has no status field).
        assert run["ended_at"] is not None, run
        assert run["counts"] is not None, run
        with (run_dir / "tracks.csv").open(encoding="utf-8", newline="") as stream:
            values = frozenset(track["link"] for track in csv.DictReader(stream))
        cam = session["camera_id"] or "-"
        checks = run["checks"]
        found[cam] = Sess(
            session["status"],
            tuple(sorted(e["kind"] for e in session["events"])),
            len(session["runs"]),
            run["group"] is not None,
            run["calibration"] is not None,
            None if checks is None else tuple(f"{c['check']}:{c['result']}" for c in checks),
            values,
        )
        links[cam] = values
    return found, links


def prepare(row: Row, tmp_path: Path, clips_pair, recorded, mp) -> tuple[callable, Path]:
    """Copy what the row replays, apply its fault, and return (the entry point call, out)."""
    a, b = clips_pair
    out = tmp_path / "out"
    extra = list(row.extra)
    detector = RowDetector(
        fail_at=4 if row.fault == "detector" else None,
        stop_mid_run=bool(row.stop and row.stop[1] == MID_RUN),
    )
    if row.stop and row.stop[1] == MID_RUN:
        original_stop = CameraPipeline.stop

        def acknowledge_stop(self, *args, **kwargs):
            detector.stop_acknowledged.set()
            return original_stop(self, *args, **kwargs)

        mp.setattr(CameraPipeline, "stop", acknowledge_stop)
    p = row.path
    if p in (SESSION_REPLAY, GROUP_REPLAY):
        source = recorded["calibrated" if row.fault == "calibration_live" else "session"]
        shutil.copytree(recorded["group"] if p == GROUP_REPLAY else source, out)
    session_dir = (
        next((d for d in out.iterdir() if d.is_dir()), None) if p == SESSION_REPLAY else None
    )

    if row.fault == "source_open":
        if p == SINGLE:
            a = tmp_path / "missing.mp4"
        elif p == GROUP:
            b = tmp_path / "missing.mp4"
        elif p == FILE_REPLAY:
            a = tmp_path / "not_a_video.mp4"
            a.write_text("this is not a video", encoding="utf-8")
        else:  # a session's video that is gone (SESSION_REPLAY, or one camera of the group)
            folders = sorted(d for d in out.iterdir() if d.is_dir())
            (session_dir or folders[-1]).joinpath("video.mkv").unlink()
    if row.fault == "cv2_open":
        mp.setattr(
            FileSource, "open", lambda self: (_ for _ in ()).throw(cv2.error("backend exploded"))
        )
    if row.fault == "cv2_run":
        original = FileSource.read

        def read(self):
            self._reads = getattr(self, "_reads", 0) + 1
            if self._reads >= 3:
                raise cv2.error("decoder exploded")
            return original(self)

        mp.setattr(FileSource, "read", read)
    if row.fault in ("calibration_edge", "calibration_ok"):
        good = calibration_for(tmp_path, "cam1")
        if row.fault == "calibration_edge":  # made at 640x480, the clip is 640x360
            doc = load(good)
            doc["image_size"] = {"width": 640, "height": 480}
            good.write_text(json.dumps(doc), encoding="utf-8")
        extra += [f"--calibration={good}"] if p == GROUP else ["--calibration", str(good)]
    if row.fault == "calibration_operator":
        extra += ["--calibration-failed", "operator refused"]
    if row.fault == "calibration_problem":
        extra += ["--calibration-problem", "file is corrupt"]
    if row.fault == "calibration_singular":
        run_json = next(
            (out / next(d.name for d in out.iterdir() if d.name.startswith("cam1"))).glob(
                "runs/*/run.json"
            )
        )
        run = load(run_json)
        run["calibration"]["homography_image_to_court"] = [[1, 0, 0], [0, 0, 0], [0, 0, 0]]
        run_json.write_text(json.dumps(run), encoding="utf-8")

    error = RuntimeError("weights download failed") if row.fault == "model_load" else None
    before = None
    if row.stop and row.stop[1] == BEFORE_MODEL:
        before = lambda: signal.raise_signal(signal.SIGINT)  # noqa: E731
    install(mp, detector, load_error=error, before_load=before)
    if row.stop:
        stop_request(mp, row.stop[0])
        if row.stop[1] == SETUP:
            signal_after_first_session_opens(mp)

    if p == SINGLE:
        return lambda: cli.main(single_argv(a, out, extra)), out
    if p == GROUP:
        argv = group_argv(a, b, out, extra)
        if row.label.startswith("group-of-one"):
            argv = argv[:1]
        return lambda: group_cli.main(argv), out
    if p == SESSION_REPLAY:
        return lambda: cli.main(["--replay", str(session_dir), "--out", str(out), *extra]), out
    if p == FILE_REPLAY:
        return lambda: cli.main(["--replay", str(a), "--out", str(out), *extra]), out
    return lambda: cli.main(["--replay", "g1", "--out", str(out), *extra]), out


@pytest.mark.parametrize("row", params())
def test_run_path_today(row, tmp_path, clips_pair, recorded, monkeypatch, capsys):
    call, out = prepare(row, tmp_path, clips_pair, recorded, monkeypatch)
    capsys.readouterr()  # the recording's output is not this run's
    code = call()
    captured = capsys.readouterr()
    stdout, stderr = captured.out.splitlines(), captured.err.splitlines()
    report = f"\n--- stdout ---\n{captured.out}\n--- stderr ---\n{captured.err}"

    observed, links = observe(out)

    assert code == row.code, report
    assert {c: dataclasses.replace(s, links=frozenset()) for c, s in observed.items()} == {
        c: dataclasses.replace(s, links=frozenset()) for c, s in row.sessions.items()
    }, report
    exact = row.path not in IS_GROUP and row.stop is None and row.fault is None
    for cam, expected in row.sessions.items():
        assert links[cam] <= expected.links, f"{cam}: link values {links[cam]}"  # timing decides
        if exact:
            assert links[cam] == expected.links, f"{cam}: link values {links[cam]}"
        if row.stop is None and row.code == EXIT_OK:
            assert links[cam], f"{cam}: successful fixture run wrote no track links"
    for pattern in row.out:
        assert any(re.search(pattern, ln) for ln in stdout), f"no stdout line {pattern!r}{report}"
    for pattern in row.err:
        assert any(re.search(pattern, ln) for ln in stderr), f"no stderr line {pattern!r}{report}"
    for pattern in row.absent:
        assert not [ln for ln in stdout if re.search(pattern, ln)], f"{pattern!r}{report}"
    if row.path not in IS_GROUP:  # one camera: its lines carry no tag
        assert not [ln for ln in stdout if re.match(r"^\[cam\d\] ", ln)], report
    assert "Traceback" not in captured.err, report


def test_the_table_covers_each_stop_and_fault_on_every_path():
    cells = {(r.path, r.stop, r.fault) for r in ROWS}
    for p in ALL_PATHS:
        assert (p, None, None) in cells
        for who in (UI, PLAIN):
            for phase in (BEFORE_MODEL, SETUP, MID_RUN):
                assert (p, (who, phase), None) in cells
            for phase in (BEFORE_MODEL, SETUP):
                assert (p, (who, phase), "detector") in cells
            assert (p, (who, BEFORE_MODEL), "model_load") in cells
        for fault in ("model_load", "source_open", "cv2_open", "cv2_run", "detector"):
            assert (p, None, fault) in cells
        calibration = "calibration_singular" if p == GROUP_REPLAY else "calibration_edge"
        assert (p, None, calibration) in cells
    assert any(r.label == "group-of-one" for r in ROWS)
    assert any(r.label == "group-of-one-today" for r in ROWS)
    for row in ROWS:
        if row.xfail and not (row.stop and row.fault):
            assert any(
                candidate.path == row.path
                and candidate.stop == row.stop
                and candidate.fault == row.fault
                and candidate.label.endswith("today")
                and not candidate.xfail
                for candidate in ROWS
            ), f"{row.id}: intended drift has no current-behaviour companion"
    assert len({r.id for r in ROWS}) == len(ROWS)
