"""Record from several cameras at once: one Pointr process per camera (D-022).

    python scripts/run_cameras.py --config cams.json --out C:/pointr_sessions [--preview]

cams.json is a list of {"camera_id", "source", "link", "det_size"?, "preview"?,
"track_lost_secs"?, "track_activation"?, "track_min_frames"?}; see
docs/cameras.example.json. Every camera is its own session, started one at a time (each start
waits for the child's "session:" line), and all share one group_id. There is no fusion across
cameras. Every child output line is prefixed with [camera_id].

Ctrl+C here stops ALL children the way Ctrl+C stops one: the launcher writes "stop" to each
child's stdin and waits, so every session ends "interrupted" or "ended", never "running".
Killing a child is the last resort after --stop-timeout and is marked "killed" in the table.
A child that fails to start does not stop the others.
"""

import argparse
import csv
import ipaddress
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # run as a script, `services` must import without an install

from services.edge.perception.detector import DET_SIZE_MULTIPLE  # noqa: E402
from services.edge.reports.build import (  # noqa: E402
    TABLE_HEADER,
    build_report,
    run_dirs,
    table_row,
)
from services.edge.session.types import CAMERA_ID_RE  # noqa: E402
from services.edge.session.writer import mask_credentials, redact  # noqa: E402

LINKS = ("usb", "wifi", "builtin", "file")
KEYS = {
    "camera_id",
    "name",
    "source",
    "link",
    "det_size",
    "fps_cap",
    "enabled",
    "preview",
    "track_lost_secs",
    "track_activation",
    "track_min_frames",
}
DEFAULT_PORTS = {"http": 80, "https": 443, "rtsp": 554}
SESSION_PREFIX = "session: "  # printed by services.edge.main once the source has opened
FAILED_READS = re.compile(r"\bfailed_reads=(\d+)")
TAIL_LINES = 20  # last output lines of a child kept for the Studio error panel
OK_STATUSES = ("ended", "interrupted")


class ConfigError(Exception):
    """The config cannot be used; nothing has been started."""


@dataclass(frozen=True)
class Camera:
    camera_id: str
    source: str
    link: str
    det_size: int | None = None
    preview: bool | None = None  # None: follow --preview
    track_lost_secs: float | None = None
    track_activation: float | None = None
    track_min_frames: int | None = None
    http_preview_port: int | None = None
    calibration_path: str | None = None
    calibration_problem: str | None = None  # why a saved calibration was not used (one line)
    name: str | None = None
    fps_cap: float | None = None
    enabled: bool = True


def source_key(source: str) -> str:
    """What identifies the device behind a source: host and port of a URL (a phone serves one
    viewer, whatever the path), the index of a camera, else the text."""
    text = source.strip().lower()
    if text.isdigit():
        return f"camera {int(text)}"
    parts = urlsplit(text)
    if parts.scheme in DEFAULT_PORTS and parts.hostname:
        try:
            port = parts.port or DEFAULT_PORTS[parts.scheme]
        except ValueError:  # a bad port: compare the whole text
            return text
        return f"{parts.hostname}:{port}"
    return text


def absolute(source: str) -> str:
    """A file path becomes absolute here: the children run in the repo folder, not in ours."""
    if source.isdigit() or urlsplit(source).scheme in DEFAULT_PORTS:
        return source
    return str(Path(source).resolve())


def _validate_url(source: str, where: str) -> None:
    parts = urlsplit(source)
    if parts.scheme.lower() not in ("http", "https", "rtsp"):
        raise ConfigError(f"{where}: URL scheme must be http, https, or rtsp")
    try:
        host = parts.hostname
        _ = parts.port
    except ValueError as exc:
        raise ConfigError(f"{where}: URL is malformed") from exc
    if not host:
        raise ConfigError(f"{where}: URL must include a host")
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        raise ConfigError(f"{where}: loopback camera URLs are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (
        address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
    ):
        raise ConfigError(f"{where}: loopback and link-local camera URLs are not allowed")


