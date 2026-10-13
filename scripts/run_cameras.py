"""Record from several cameras at once: one Pointr process per camera (D-022).

    python scripts/run_cameras.py --config cams.json --out C:/pointr_sessions [--preview]

cams.json is a list of {"camera_id", "source", "link", "det_size"?, "preview"?}; see
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
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # run as a script, `services` must import without an install

from services.edge.perception.detector import DET_SIZE_MULTIPLE  # noqa: E402
from services.edge.session.types import CAMERA_ID_RE  # noqa: E402

LINKS = ("usb", "wifi", "builtin", "file")
KEYS = {"camera_id", "source", "link", "det_size", "preview"}
DEFAULT_PORTS = {"http": 80, "https": 443, "rtsp": 554}
SESSION_PREFIX = "session: "  # printed by services.edge.main once the source has opened
FAILED_READS = re.compile(r"\bfailed_reads=(\d+)")
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
        source = entry["source"]
        if isinstance(source, int) and not isinstance(source, bool):
            source = str(source)  # 0 is as good as "0"
        if not isinstance(source, str) or not source.strip():
            raise ConfigError(f"{where}: source must be a camera index or a URL or path")
        if entry["link"] not in LINKS:
            raise ConfigError(f"{where}: link must be one of {', '.join(LINKS)}")
        size = entry.get("det_size")
        if size is not None and (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or size % DET_SIZE_MULTIPLE
        ):
            raise ConfigError(
                f"{where}: det_size must be a positive multiple of {DET_SIZE_MULTIPLE}"
            )
        preview = entry.get("preview")
        if preview is not None and not isinstance(preview, bool):
            raise ConfigError(f"{where}: preview must be true or false")
        cameras.append(Camera(camera_id, source.strip(), entry["link"], size, preview))
    for a in range(len(cameras)):
        for b in range(a):
            if cameras[a].camera_id == cameras[b].camera_id:
                raise ConfigError(f"camera_id {cameras[a].camera_id!r} is used twice")
            if source_key(cameras[a].source) == source_key(cameras[b].source):
                raise ConfigError(
                    f"{cameras[b].camera_id} and {cameras[a].camera_id} use the same source "
                    f"({cameras[a].source}): a phone serves ONE viewer, so a second reader "
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
        "--source", cam.source, "--link", cam.link,
        "--camera-id", cam.camera_id, "--group-id", opts.group_id,
        "--out", opts.out, "--stop-on-stdin",
    ]  # fmt: skip
    if cam.det_size:
        cmd += ["--det-size", str(cam.det_size)]
    if cam.preview if cam.preview is not None else opts.preview:
        cmd.append("--preview")
    if opts.device:
        cmd += ["--device", opts.device]
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
        self.killed = False
        self.stop_sent = False

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
            print(text, flush=True)

    # -- start ---------------------------------------------------------------------------------

    def spawn(self, child: Child) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        # own process group (session): the terminal's Ctrl+C reaches this launcher only, and
        # each child is stopped through one path, its stdin
        group = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
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
            if line.startswith(SESSION_PREFIX):
                child.session_dir = Path(line[len(SESSION_PREFIX) :])
                child.opened.set()
            elif m := FAILED_READS.search(line):
                child.failed_reads = m.group(1)
            self.say(f"[{child.cam.camera_id}] {line}")

    def start_one(self, cam: Camera) -> None:
        """Start one camera and wait until its session exists, it exits, or the timeout."""
        child = Child(cam)
        self.children.append(child)
        try:
            self.spawn(child)
        except OSError as e:
            child.failure = f"failed to start: {e}"
            self.say(f"[launcher] {cam.camera_id}: {child.failure}")
            return
        self.say(f"[launcher] starting {cam.camera_id} ({cam.source})")
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

    def stop_all(self) -> None:
        """Stop every child; a further Ctrl+C meanwhile only prints a reminder."""
        while True:
            try:
                self.stop(self.children)
                return
            except KeyboardInterrupt:
                self.say("[launcher] stopping, please wait: the sessions are being saved")

    # -- run -----------------------------------------------------------------------------------

    def run(self) -> int:
        self.say(
            f"[launcher] group {self.opts.group_id}: "
            + ", ".join(c.camera_id for c in self.cameras)
        )
        try:
            for cam in self.cameras:  # one at a time: first starts share device_id, RAM spikes
                self.start_one(cam)
            while any(c.running for c in self.children):
                time.sleep(0.2)
            self.say("[launcher] every camera has stopped")
        except KeyboardInterrupt:
            self.say("[launcher] Ctrl+C: stopping every camera")
        finally:
            self.stop_all()
        rows = [self.summary(c) for c in self.children]
        self.say(format_table(rows))
        return 0 if all(r[2] in OK_STATUSES for r in rows) else 1

    def summary(self, child: Child) -> tuple[str, str, str, str, str]:
        """camera_id, session folder, final status, processed fps, failed reads."""
        cam = child.cam.camera_id
        if child.session_dir is None:
            code = child.proc.returncode if child.proc else None
            return cam, "-", child.failure or f"failed (exit {code})", "-", "-"
        status = session_status(child.session_dir)
        if child.killed:
            status += " (killed)"
        return (
            cam,
            child.session_dir.name,
            status,
            processed_fps(child.session_dir),
            child.failed_reads,
        )


def kill_tree(proc: subprocess.Popen) -> None:
    """Last resort. On Windows a venv's python.exe is a stub that starts the real interpreter
    as its child: killing the stub alone would leave the camera recording, so kill the tree."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # started in its own session: pgid is its pid
        except OSError:
            pass
    proc.kill()  # the stub itself, if taskkill missed it
    proc.wait()


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


def format_table(rows: list[tuple[str, ...]]) -> str:
    header = ("camera_id", "session folder", "final status", "processed fps", "failed reads")
    table = [header, *rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(header))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(r, widths, strict=True)) for r in table]
    return "\n".join(f"[launcher] {line}" for line in ["result:", *lines])


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
    try:
        cameras = load_config(args.config)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if hasattr(signal, "SIGBREAK"):  # Ctrl+Break and a closing console window: same as Ctrl+C
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    opts = Options(args.out, str(uuid.uuid4()), args.preview, args.device, args.no_detect)
    return Launcher(
        cameras, opts, start_timeout=args.start_timeout, stop_timeout=args.stop_timeout
    ).run()


if __name__ == "__main__":
    sys.exit(main())
