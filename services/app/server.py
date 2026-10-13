import base64
import csv
import datetime as dt
import ipaddress
import json
import socket
import threading
import time
import urllib.request
import uuid
import webbrowser
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from services.app.config import CameraConfig
from services.edge.capture.sources import SourceOpenError, open_source
from services.edge.capture.types import SourceEnded
from services.edge.launcher import Camera, ConfigError, Launcher, Options, parse_config
from services.edge.reports.build import build_report, format_summary, run_dirs

ROOT = Path(__file__).resolve().parents[2]
UI_DIST = Path(__file__).parent / "ui" / "dist"
FRAME_COLUMNS = (
    "seq",
    "t_recv",
    "t_proc_start",
    "t_proc_end",
    "app_delay_ms",
    "n_detections",
    "n_tracks",
    "dropped_total",
)


class Studio:
    def __init__(self, out: str, config=None, launcher_factory=Launcher):
        self.out = str(Path(out).resolve())
        self.config = config or CameraConfig()
        self.launcher_factory = launcher_factory
        self.launcher = None
        self.worker = None
        self.group_id = None
        self.preview_ports: dict[str, int] = {}
        self.lock = threading.RLock()
        self.final: dict[str, dict] = {}
        self.frame_cache = {}

    def entries(self):
        return self.config.read()

    def save(self, entries):
        try:
            if entries:
                parse_config(entries)
            self.config.write(entries)
        except ConfigError as exc:
            raise HTTPException(422, str(exc)) from exc

    def recording(self):
        return bool(self.worker and self.worker.is_alive())

    def start(self):
        with self.lock:
            if self.recording():
                raise HTTPException(409, "recording is already active")
            entries = self.entries()
            if not entries:
                raise HTTPException(422, "add at least one camera")
            cameras = parse_config(entries)
            self.group_id = str(uuid.uuid4())
            self.final = {}
            self.preview_ports = {}
            for camera in cameras:
                port = self.free_port()
                while port in self.preview_ports.values():
                    port = self.free_port()
                self.preview_ports[camera.camera_id] = port
            cameras = [
                Camera(
                    camera.camera_id,
                    camera.source,
                    camera.link,
                    camera.det_size,
                    camera.preview,
                    camera.track_lost_secs,
                    camera.track_activation,
                    camera.track_min_frames,
                    self.preview_ports[camera.camera_id],
                )
                for camera in cameras
            ]
            opts = Options(self.out, self.group_id)
            self.launcher = self.launcher_factory(cameras, opts)
            self.worker = threading.Thread(
                target=self.launcher.run, name="studio-launcher", daemon=True
            )
            self.worker.start()
        return self.status()

    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def stop(self):
        with self.lock:
            launcher = self.launcher
            worker = self.worker
        if worker and worker.is_alive():
            launcher.stop_all("[app] stop requested")
            worker.join(timeout=50)
        return self.status()

    def status(self):
        with self.lock:
            launcher = self.launcher
            ports = dict(self.preview_ports)
            active = self.recording()
            finals = dict(self.final)
        cameras = []
        for child in getattr(launcher, "children", []):
            session_dir = child.session_dir
            session = {}
            if session_dir:
                try:
                    session = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            status = session.get("status", "starting" if child.running else "error")
            try:
                run_dir = next((session_dir / "runs").iterdir()) if session_dir else None
                frames = self.read_recent_frames(run_dir / "frames.csv") if run_dir else []
                frame = frames[-1] if frames else {}
                elapsed = (
                    float(frame.get("t_proc_end", 0)) - float(frames[0].get("t_proc_start", 0))
                    if frames
                    else 0
                )
                fps = len(frames) / elapsed if elapsed > 0 else None
                people = int(frame.get("n_detections") or 0)
                track_count = int(frame.get("n_tracks") or 0)
                drops = int(frame.get("dropped_total") or 0)
            except (OSError, ValueError, StopIteration, KeyError):
                fps, people, track_count, drops = None, 0, 0, 0
            events = session.get("events", [])
            health = "OK"
            for event in events:
                health = {
                    "source_lost": "LOST",
                    "source_recovered": "OK",
                    "frozen_frames": "FROZEN",
                    "dark_frames": "DARK",
                }.get(event.get("kind"), health)
            preview_port = child.preview_port or ports.get(child.cam.camera_id)
            live = {}
            if preview_port:
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{preview_port}/status.json", timeout=0.1
                    ) as response:
                        live = json.loads(response.read())
                    health = live.get("health", health)
                    fps = live.get("processed_fps", fps)
                    people = live.get("people", people) or 0
                    track_count = live.get("tracks", track_count) or 0
                    drops = live.get("drops", drops) or 0
                except (OSError, ValueError):
                    pass
            cameras.append(
                {
                    "camera_id": child.cam.camera_id,
                    "state": status,
                    "processed_fps": fps,
                    "people": people,
                    "tracks": track_count,
                    "drops": drops,
                    "preview_drops": live.get("preview_drops", 0) if preview_port else 0,
                    "health": health,
                    "last_event": events[-1] if events else None,
                    "session_folder": str(session_dir) if session_dir else None,
                    "preview_port": preview_port,
                }
            )
        return {"running": active, "group_id": self.group_id, "cameras": cameras, "final": finals}

    def read_recent_frames(self, path):
        state = self.frame_cache.setdefault(
            str(path), {"offset": 0, "partial": b"", "rows": deque(maxlen=30)}
        )
        try:
            if path.stat().st_size < state["offset"]:
                state.update(offset=0, partial=b"", rows=deque(maxlen=30))
            with path.open("rb") as stream:
                stream.seek(state["offset"])
                payload = stream.read()
                state["offset"] += len(payload)
        except OSError:
            return list(state["rows"])
        lines = (state["partial"] + payload).split(b"\n")
        state["partial"] = lines.pop()
        for line in lines:
            if not line or line.startswith(b"seq,"):
                continue
            try:
                values = next(csv.reader([line.decode("utf-8")]))
                state["rows"].append(dict(zip(FRAME_COLUMNS, values, strict=True)))
            except (UnicodeDecodeError, ValueError):
                continue
        return list(state["rows"])

    def test_camera(self, camera_id, duration=2.0):
        with self.lock:
            if self.recording() and any(c.camera_id == camera_id for c in self.launcher.cameras):
                raise HTTPException(409, "cannot test a camera while it is recording")
        entry = next((item for item in self.entries() if item["camera_id"] == camera_id), None)
        if entry is None:
            raise HTTPException(404, "camera not found")
        source = None
        try:
            source = open_source(str(entry["source"]), None)
            info = source.open()
            started = time.monotonic()
            deadline = started + duration
            frame = None
            reads = 0
            while time.monotonic() < deadline:
                try:
                    current = source.read()
                except SourceEnded:
                    break
                if current is not None:
                    frame = current
                    reads += 1
            elapsed = max(time.monotonic() - started, 0.001)
            if frame is None:
                return {
                    "error": "no frame received",
                    "resolution": [info.width, info.height],
                    "fps": 0,
                    "reported_fps": info.reported_fps,
                }
            ok, encoded = cv2.imencode(".jpg", frame.image)
            return {
                "snapshot": base64.b64encode(encoded.tobytes()).decode("ascii") if ok else None,
                "resolution": [info.width, info.height],
                "fps": reads / elapsed,
                "reported_fps": info.reported_fps,
                "error": None if ok else "JPEG encoding failed",
            }
        except (SourceOpenError, cv2.error, OSError) as exc:
            return {
                "snapshot": None,
                "resolution": None,
                "fps": None,
                "reported_fps": None,
                "error": str(exc),
            }
        finally:
            if source:
                source.close()