def parse_config(data: object) -> list[Camera]:
    """The camera list from parsed JSON; ConfigError says which entry is wrong and why."""
    if not isinstance(data, list) or not data:
        raise ConfigError("the config must be a non-empty JSON list of cameras")
    cameras: list[Camera] = []
    for i, entry in enumerate(data):
        where = f"entry {i + 1}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: must be an object")
        if unknown := set(entry) - KEYS:
            raise ConfigError(f"{where}: unknown keys {sorted(unknown)}; allowed {sorted(KEYS)}")
        for key in ("camera_id", "source", "link"):
            if key not in entry:
                raise ConfigError(f"{where}: missing {key!r}")
        camera_id = entry["camera_id"]
        if not isinstance(camera_id, str) or not CAMERA_ID_RE.fullmatch(camera_id):
            raise ConfigError(f"{where}: camera_id must match {CAMERA_ID_RE.pattern}")
        where = f"camera {camera_id}"
        name = entry.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ConfigError(f"{where}: name must not be empty")
        source = entry["source"]
        if isinstance(source, int) and not isinstance(source, bool):
            source = str(source)  # 0 is as good as "0"
        if not isinstance(source, str) or not source.strip():
            raise ConfigError(f"{where}: source must be a camera index or a URL or path")
        source = source.strip()
        if "://" in source or source.lower().startswith(("http:", "https:", "rtsp:", "file:")):
            _validate_url(source, where)
        if entry["link"] not in LINKS:
            raise ConfigError(f"{where}: link must be one of {', '.join(LINKS)}")
        size = entry.get("det_size")
        if size is not None and (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size not in range(320, 1281, DET_SIZE_MULTIPLE)
        ):
            raise ConfigError(f"{where}: det_size must be an allowed size from 320 through 1280")
        fps_cap = entry.get("fps_cap")
        try:
            fps_valid = fps_cap is None or (
                not isinstance(fps_cap, bool)
                and isinstance(fps_cap, (int, float))
                and math.isfinite(float(fps_cap))
                and 0 < fps_cap <= 60
            )
        except OverflowError:
            fps_valid = False
        if not fps_valid:
            raise ConfigError(f"{where}: fps_cap must be greater than 0 and at most 60")
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{where}: enabled must be true or false")
        preview = entry.get("preview")
        if preview is not None and not isinstance(preview, bool):
            raise ConfigError(f"{where}: preview must be true or false")
        track_lost_secs = entry.get("track_lost_secs")
        if track_lost_secs is not None and (
            isinstance(track_lost_secs, bool)
            or not isinstance(track_lost_secs, (int, float))
            or not 0 < track_lost_secs < float("inf")
        ):
            raise ConfigError(f"{where}: track_lost_secs must be a finite number greater than 0")
        track_activation = entry.get("track_activation")
        if track_activation is not None and (
            isinstance(track_activation, bool)
            or not isinstance(track_activation, (int, float))
            or not 0 < track_activation <= 1
        ):
            raise ConfigError(f"{where}: track_activation must be a number in (0, 1]")
        track_min_frames = entry.get("track_min_frames")
        if track_min_frames is not None and (
            not isinstance(track_min_frames, int)
            or isinstance(track_min_frames, bool)
            or track_min_frames < 1
        ):
            raise ConfigError(f"{where}: track_min_frames must be a positive integer")
        cameras.append(
            Camera(
                camera_id,
                absolute(source.strip()),
                entry["link"],
                size,
                preview,
                track_lost_secs,
                track_activation,
                track_min_frames,
                name=name.strip() if name else None,
                fps_cap=fps_cap,
                enabled=enabled,
            )
        )
    for a in range(len(cameras)):
        for b in range(a):
            if cameras[a].camera_id == cameras[b].camera_id:
                raise ConfigError(f"camera_id {cameras[a].camera_id!r} is used twice")
            name_a = (cameras[a].name or cameras[a].camera_id).casefold()
            name_b = (cameras[b].name or cameras[b].camera_id).casefold()
            if name_a == name_b:
                raise ConfigError(f"camera name {name_a!r} is used twice")
            if source_key(cameras[a].source) == source_key(cameras[b].source):
                raise ConfigError(
                    f"{cameras[b].camera_id} and {cameras[a].camera_id} use the same source "
                    f"({redact(cameras[a].source)}): a phone serves ONE viewer, so a second reader "
                    "would fail"
                )
    return cameras


def load_config(path: Path) -> list[Camera]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    except ValueError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}") from e
    return parse_config(data)


@dataclass(frozen=True)
class Options:
    out: str
    group_id: str
    preview: bool = False
    device: str | None = None
    no_detect: bool = False


