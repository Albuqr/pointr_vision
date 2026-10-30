"""File SessionWriter (PHASE_03, D-020): session.json, runs/<run_id>/run.json, frames.csv and
tracks.csv under <out>/<folder>/ (DATA_CONTRACTS.md sections 1-5).

One writer thread owns every file handle; the capture, processing and main threads only put
on a bounded queue. At least once per second the CSVs are flushed and session.json is
rewritten (temp file + replace), so a crash leaves readable CSVs and a valid session.json.
close() hands the final status to the writer thread and waits for it, so a second Ctrl+C in
the main thread cannot cut the final write short.
"""

import csv
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from services.edge.capture.types import utc_now
from services.edge.contract import CONTRACT_VERSION, UNSHARED, VIDEO_FILE
from services.edge.perception.types import TrackObs
from services.edge.session.folder import read_session_for_update
from services.edge.session.types import (
    CAMERA_ID_RE,
    GROUP_ID_RE,
    FrameRecord,
    PositionMap,
    RunCounts,
    RunMeta,
    SessionEvent,
    SessionMeta,
)

FRAMES_COLUMNS = [
    "seq", "t_recv", "t_proc_start", "t_proc_end", "app_delay_ms",
    "n_detections", "n_tracks", "dropped_total", "t_video",
]  # fmt: skip
TRACKS_COLUMNS = [
    "seq", "track_id", "x1", "y1", "x2", "y2", "confidence", "state", "athlete_id",
    "player_number", "id_source", "link", "x_m", "y_m", "calibration_id", "position_method",
    "in_court",
]  # fmt: skip
# a row says how its track was linked (TrackObs.link, 0.14.0, D-051); UNSHARED when it could not be
READY_STEPS = ("model_loaded", "first_frame", "first_preview")  # run.json ready (0.15.0, D-052)
FLUSH_SECS = 0.5  # flush period; under the contract's "at least once per second"
METHOD = "box_bottom_center"
UNPROJECTED_EVENT_SECS = 30.0  # at most one "no metre position" event per this many seconds


def redact(ref: str) -> str:
    """Remove user:password@ from a URL, so credentials never reach the files."""
    parts = urlsplit(ref)
    if "@" not in parts.netloc:
        return ref
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


_USERINFO = re.compile(r"(?<=://)[^/\s@]+@")
_SECRET_PARAM = re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)=[^&\s]+")


def mask_credentials(text: str) -> str:
    """Hide credentials in free text (an error message, a stderr line): user:password@ in any
    URL and secret-looking query parameters. `redact` is for one URL going into a file."""
    return _SECRET_PARAM.sub(r"\1=***", _USERINFO.sub("***@", text))


def _read_device_id(path: Path) -> str | None:
    """The UUIDv4 in the file, or None if it is missing or not a UUIDv4. OSError (a lock held
    by OneDrive or an antivirus) propagates: that is not a reason to change the id."""
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        return value if uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value else None
    except ValueError:
        return None