def create_app(out="C:/pointr_sessions", config=None, launcher_factory=Launcher):
    studio = Studio(out, config, launcher_factory)

    @asynccontextmanager
    async def lifespan(app):
        app.state.studio = studio
        browser_url = getattr(app.state, "open_browser_url", None)
        if browser_url:
            webbrowser.open(browser_url)
        yield
        studio.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.studio = studio
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def restrict_browser_origin(request, call_next):
        origin = request.headers.get("origin")
        if origin:
            host = origin.split("://", 1)[-1].split(":", 1)[0].strip("[]").lower()
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = host == "localhost"
            if not loopback:
                return JSONResponse(
                    {"detail": "only loopback browser origins are allowed"}, status_code=403
                )
        return await call_next(request)

    @app.get("/api/cameras")
    def list_cameras():
        return studio.entries()

    @app.post("/api/cameras")
    async def add_camera(request: Request):
        entry = await request.json()
        entries = studio.entries()
        entries.append(entry)
        studio.save(entries)
        return entry

    @app.put("/api/cameras/{camera_id}")
    async def edit_camera(camera_id: str, request: Request):
        entry = await request.json()
        entries = studio.entries()
        index = next(
            (i for i, value in enumerate(entries) if value["camera_id"] == camera_id), None
        )
        if index is None:
            raise HTTPException(404, "camera not found")
        entries[index] = entry
        studio.save(entries)
        return entry

    @app.delete("/api/cameras/{camera_id}")
    def remove_camera(camera_id: str):
        entries = studio.entries()
        kept = [entry for entry in entries if entry["camera_id"] != camera_id]
        if len(kept) == len(entries):
            raise HTTPException(404, "camera not found")
        studio.save(kept)
        return {"ok": True}

    @app.post("/api/cameras/{camera_id}/test")
    def test_camera(camera_id: str):
        return studio.test_camera(camera_id)

    @app.post("/api/recording/start")
    def start_recording():
        return studio.start()

    @app.post("/api/recording/stop")
    def stop_recording():
        return studio.stop()

    @app.get("/api/status")
    def recording_status():
        return studio.status()

    @app.get("/api/sessions")
    def sessions():
        base = Path(studio.out).resolve()
        rows = []
        if base.exists():
            for path in base.iterdir():
                session_file = path / "session.json"
                if path.is_symlink() or not path.is_dir() or not session_file.is_file():
                    continue
                try:
                    value = json.loads(session_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                report_text = None
                for run_dir in run_dirs(path) if (path / "session.json").is_file() else []:
                    try:
                        report_text = format_summary(build_report(run_dir))
                    except (OSError, ValueError, KeyError):
                        continue
                    break
                rows.append(
                    {
                        "camera_id": value.get("camera_id"),
                        "group_id": value.get("group_id"),
                        "status": value.get("status"),
                        "started_at": value.get("started_at"),
                        "duration": session_duration(value),
                        "folder": path.name,
                        "summary": report_text,
                    }
                )
        return rows

    @app.get("/api/cameras/{camera_id}/preview/{kind}")
    def preview_proxy(camera_id: str, kind: str):
        if kind not in ("snapshot.jpg", "mjpeg"):
            raise HTTPException(404, "preview not found")
        status = studio.status()
        item = next((cam for cam in status["cameras"] if cam["camera_id"] == camera_id), None)
        port = item.get("preview_port") if item else studio.preview_ports.get(camera_id)
        if port is None:
            raise HTTPException(404, "preview not available")
        url = f"http://127.0.0.1:{port}/{kind}"
        if kind == "snapshot.jpg":
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    return StreamingResponse(iter([response.read()]), media_type="image/jpeg")
            except OSError as exc:
                raise HTTPException(503, "preview unavailable") from exc

        def stream():
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    while chunk := response.read(8192):
                        yield chunk
            except OSError:
                return

        return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (UI_DIST / path).resolve()
        if UI_DIST.resolve() not in candidate.parents and candidate != UI_DIST.resolve():
            raise HTTPException(404)
        if candidate.is_file():
            return FileResponse(candidate)
        index = UI_DIST / "index.html"
        if index.is_file():
            return FileResponse(index)
        return {"message": "Build the UI with npm run build in services/app/ui"}

    return app


def session_duration(value):
    started, ended = value.get("started_at"), value.get("ended_at")
    if not started:
        return None
    start = dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
    if ended:
        finish = dt.datetime.fromisoformat(ended.replace("Z", "+00:00"))
    else:
        finish = dt.datetime.now(dt.UTC)
    return max(0.0, (finish - start).total_seconds())