def child_command(cam: Camera, opts: Options) -> list[str]:
    """The command line of one camera's process: services.edge.main with its identity."""
    cmd = [
        sys.executable, "-u", "-m", "services.edge.main",
        f"--source={cam.source}", f"--link={cam.link}",
        f"--camera-id={cam.camera_id}", f"--group-id={opts.group_id}",
        f"--out={opts.out}", "--stop-on-stdin",
    ]  # fmt: skip
    if cam.det_size:
        cmd.append(f"--det-size={cam.det_size}")
    if cam.fps_cap is not None:
        cmd.append(f"--fps-cap={cam.fps_cap}")
    if cam.track_lost_secs is not None:
        cmd.append(f"--track-lost-secs={cam.track_lost_secs}")
    if cam.track_activation is not None:
        cmd.append(f"--track-activation={cam.track_activation}")
    if cam.track_min_frames is not None:
        cmd.append(f"--track-min-frames={cam.track_min_frames}")
    if cam.http_preview_port is not None:
        cmd.append(f"--http-preview={cam.http_preview_port}")
    if cam.calibration_path is not None:
        cmd.append(f"--calibration={cam.calibration_path}")
    if cam.calibration_problem:
        cmd.append(f"--calibration-problem={cam.calibration_problem}")
    if cam.preview if cam.preview is not None else opts.preview:
        cmd.append("--preview")
    if opts.device:
        cmd.append(f"--device={opts.device}")
    if opts.no_detect:
        cmd.append("--no-detect")
    return cmd


class Child:
    """One camera's process and what the launcher learned from its output."""

    def __init__(self, cam: Camera):
        self.cam = cam
        self.proc: subprocess.Popen | None = None
        self.reader: threading.Thread | None = None
        self.session_dir: Path | None = None  # from the "session:" line
        self.opened = threading.Event()  # that line was seen
        self.failed_reads = "-"
        self.failure: str | None = None  # why it never recorded
        self.tail: deque[str] = deque(maxlen=TAIL_LINES)  # last output lines, credentials masked
        self.killed = False
        self.stop_sent = False
        self.preview_port = cam.http_preview_port

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


