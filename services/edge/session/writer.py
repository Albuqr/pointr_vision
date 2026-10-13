"""File SessionWriter (PHASE_03, D-020): session.json, runs/<run_id>/run.json, frames.csv and
tracks.csv under <out>/<session_id>/ (DATA_CONTRACTS.md sections 1-5).

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
import sys
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from services.edge.capture.types import utc_now
from services.edge.perception.types import TrackObs
from services.edge.session.types import (
    FrameRecord,
    RunCounts,
    RunMeta,
    SessionEvent,
    SessionMeta,
)

CONTRACT_VERSION = "0.4.0"
FRAMES_COLUMNS = [
    "seq", "t_recv", "t_proc_start", "t_proc_end", "app_delay_ms",
    "n_detections", "n_tracks", "dropped_total",
]  # fmt: skip
TRACKS_COLUMNS = [
    "seq", "track_id", "x1", "y1", "x2", "y2", "confidence", "state", "athlete_id",
]  # fmt: skip
FLUSH_SECS = 0.5  # flush period; under the contract's "at least once per second"


def redact(ref: str) -> str:
    """Remove user:password@ from a URL, so credentials never reach the files."""
    parts = urlsplit(ref)
    if "@" not in parts.netloc:
        return ref
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


def device_id(out_dir: Path) -> str:
    """This device's UUIDv4, kept in <out>/device_id and created on first use."""
    path = Path(out_dir) / "device_id"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value:
            return value
    except (OSError, ValueError):
        pass
    value = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    return value


def _num(x: float | None, digits: int = 6) -> str:
    return "" if x is None else f"{x:.{digits}f}"


def _opt(x) -> str:
    return "" if x is None else str(x)


def write_json(path: Path, doc: dict) -> None:
    """Write via a temp file and replace, so readers never see a half-written file. Windows
    refuses the replace while another program (OneDrive, an editor) holds the file: retry."""
    tmp = path.with_name(path.name + ".tmp")
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
        self.status: str | None = None  # final status written by close()
        self._t0: float | None = None
        self._q: queue.Queue = queue.Queue(maxsize)
        self._backlog = False  # inside a writer_backlog episode (ends when the queue empties)
        self._lock = threading.Lock()  # JSON writes: writer thread or close() fallback
        # set when the thread ends, normally or not; waited on instead of join(), which a
        # Ctrl+C can corrupt
        self.done = threading.Event()
        self._thread = threading.Thread(target=self._run, name="writer", daemon=True)

    # -- producers (any thread) --------------------------------------------------------------

    def start(self, meta: SessionMeta, run: RunMeta) -> None:
        """Create the folders, write session.json and run.json (status running), start the
        thread. Raises OSError when the folder cannot be created; FileExistsError if it
        exists: a run never writes into another run's folder (A5)."""
        self.dir = self.out_dir / meta.session_id
        self._run_dir = self.dir / "runs" / run.run_id
        self._run_dir.mkdir(parents=True)
        src = meta.source
        self._session = {
            "contract_version": CONTRACT_VERSION,
            "session_id": meta.session_id,
            "device_id": meta.device_id,
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
                "path": "video.mp4" if meta.recording_enabled else None,
                "sha256": None,
                "locked": False,
            },
            "runs": [run.run_id],
            "events": [],
        }
        self._run_doc = {
            "contract_version": CONTRACT_VERSION,
            "run_id": run.run_id,
            "session_id": meta.session_id,
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
        }
        self._frames_f = open(self._run_dir / "frames.csv", "w", newline="", encoding="utf-8")
        self._tracks_f = open(self._run_dir / "tracks.csv", "w", newline="", encoding="utf-8")
        self._frames = csv.writer(self._frames_f)
        self._tracks = csv.writer(self._tracks_f)
        self._frames.writerow(FRAMES_COLUMNS)
        self._tracks.writerow(TRACKS_COLUMNS)
        self._flush()
        write_json(self.dir / "session.json", self._session)
        write_json(self._run_dir / "run.json", self._run_doc)
        self._thread.start()

    def set_t0(self, t0: float, t0_wall: str) -> None:
        self._t0 = t0
        self._put(("t0", t0_wall))

    def frame(self, rec: FrameRecord) -> None:
        self._put(("frame", rec))

    def tracks(self, seq: int, obs: list[TrackObs]) -> None:
        self._put(("tracks", seq, obs))

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
        if self.error is None and not self._running() and self._session["ended_at"]:
            self.status = self._session["status"]
            return
        # ponytail: the fallback writes JSON only; a writer stuck past join_timeout may still
        # rewrite session.json later with its own status.
        why = repr(self.error) if self.error else f"did not finish in {self.join_timeout} s"
        detail = f"session writer: {why}; {self.lost + self._q.qsize()} items not written"
        self._session["events"].append(
            asdict(SessionEvent(utc_now(), self._rel(), "error", detail))
        )
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
                        dirty = not self._snapshot(self.dir / "session.json", self._session)
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
                ]
            )
        elif kind == "tracks":
            _, seq, obs = item
            for o in obs:
                x1, y1, x2, y2 = o.xyxy
                self._tracks.writerow(
                    [seq, o.track_id, _num(x1, 2), _num(y1, 2), _num(x2, 2), _num(y2, 2),
                     _num(o.confidence, 4), _opt(o.state), ""]
                )  # fmt: skip
        elif kind == "event":
            self._session["events"].append(asdict(item[1]))
            return True
        elif kind == "t0":
            self._run_doc["t0_wall"] = item[1]
            self._snapshot(self._run_dir / "run.json", self._run_doc)  # also in the final write
        return False

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
        self._finish_json(status, counts, ended_at)

    def _finish_json(self, status: str, counts: RunCounts, ended_at: str) -> None:
        with self._lock:
            self._run_doc["ended_at"] = ended_at
            self._run_doc["counts"] = asdict(counts)
            write_json(self._run_dir / "run.json", self._run_doc)
            self._session["ended_at"] = ended_at
            self._session["status"] = status
            write_json(self.dir / "session.json", self._session)