def device_id(out_dir: Path) -> str:
    """This device's UUIDv4, kept in <out>/device_id and created on first use.

    Several processes may start together on a fresh folder (one per camera): the file is
    created exclusively, and the process that loses the race reads the winner's value. The
    winner writes after creating, so a reader may see the file empty for a moment: it retries."""
    path = Path(out_dir) / "device_id"
    path.parent.mkdir(parents=True, exist_ok=True)
    locked: OSError | None = None
    for _ in range(40):  # 2 s: the winner's write takes microseconds
        try:
            if (value := _read_device_id(path)) is not None:
                return value
            locked = None
        except OSError as e:  # unreadable for now: wait, never overwrite what we cannot read
            locked = e
            time.sleep(0.05)
            continue
        try:
            with open(path, "x", encoding="utf-8") as f:
                value = str(uuid.uuid4())
                f.write(value + "\n")
            return value
        except FileExistsError:
            time.sleep(0.05)  # another process won: read its value on the next turn
    if locked is not None:
        raise locked
    # present but never valid (corrupt, or its creator died mid-write): replace it, and say so
    print(f"warning: {path} is not a valid device id; replacing it", file=sys.stderr)
    value = str(uuid.uuid4())
    tmp = path.with_name(f"device_id.{os.getpid()}.tmp")
    tmp.write_text(value + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return value


def _num(x: float | None, digits: int = 6) -> str:
    return "" if x is None or x == "" else f"{x:.{digits}f}"


def _opt(x) -> str:
    return "" if x is None else str(x)


def write_json(path: Path, doc: dict) -> None:
    """Write via a temp file and replace, so readers never see a half-written file. Windows
    refuses the replace while another program (OneDrive, an editor) holds the file: retry."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # per process: replays can overlap
    text = json.dumps(doc, indent=2) + "\n"
    for attempt in range(20):
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


class FileSessionWriter:
    """Implements SessionWriter. Producer methods never raise: if the writer thread has died,
    items are counted in `lost` and the failure is recorded when the session closes."""

    def __init__(self, out_dir: Path | str, maxsize: int = 4096, join_timeout: float = 15.0):
        self.out_dir = Path(out_dir)
        self.join_timeout = join_timeout
        self.dir: Path | None = None  # <out>/<session_id>, set by start()
        self.error: BaseException | None = None  # why the writer thread stopped, if it failed
        self.lost = 0  # items put after the writer thread stopped
        self.unprojected = 0  # track rows written without a metre position
        self._reported_unprojected = 0
        self._last_unprojected_event: float | None = None
        self._positions: PositionMap | None = None
        self.status: str | None = None  # final status written by close()
        self._replay = False  # a replay adds a run and leaves the rest of session.json alone
        self._replay_events: list[dict] = []  # the only events a replay adds to session.json
        self._t0: float | None = None
        self._final: dict = {}
        self._q: queue.Queue = queue.Queue(maxsize)
        self._backlog = False  # inside a writer_backlog episode (ends when the queue empties)
        self._lock = threading.Lock()  # JSON writes: writer thread or close() fallback
        # set when the thread ends, normally or not; waited on instead of join(), which a
        # Ctrl+C can corrupt
        self.done = threading.Event()
        self._thread = threading.Thread(target=self._run, name="writer", daemon=True)

    # -- producers (any thread) --------------------------------------------------------------

    def start(self, meta: SessionMeta, run: RunMeta, positions: PositionMap | None = None) -> None:
        """Create the folders, write session.json and run.json (status running), start the
        thread. Raises OSError when the folder cannot be created; FileExistsError if it
        exists: a run never writes into another run's folder (A5). `positions` projects the
        rows of a calibrated run and is required exactly when run.calibration is set."""
        if (positions is None) != (run.calibration is None):
            raise ValueError("a calibrated run needs positions, and positions need a calibration")
        self._positions = positions
        # ids reach a folder name: refuse anything that is not a plain token (D-022)
        if meta.camera_id is not None and not CAMERA_ID_RE.fullmatch(meta.camera_id):
            raise ValueError(f"invalid camera_id {meta.camera_id!r}")
        if meta.group_id is not None and not GROUP_ID_RE.fullmatch(meta.group_id):
            raise ValueError(f"invalid group_id {meta.group_id!r}")
        folder = f"{meta.camera_id}_{meta.session_id}" if meta.camera_id else meta.session_id
        self.dir = self.out_dir / folder
        src = meta.source
        self._session = {
            "contract_version": CONTRACT_VERSION,
            "session_id": meta.session_id,
            "device_id": meta.device_id,
            "camera_id": meta.camera_id,
            "group_id": meta.group_id,
            "started_at": meta.started_at,
            "ended_at": None,
            "status": "running",
            "source": {
                "kind": src.kind,
                "ref": redact(src.ref),
                "width": src.width,
                "height": src.height,
                "reported_fps": src.reported_fps,
                "link": src.link,
            },
            "registration": None,
            "recording": {
                "enabled": meta.recording_enabled,
                "path": VIDEO_FILE if meta.recording_enabled else None,
                "sha256": None,
                "locked": False,
            },
            "runs": [run.run_id],
            "events": [],
            "calibration": meta.calibration,
        }
        self._begin_run(run)

    def start_run(
        self, session_dir: Path | str, run: RunMeta, positions: PositionMap | None = None
    ) -> None:
        """A replay: add `run` to the session already in session_dir. In session.json only `runs`
        grows; the session's status and recording stay as the live run left them. The replay adds
        no events except an `interrupted` or `error` one, tagged with its run id, so a replay that
        did not end cleanly is visible (D-042)."""
        if (positions is None) != (run.calibration is None):
            raise ValueError("a calibrated run needs positions, and positions need a calibration")
        self._positions = positions
        self.dir = Path(session_dir)
        self._session = read_session_for_update(self.dir)
        self._session["runs"].append(run.run_id)
        self._replay = True
        self._begin_run(run)

    def _begin_run(self, run: RunMeta) -> None:
        """Create the run folder and its files, write session.json and run.json, start the
        thread. FileExistsError if the run folder exists (A5)."""
        self._run_dir = self.dir / "runs" / run.run_id
        self._run_dir.mkdir(parents=True)
        self._run_doc = {
            "contract_version": CONTRACT_VERSION,
            "run_id": run.run_id,
            "session_id": self._session["session_id"],
            "mode": run.mode,
            "input": {**run.input, "ref": redact(run.input["ref"])},
            "detector": run.detector,
            "tracker": run.tracker,
            "health": run.health,
            "runtime": run.runtime,
            "started_at": run.started_at,
            "t0_wall": None,
            "ended_at": None,
            "counts": None,
            "calibration": run.calibration,
            "t0_mono": None,
            "checks": run.checks,
            "clock": run.clock,
            "objects": run.objects,
            "gaps": run.gaps,
            "outages": run.outages,
            "group": run.group,
            "ready": {**dict.fromkeys(READY_STEPS), **(run.ready or {})},
            "power": {"start": run.power_start, "end": None},  # 0.16.0, D-053
        }
        self._frames_f = open(self._run_dir / "frames.csv", "w", newline="", encoding="utf-8")
        self._tracks_f = open(self._run_dir / "tracks.csv", "w", newline="", encoding="utf-8")
        self._frames = csv.writer(self._frames_f)
        self._tracks = csv.writer(self._tracks_f)
        self._frames.writerow(FRAMES_COLUMNS)
        self._tracks.writerow(TRACKS_COLUMNS)
        self._flush()
        write_json(self.dir / "session.json", self._session_doc())
        write_json(self._run_dir / "run.json", self._run_doc)
        self._thread.start()

    @property
    def run_dir(self) -> Path:
        """runs/<run_id>/ of this session, once start() has run."""
        return self._run_dir

    def set_t0(self, t0: float, t0_wall: str) -> None:
        self._t0 = t0
        self._put(("t0", t0_wall, t0))

    def set_final(self, **blocks) -> None:
        """Run.json blocks known only at the end (gaps, outages, clock, power_end); call before
        close()."""
        unknown = set(blocks) - {"gaps", "outages", "clock", "power_end"}
        if unknown:
            raise ValueError(f"unknown run.json blocks: {sorted(unknown)}")
        if self.status is not None:
            raise RuntimeError("set_final after close()")
        with self._lock:
            self._final.update(blocks)

    def set_ready(self, step: str, t_wall: str, t_pc: float) -> None:
        """A step of run.json `ready` happened (D-052). Saved with the run's next snapshot, so a
        run stopped early keeps the steps it reached; the first call for a step wins."""
        if step not in READY_STEPS:
            raise ValueError(f"unknown ready step: {step!r}")
        self._put(("ready", step, t_wall, t_pc))

    def set_recording_sha256(self, sha256: str) -> None:
        """The sha256 of the session video, once the recorder has stopped; call before close()."""
        if self.status is not None:
            raise RuntimeError("set_recording_sha256 after close()")
        with self._lock:
            self._session["recording"]["sha256"] = sha256

    def frame(self, rec: FrameRecord) -> None:
        self._put(("frame", rec))

    def tracks(self, seq: int, obs: list[TrackObs], no_positions: str | None = None) -> None:
        """no_positions: why these rows get no metre position (the caller knows the frame, e.g.
        its size no longer matches the calibration); the rows are written all the same."""
        self._put(("tracks", seq, obs, no_positions))

    def event(self, ev: SessionEvent) -> None:
        self._put(("event", ev))

    def close(self, status: str, counts: RunCounts) -> None:
        """Write the final status, end time and counts, and stop the thread. Safe to call
        again after a KeyboardInterrupt. If the writer thread failed or does not finish in
        join_timeout, the JSON files are written from this thread with status error."""
        if self.status is not None:
            return
        ended_at = utc_now()
        if self._running():
            self._put(("close", status, counts, ended_at))
        deadline = time.perf_counter() + self.join_timeout
        while self._running() and time.perf_counter() < deadline:
            try:
                self.done.wait(0.1)
            except KeyboardInterrupt:  # a second Ctrl+C must not cut the final write short
                pass
        if (
            self.error is None
            and not self._running()
            and (self._replay or self._session["ended_at"])
        ):
            self.status = status if self._replay else self._session["status"]
            return
        # ponytail: the fallback writes JSON only; a writer stuck past join_timeout may still
        # rewrite session.json later with its own status.
        why = repr(self.error) if self.error else f"did not finish in {self.join_timeout} s"
        detail = f"session writer: {why}; {self.lost + self._q.qsize()} items not written"
        self._add_event(SessionEvent(utc_now(), self._rel(), "error", detail))
        self._finish_json("error", counts, ended_at)
        self.status = "error"

    def _running(self) -> bool:
        return self._thread.is_alive() and not self.done.is_set()

    def _put(self, item) -> None:
        if not self._running():
            self.lost += 1
            return
        try:
            self._q.put_nowait(item)
            return
        except queue.Full:
            pass
        first, self._backlog = not self._backlog, True
        # wait rather than drop rows: the producer slows, capture drops frames and counts them
        if not self._put_wait(item):
            return
        if first:
            detail = f"write queue full ({self._q.maxsize} items); producers waited"
            self._put_wait(
                ("event", SessionEvent(utc_now(), self._rel(), "writer_backlog", detail))
            )

    def _put_wait(self, item) -> bool:
        while True:
            try:
                self._q.put(item, timeout=0.5)
                return True
            except queue.Full:
                if not self._running():
                    self.lost += 1
                    return False

    def _rel(self) -> float | None:
        return None if self._t0 is None else time.perf_counter() - self._t0

    # -- writer thread -----------------------------------------------------------------------

    def _run(self) -> None:
        last = time.perf_counter()
        dirty = False  # session.json has events not on disk yet
        try:
            while True:
                try:
                    item = self._q.get(timeout=FLUSH_SECS)
                except queue.Empty:
                    item = None
                if item is not None:
                    if item[0] == "close":
                        self._finish(*item[1:])
                        return
                    dirty |= self._handle(item)
                if self._q.empty():
                    self._backlog = False
                if time.perf_counter() - last >= FLUSH_SECS:
                    self._flush()
                    if dirty:
                        dirty = not self._snapshot(self.dir / "session.json", self._session_doc())
                    last = time.perf_counter()
        except BaseException as e:  # disk full, permissions: recorded by close()
            self.error = e
            print(f"error: session writer stopped, data is no longer saved: {e!r}", file=sys.stderr)
        finally:
            for f in (self._frames_f, self._tracks_f):
                try:
                    f.close()
                except OSError:
                    pass
            self.done.set()

    def _handle(self, item) -> bool:
        """Write one item; True when session.json changed."""
        kind = item[0]
        if kind == "frame":
            r: FrameRecord = item[1]
            self._frames.writerow(
                [
                    r.seq,
                    _num(r.t_recv),
                    _num(r.t_proc_start),
                    _num(r.t_proc_end),
                    _num(r.app_delay_ms, 3),
                    _opt(r.n_detections),
                    _opt(r.n_tracks),
                    r.dropped_total,
                    _num(r.t_video),
                ]
            )
        elif kind == "tracks":
            _, seq, obs, no_positions = item
            changed = False
            for o in obs:
                try:
                    box = tuple(float(value) for value in o.xyxy)
                    if len(box) != 4:
                        raise ValueError("track box must have four coordinates")
                    x1, y1, x2, y2 = box
                    x_m, y_m, calibration_id, position_method, in_court, why = self._position(
                        (x1 + x2) / 2, y2, no_positions
                    )
                    if why:
                        changed |= self._note_unprojected(why)
                    row = [
                        seq, o.track_id, _num(x1, 2), _num(y1, 2), _num(x2, 2), _num(y2, 2),
                        _num(o.confidence, 4), _opt(o.state), "", "", "", o.link,
                        _num(x_m, 4), _num(y_m, 4),
                        calibration_id, position_method, in_court,
                    ]  # fmt: skip
                except Exception as e:  # a bad track row is recorded as empty, never fatal
                    changed |= self._note_unprojected(f"track row error: {e!r}")
                    try:
                        track_id = o.track_id
                    except Exception:
                        track_id = ""
                    row = [
                        seq, track_id, "", "", "", "", "", "", "", "", "", UNSHARED, "", "",
                        self._calibration_id(), METHOD if self._positions else "", "",
                    ]  # fmt: skip
                self._tracks.writerow(row)
            return changed
        elif kind == "event":
            return self._add_event(item[1])
        elif kind == "ready":
            _, step, t_wall, t_pc = item
            if self._run_doc["ready"][step] is None:
                self._run_doc["ready"][step] = {"t_wall": t_wall, "t_pc": t_pc}
                self._snapshot(self._run_dir / "run.json", self._run_doc)
        elif kind == "t0":
            self._run_doc["t0_wall"] = item[1]
            self._run_doc["t0_mono"] = item[2]
            self._snapshot(self._run_dir / "run.json", self._run_doc)  # also in the final write
        return False

    def _position(self, x: float, y: float, no_positions: str | None = None) -> tuple:
        """The five position cells of one row and why the position is empty (or None). Nothing
        a projection does can stop the writer: an error leaves the position empty."""
        positions = self._positions
        if positions is None:
            return "", "", "", "", "", None
        if no_positions:
            return "", "", self._calibration_id(), METHOD, "", no_positions
        try:
            xy = positions(x, y)
            if xy is None:
                return "", "", self._calibration_id(), METHOD, "", "outside the camera's view"
            in_court = str(bool(positions.in_court(*xy))).lower()
            return xy[0], xy[1], self._calibration_id(), METHOD, in_court, None
        except Exception as e:  # a projection failure is a missing position, not a dead run
            return "", "", self._calibration_id(), METHOD, "", repr(e)

    def _calibration_id(self) -> str:
        try:
            return getattr(self._positions, "calibration_id", "") or ""
        except Exception:
            return ""

    def _note_unprojected(self, why: str) -> bool:
        """Count a row without a position; one event on the first, then at most one per
        UNPROJECTED_EVENT_SECS. True when session.json changed."""
        self.unprojected += 1
        now = time.monotonic()
        if self._last_unprojected_event is not None and (
            now - self._last_unprojected_event < UNPROJECTED_EVENT_SECS
        ):
            return False
        self._append_unprojected_event(why)
        return True

    def _append_unprojected_event(self, why: str) -> None:
        self._last_unprojected_event = time.monotonic()
        self._reported_unprojected = self.unprojected
        detail = (
            f"{self.unprojected} track row(s) so far have no metre position ({why}); "
            "x_m, y_m and in_court are left empty"
        )
        self._add_event(SessionEvent(utc_now(), self._rel(), "error", detail))

    def _add_event(self, ev: SessionEvent) -> bool:
        """Append to session.json events; True when session.json changed. A replay keeps only
        its interrupted and error events, tagged with its run id."""
        if self._replay:
            if ev.kind not in ("interrupted", "error"):
                return False
            detail = f"replay {self._run_doc['run_id']}: {ev.detail}"
            self._replay_events.append(asdict(replace(ev, detail=detail)))
            return True
        self._session["events"].append(asdict(ev))
        return True

    def _session_doc(self) -> dict:
        """The session.json to write. A replay re-reads the file first, so a run another process
        added meanwhile is kept (ponytail: a read-merge-write, not a lock; two writers can still
        collide within the same few milliseconds)."""
        if not self._replay:
            return self._session
        doc = read_session_for_update(self.dir)
        run_id = self._run_doc["run_id"]
        if run_id not in doc["runs"]:
            doc["runs"].append(run_id)
        doc["events"] = [e for e in doc["events"] if e not in self._replay_events]
        doc["events"].extend(self._replay_events)
        return doc

    def _snapshot(self, path: Path, doc: dict) -> bool:
        """A mid-run JSON write. A failure (file held by OneDrive or an editor) is printed and
        retried on the next tick; it must not stop the CSV rows. True when written."""
        try:
            with self._lock:
                write_json(path, doc)
            return True
        except OSError as e:
            print(f"warning: {path.name} not updated yet, will retry: {e!r}", file=sys.stderr)
            return False

    def _flush(self) -> None:
        # ponytail: flush, no fsync: survives a process crash, not a power cut
        self._frames_f.flush()
        self._tracks_f.flush()

    def _finish(self, status: str, counts: RunCounts, ended_at: str) -> None:
        self._frames_f.close()  # CSVs complete before the status says the run ended
        self._tracks_f.close()
        if self.unprojected > self._reported_unprojected:  # the rate limit hid the final count
            self._append_unprojected_event("final count for the run")
        self._finish_json(status, counts, ended_at)

    def _finish_json(self, status: str, counts: RunCounts, ended_at: str) -> None:
        with self._lock:
            final = dict(self._final)
            if "power_end" in final:
                self._run_doc["power"] = {**self._run_doc["power"], "end": final.pop("power_end")}
            self._run_doc.update(final)
            self._run_doc["ended_at"] = ended_at
            self._run_doc["counts"] = asdict(counts)
            write_json(self._run_dir / "run.json", self._run_doc)
            if self._replay:
                if status != "ended" and not self._replay_events:
                    kind = "interrupted" if status == "interrupted" else "error"
                    self._add_event(SessionEvent(utc_now(), None, kind, f"ended with {status}"))
            else:
                self._session["ended_at"] = ended_at
                self._session["status"] = status
            write_json(self.dir / "session.json", self._session_doc())