class Launcher:
    def __init__(
        self,
        cameras: list[Camera],
        opts: Options,
        command=child_command,
        start_timeout: float = 180.0,
        stop_timeout: float = 45.0,
    ):
        self.cameras = cameras
        self.opts = opts
        self.command = command
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.children: list[Child] = []
        self._print = threading.Lock()  # lines from several readers must not interleave

    def say(self, text: str) -> None:
        with self._print:
            try:
                print(text, flush=True)
            except UnicodeEncodeError:  # a console code page that lacks a character of the line
                enc = sys.stdout.encoding or "ascii"
                print(text.encode(enc, "replace").decode(enc), flush=True)
            except OSError:  # our own stdout is gone: keep draining the child's pipe
                pass

    # -- start ---------------------------------------------------------------------------------

    def spawn(self, child: Child) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        # Windows: no console of its own and its own process group, so neither a console event
        # (Ctrl+C, Ctrl+Break, closing the window) nor the launcher's death kills a child: the
        # only way to stop one is its stdin, and a dead launcher closes it, which stops it too
        group = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
            if sys.platform == "win32"
            else {"start_new_session": True}
        )
        child.proc = subprocess.Popen(
            self.command(child.cam, self.opts),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=ROOT,
            env=env,
            **group,
        )
        child.reader = threading.Thread(target=self.read, args=(child,), daemon=True)
        child.reader.start()

    def read(self, child: Child) -> None:
        for raw in child.proc.stdout:
            line = raw.rstrip("\r\n")
            child.tail.append(mask_credentials(line))
            if line.startswith(SESSION_PREFIX):
                child.session_dir = Path(line[len(SESSION_PREFIX) :])
                child.opened.set()
            elif m := FAILED_READS.search(line):
                child.failed_reads = m.group(1)
            elif line.startswith("preview_port: "):
                try:
                    child.preview_port = int(line.split(":", 1)[1].strip())
                except ValueError:
                    child.failure = "invalid preview port reported"
            elif line.startswith("error: ") and child.failure is None:
                child.failure = mask_credentials(line.removeprefix("error: ").strip())
            # never raises: the pipe must be drained
            self.say(f"[{child.cam.camera_id}] {mask_credentials(line)}")

    def start_one(self, cam: Camera) -> None:
        """Start one camera and wait until its session exists, it exits, or the timeout."""
        child = Child(cam)
        self.children.append(child)
        try:
            self.spawn(child)
        except OSError as e:
            child.failure = mask_credentials(f"failed to start: {e}")
            self.say(f"[launcher] {cam.camera_id}: {child.failure}")
            return
        self.say(f"[launcher] starting {cam.camera_id} ({redact(cam.source)})")
        deadline = time.monotonic() + self.start_timeout
        while not child.opened.is_set():
            if not child.running:
                child.reader.join(5)  # the last lines, "session:" among them, may be in the pipe
                break
            if time.monotonic() > deadline:
                child.failure = f"failed: no session after {self.start_timeout:g} s"
                self.say(f"[launcher] {cam.camera_id}: {child.failure}; stopping it")
                self.stop([child])
                return
            child.opened.wait(0.2)
        if not child.opened.is_set():
            if child.failure is None:
                child.failure = f"failed to start (exit {child.proc.returncode})"
            self.say(f"[launcher] {cam.camera_id}: {child.failure}, the others go on")

    # -- stop ----------------------------------------------------------------------------------

    def stop(self, children: list[Child]) -> None:
        """Ask each running child to stop like Ctrl+C and wait for it; kill only after
        stop_timeout. Safe to call again after a Ctrl+C."""
        for child in children:
            if child.running and not child.stop_sent:
                child.stop_sent = True
                try:
                    child.proc.stdin.write("stop\n")
                    child.proc.stdin.flush()
                except OSError:  # it exited meanwhile
                    pass
        deadline = time.monotonic() + self.stop_timeout
        for child in children:
            while child.running:
                if time.monotonic() > deadline:
                    self.say(f"[launcher] {child.cam.camera_id} did not stop: killing it")
                    child.killed = True
                    kill_tree(child.proc)
                    break
                time.sleep(0.1)
            if child.reader:
                child.reader.join(5)
            if child.proc and child.proc.stdin:
                try:
                    child.proc.stdin.close()
                except OSError:
                    pass

    def stop_all(self, reason: str | None = None) -> None:
        """Stop every child. While it runs Ctrl+C and Ctrl+Break only print a reminder: the
        stop deadline is not restarted and nothing escapes before the table."""

        def remind(signum, frame):  # not self.say: that lock may be held by this very thread
            print("[launcher] stopping, please wait: the sessions are being saved", flush=True)

        saved = {}
        for name in ("SIGINT", "SIGBREAK"):
            if (sig := getattr(signal, name, None)) is not None:
                try:
                    saved[sig] = signal.signal(sig, remind)
                except ValueError:  # not the main thread
                    pass
        try:
            if reason:
                self.say(reason)
            self.stop(self.children)
        finally:
            for sig, handler in saved.items():
                signal.signal(sig, handler)

    # -- run -----------------------------------------------------------------------------------

    def run(self) -> int:
        self.say(
            f"[launcher] group {self.opts.group_id}: "
            + ", ".join(c.camera_id for c in self.cameras)
        )
        reason = None
        try:
            for cam in self.cameras:  # one at a time: first starts share device_id, RAM spikes
                self.start_one(cam)
            while any(c.running for c in self.children):
                time.sleep(0.2)
            reason = "[launcher] every camera has stopped"
        except KeyboardInterrupt:
            reason = "[launcher] Ctrl+C: stopping every camera"
        finally:
            self.stop_all(reason)
        rows = [self.summary(c) for c in self.children]
        started = {c.cam.camera_id for c in self.children}
        rows += [
            (c.camera_id, "-", "not started", "-", "-", "-")
            for c in self.cameras
            if c.camera_id not in started
        ]  # a Ctrl+C during the staggered start
        self.say(format_table(rows))
        if reports := self.report_rows():
            self.say(format_table(reports, REPORT_HEADER, "report (per camera, from the files):"))
        return 0 if all(r[2] in OK_STATUSES and r[5] in ("0", "-") for r in rows) else 1

    def report_rows(self) -> list[tuple[str, ...]]:
        """One row per camera that has a session: its report, built from its files."""
        rows = []
        for child in self.children:
            if child.session_dir is None:
                continue
            try:
                rows.append(table_row(build_report(run_dirs(child.session_dir)[-1])))
            except Exception as e:  # shown, never silent (CLAUDE.md rule 6)
                self.say(f"[launcher] {child.cam.camera_id}: report failed: {e!r}")
                rows.append((child.cam.camera_id, *["n/a"] * (len(REPORT_HEADER) - 1)))
        return rows

    def summary(self, child: Child) -> tuple[str, str, str, str, str, str]:
        """camera_id, session folder, final status, processed fps, failed reads, error events."""
        cam = child.cam.camera_id
        if child.session_dir is None:
            code = child.proc.returncode if child.proc else None
            return cam, "-", child.failure or f"failed (exit {code})", "-", "-", "-"
        status = session_status(child.session_dir)
        if child.killed:
            status += " (killed)"
        return (
            cam,
            child.session_dir.name,
            status,
            processed_fps(child.session_dir),
            child.failed_reads,
            error_events(child.session_dir),
        )


def kill_tree(proc: subprocess.Popen) -> None:
    """Last resort. On Windows a venv's python.exe is a stub that starts the real interpreter
    as its child: killing the stub alone would leave the camera recording, so kill the tree."""
    if sys.platform == "win32":
        # full path: Git Bash can lose PATH (CLAUDE.md); a failure still falls through to kill()
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run([str(taskkill), "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        except OSError:
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # started in its own session: pgid is its pid
        except OSError:
            pass
    proc.kill()  # the stub itself, if taskkill missed it
    proc.wait()


def error_events(session_dir: Path) -> str:
    """How many `error` events session.json holds (a thread that did not stop in time, a dead
    writer): a session can end `interrupted` and still have lost data."""
    try:
        doc = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        return str(sum(e["kind"] == "error" for e in doc["events"]))
    except (OSError, ValueError, KeyError):
        return "-"


def session_status(session_dir: Path) -> str:
    try:
        return json.loads((session_dir / "session.json").read_text(encoding="utf-8"))["status"]
    except (OSError, ValueError, KeyError):
        return "unknown"


def processed_fps(session_dir: Path) -> str:
    """Processed frames over first processing start to last end, as the benchmark computes it
    (loop.rates), from frames.csv; '-' when it cannot be computed."""
    try:
        [run_dir] = (session_dir / "runs").iterdir()
        with open(run_dir / "frames.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        span = float(rows[-1]["t_proc_end"]) - float(rows[0]["t_proc_start"])
        return f"{len(rows) / span:.2f}" if span > 0 else "-"
    except (OSError, ValueError, KeyError, IndexError):
        return "-"


RESULT_HEADER = (
    "camera_id", "session folder", "final status", "processed fps", "failed reads", "errors"
)  # fmt: skip
REPORT_HEADER = TABLE_HEADER


def format_table(
    rows: list[tuple[str, ...]], header: tuple[str, ...] = RESULT_HEADER, title: str = "result:"
) -> str:
    table = [header, *rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(header))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(r, widths, strict=True)) for r in table]
    return "\n".join(f"[launcher] {line}" for line in [title, *lines])


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python scripts/run_cameras.py", description=__doc__)
    p.add_argument(
        "--config", required=True, type=Path, help="cameras JSON (docs/cameras.example.json)"
    )
    p.add_argument("--out", default="sessions", help="folder for session data (default sessions)")
    p.add_argument("--preview", action="store_true", help="a preview window per camera")
    p.add_argument("--device", choices=["auto", "cpu", "cuda"], help="passed to every camera")
    p.add_argument("--no-detect", action="store_true", help="capture only, no detection")
    p.add_argument("--start-timeout", type=float, default=180.0, help="seconds to wait per camera")
    p.add_argument("--stop-timeout", type=float, default=45.0, help="seconds before a kill")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # a piped console must not choke on a line
        sys.stdout.reconfigure(errors="backslashreplace")
    try:
        cameras = load_config(args.config)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if hasattr(signal, "SIGBREAK"):  # Ctrl+Break in this console stops us like Ctrl+C
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    # closing the console window kills the launcher and every camera: sessions stay "running"
    opts = Options(
        str(Path(args.out).resolve()), str(uuid.uuid4()), args.preview, args.device, args.no_detect
    )
    return Launcher(
        cameras, opts, start_timeout=args.start_timeout, stop_timeout=args.stop_timeout
    ).run()


if __name__ == "__main__":
    sys.exit(main())
