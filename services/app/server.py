import base64
import csv
import dataclasses
import datetime as dt
import http.client
import ipaddress
import json
import os
import socket
import threading
import time
import uuid
import webbrowser
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from services.app.calibrations import CalibrationStore
from services.app.camera_log import CameraLog
from services.app.config import CameraConfig, resolve_camera_source
from services.edge.calibration.court import court_lines, court_model
from services.edge.calibration.homography import fit_calibration
from services.edge.calibration.render import projected_court_lines
from services.edge.capture.sources import DEFAULT_CAPTURE_SIZE, SourceOpenError, open_source
from services.edge.capture.types import SourceEnded
from services.edge.contract import CONTRACT_VERSION
from services.edge.launcher import Camera, ConfigError, Launcher, Options, parse_config
from services.edge.reports.build import build_report, format_summary, run_dirs
from services.edge.session.writer import mask_credentials

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
        self.calibrations = CalibrationStore(self.config.path.parent)
        self.launcher_factory = launcher_factory
        self.launcher = None
        self.worker = None
        self.group_id = None
        self.preview_ports: dict[str, int] = {}
        self.lock = threading.RLock()
        self.final: dict[str, dict] = {}
        self.logs: dict[str, CameraLog] = {}
        self.frame_cache = {}
        self.calibration_frames = {}
        self.calibration_warnings: dict[str, str] = {}
        self.active_group_path = self.config.path.with_name("active_group.json")
        self.recover_interrupted_group()

    def recover_interrupted_group(self):
        try:
            group_id = json.loads(self.active_group_path.read_text(encoding="utf-8"))["group_id"]
        except (OSError, ValueError, KeyError, TypeError):
            return
        for session_file in Path(self.out).glob("*/session.json"):
            try:
                session = json.loads(session_file.read_text(encoding="utf-8"))
                if session.get("group_id") != group_id or session.get("status") != "running":
                    continue
                session["status"] = "interrupted"
                session["ended_at"] = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
                session.setdefault("events", []).append(
                    {
                        "t_wall": session["ended_at"],
                        "t_mono": None,
                        "kind": "interrupted",
                        "detail": "app restarted after an unclean shutdown",
                    }
                )
                temporary = session_file.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
                os.replace(temporary, session_file)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        self.active_group_path.unlink(missing_ok=True)

    def entries(self):
        return self.config.read()

    def save(self, entries):
        try:
            self.config.write(entries)
        except ConfigError as exc:
            detail = mask_credentials(str(exc))
            if getattr(exc, "field_errors", None):
                detail = {
                    "message": detail,
                    "fields": [
                        {**error, "message": mask_credentials(error["message"])}
                        for error in exc.field_errors
                    ],
                }
            raise HTTPException(422, detail) from exc

    def recording(self):
        return bool(self.worker and self.worker.is_alive())

    def log(self, camera_id) -> CameraLog:
        with self.lock:
            return self.logs.setdefault(camera_id, CameraLog())

    def note_child(self, child, log, state, events):
        """Copy a child's news into its camera log: session events, and, once, why it ended
        or never recorded (the error stays until dismissed or the camera next starts)."""
        if child.session_dir:
            log.ingest_session_events(str(child.session_dir), events)
        if log.reported_child is child:
            return
        failure = getattr(child, "failure", None)
        running = child.running
        if not failure and (running or state != "error"):
            return
        log.reported_child = child
        proc = getattr(child, "proc", None)
        code = getattr(proc, "returncode", None)
        if failure and "no session after" in failure:
            message = "The camera took too long to open, so it was stopped."
        elif failure:
            message = "The camera could not start recording."
        else:
            message = "The camera stopped recording because of an error."
        lines = [f"source: {mask_credentials(str(child.cam.source))}"]
        if failure:
            lines.append(f"reason: {failure}")
        if code is not None:
            lines.append(f"exit code: {code}")
        tail = list(getattr(child, "tail", ()))
        if tail:
            lines.append(f"output (last {len(tail)} lines):")
            lines.extend(tail)
        log.set_error(message, "\n".join(lines))
        failure_kind = (
            "source_open_failed"
            if failure and ("open" in failure.lower() or "source" in failure.lower())
            else "start_failed"
        )
        log.add_event(failure_kind if failure else "error", failure or message)

    def start(self):
        with self.lock:
            if self.recording():
                raise HTTPException(409, "recording is already active")
            entries = self.entries()
            if not entries:
                raise HTTPException(422, "add at least one camera")
            cameras = [camera for camera in parse_config(entries) if camera.enabled]
            if not cameras:
                raise HTTPException(422, "enable at least one camera before starting")
            resolved_cameras = []
            for camera in cameras:
                try:
                    resolved_cameras.append(
                        dataclasses.replace(camera, source=resolve_camera_source(camera.source))
                    )
                except ConfigError as exc:
                    log = self.log(camera.camera_id)
                    detail = f"source: {mask_credentials(str(camera.source))}\nreason: {exc}"
                    log.set_error("The camera URL could not be used safely.", detail)
                    log.add_event("source_open_failed", exc)
            cameras = resolved_cameras
            if not cameras:
                raise HTTPException(422, "no enabled camera has a usable source; see camera errors")
            # Load every calibration before any state changes. A camera whose calibration is
            # missing records uncalibrated; one whose calibration is corrupt does too, but says
            # so (a session event, and a warning in the status). One camera never blocks the rest.
            calibration_paths: dict[str, str | None] = {}
            warnings: dict[str, str] = {}
            for camera in cameras:
                calibration_paths[camera.camera_id] = None
                try:
                    saved = self.calibrations.load(camera.camera_id)
                except Exception as exc:
                    warnings[camera.camera_id] = (
                        " ".join(str(exc).split())
                        + "; recording without calibration (positions in pixels)"
                    )
                    self.log(camera.camera_id).add_event(
                        "calibration_not_used", warnings[camera.camera_id]
                    )
                    continue
                if saved:
                    calibration_paths[camera.camera_id] = str(
                        self.calibrations.camera_dir(camera.camera_id)
                        / saved["calibration_id"]
                        / "calibration.json"
                    )
            self.group_id = str(uuid.uuid4())
            self.final = {}
            self.preview_ports = {}
            self.calibration_warnings = warnings
            for camera in cameras:
                self.log(camera.camera_id).clear_error()
                port = self.free_port()
                while port in self.preview_ports.values():
                    port = self.free_port()
                self.preview_ports[camera.camera_id] = port
            configured = []
            for camera in cameras:
                configured.append(
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
                        calibration_paths[camera.camera_id],
                        warnings.get(camera.camera_id),
                        camera.name,
                        camera.fps_cap,
                        camera.enabled,
                    )
                )
            cameras = configured
            opts = Options(self.out, self.group_id)
            self.launcher = self.launcher_factory(cameras, opts)
            self.active_group_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.active_group_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"group_id": self.group_id}), encoding="utf-8")
            os.replace(temporary, self.active_group_path)
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
        if not worker or not worker.is_alive():
            self.active_group_path.unlink(missing_ok=True)
        return self.status()

    def status(self):
        with self.lock:
            launcher = self.launcher
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
            log = self.log(child.cam.camera_id)
            self.note_child(child, log, status, events)
            health = "OK"
            for event in events:
                health = {
                    "source_lost": "LOST",
                    "source_recovered": "OK",
                    "frozen_frames": "FROZEN",
                    "dark_frames": "DARK",
                }.get(event.get("kind"), health)
            # only a port the camera has confirmed: it may still be loading its model, and it picks
            # another port when the one Studio chose is busy. Until then the UI shows a placeholder.
            preview_port = child.preview_port if getattr(child, "preview_ready", False) else None
            live = {}
            if preview_port:
                try:
                    with preview_get(preview_port, "status.json", timeout=0.1) as response:
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
                    "name": child.cam.name or child.cam.camera_id,
                    "state": status,
                    "processed_fps": fps,
                    "people": people,
                    "tracks": track_count,
                    "drops": drops,
                    "preview_drops": live.get("preview_drops", 0) if preview_port else 0,
                    "health": health,
                    "last_event": (
                        {**events[-1], "detail": mask_credentials(str(events[-1].get("detail")))}
                        if events and events[-1].get("detail") is not None
                        else (events[-1] if events else None)
                    ),
                    "session_folder": str(session_dir) if session_dir else None,
                    "preview_port": preview_port,
                    "error": mask_credentials(getattr(child, "failure", None) or "") or None,
                    "calibration_warning": self.calibration_warnings.get(child.cam.camera_id),
                    **log.snapshot(),
                    "calibration": (
                        {
                            "calibration_id": session.get("calibration", {}).get("calibration_id"),
                            "check_error_m": session.get("calibration", {}).get("check_error_m"),
                        }
                        if session.get("calibration")
                        else None
                    ),
                }
            )
        shown = {camera["camera_id"] for camera in cameras}
        with self.lock:
            others = [(name, log) for name, log in self.logs.items() if name not in shown]
        idle = []
        for name, log in others:
            snapshot = log.snapshot()
            if snapshot["last_error"] or snapshot["recent_events"]:
                idle.append({"camera_id": name, **snapshot})
        return {
            "running": active,
            "group_id": self.group_id,
            "cameras": cameras,
            "idle_cameras": idle,
            "config_warning": self.config.warning,
            "final": finals,
        }

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
                if len(values) < len(
                    FRAME_COLUMNS
                ):  # a half-written row; later columns are ignored
                    continue
                state["rows"].append(dict(zip(FRAME_COLUMNS, values, strict=False)))
            except (UnicodeDecodeError, ValueError):
                continue
        return list(state["rows"])

    def test_camera(self, camera_id, duration=3.0):
        with self.lock:
            if self.recording() and any(c.camera_id == camera_id for c in self.launcher.cameras):
                raise HTTPException(409, "cannot test a camera while it is recording")
        entry = next((item for item in self.entries() if item["camera_id"] == camera_id), None)
        if entry is None:
            raise HTTPException(404, "camera not found")
        source = None
        try:
            source = open_source(resolve_camera_source(str(entry["source"])), None)
            source.fps_cap = entry.get("fps_cap")
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
                self.record_test_failure(camera_id, "no frame received", entry["source"])
                return {
                    "error": "no frame received",
                    "resolution": [info.width, info.height],
                    "fps": 0,
                    "reported_fps": info.reported_fps,
                }
            ok, encoded = cv2.imencode(".jpg", frame.image)
            if not ok:
                self.record_test_failure(camera_id, "JPEG encoding failed", entry["source"])
            return {
                "snapshot": base64.b64encode(encoded.tobytes()).decode("ascii") if ok else None,
                "resolution": [info.width, info.height],
                "fps": reads / elapsed,
                "reported_fps": info.reported_fps,
                "error": None if ok else "JPEG encoding failed",
            }
        except (ConfigError, SourceOpenError, cv2.error, OSError) as exc:
            self.record_test_failure(camera_id, str(exc), entry["source"])
            return {
                "snapshot": None,
                "resolution": None,
                "fps": None,
                "reported_fps": None,
                "error": mask_credentials(str(exc)),
            }
        finally:
            if source:
                source.close()

    def record_test_failure(self, camera_id, reason, source):
        detail = f"source: {mask_credentials(str(source))}\nreason: {mask_credentials(str(reason))}"
        self.log(camera_id).set_error("The camera test failed.", detail)
        self.log(camera_id).add_event("source_open_failed", reason)

    def calibration_frame(self, camera_id, cache=True):
        entry = next((item for item in self.entries() if item["camera_id"] == camera_id), None)
        if entry is None:
            raise HTTPException(404, "camera not found")
        with self.lock:
            child = next(
                (
                    c
                    for c in getattr(self.launcher, "children", [])
                    if c.cam.camera_id == camera_id and c.running
                ),
                None,
            )
            port = child.preview_port if child else None
        try:
            if port:
                with preview_get(port, "raw-snapshot.jpg", timeout=3) as r:
                    jpeg = r.read()
                image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError("recording process returned an invalid JPEG")
            else:
                # the recorder's own capture size, so the frame is the one it will record
                source = open_source(
                    resolve_camera_source(str(entry["source"])), DEFAULT_CAPTURE_SIZE
                )
                source.fps_cap = entry.get("fps_cap")
                try:
                    source.open()
                    deadline = time.monotonic() + 3
                    image = None
                    while time.monotonic() < deadline and image is None:
                        try:
                            frame = source.read()
                        except SourceEnded:
                            break
                        if frame is not None:
                            image = frame.image.copy()
                    if image is None:
                        raise ValueError("no frame received")
                finally:
                    source.close()
                ok, encoded = cv2.imencode(".jpg", image)
                if not ok:
                    raise ValueError("JPEG encoding failed")
                jpeg = encoded.tobytes()
        except (ConfigError, SourceOpenError, OSError, ValueError, cv2.error) as exc:
            raise HTTPException(
                502, mask_credentials(f"could not capture calibration frame: {exc}")
            ) from exc
        token = str(uuid.uuid4())
        if cache:
            with self.lock:
                self.calibration_frames[camera_id] = {
                    "token": token,
                    "jpeg": jpeg,
                    "image": image.copy(),
                }
        return jpeg, token, image.shape[1], image.shape[0]

    def calibration_fit(self, camera_id, payload, save=False):
        with self.lock:
            cached = self.calibration_frames.get(camera_id)
        if not cached or payload.get("frame_token") != cached["token"]:
            raise HTTPException(409, "capture a fresh frame before fitting or saving")
        try:
            court = court_model(
                payload.get("court_kind", "custom"),
                float(payload.get("length_m", 28)),
                float(payload.get("width_m", 15)),
                payload.get("custom_landmarks"),
            )
            points = payload["points"]
            for point in points:
                image_x, image_y = point["image_px"]
                if (
                    not 0 <= image_x < cached["image"].shape[1]
                    or not 0 <= image_y < cached["image"].shape[0]
                ):
                    raise ValueError("image point is outside the captured frame")
                x, y = point["court_m"]
                if not 0 <= x <= court.length_m or not 0 <= y <= court.width_m:
                    raise ValueError("court point is outside the court dimensions")
            result = fit_calibration(
                points,
                float(payload.get("max_check_error_m", 0.5)),
                bool(payload.get("save_anyway", False)),
                enforce_limit=save,
                require_checks=save,
                court_dimensions=(court.length_m, court.width_m)
                if court.kind == "fiba_half"
                else None,
            )
        except (KeyError, TypeError, ValueError, np.linalg.LinAlgError) as exc:
            raise HTTPException(422, str(exc) or exc.__class__.__name__) from exc
        result["projected_court_lines"] = projected_court_lines(
            result["homography_image_to_court"], court
        )
        result["court"] = {
            "kind": court.kind,
            "type": court.kind,
            "length_m": court.length_m,
            "width_m": court.width_m,
            "landmarks": court.landmarks,
        }
        result["point_errors_m"] = []
        calibration_index = check_index = 0
        for point in points:
            if point["role"] == "calibration":
                result["point_errors_m"].append(result["calibration_errors_m"][calibration_index])
                calibration_index += 1
            else:
                result["point_errors_m"].append(result["check_errors_m"][check_index])
                check_index += 1
        if save:
            residual_iter = iter(result["point_errors_m"])
            document = {
                "contract_version": CONTRACT_VERSION,
                "calibration_id": str(uuid.uuid4()),
                "camera_id": camera_id,
                "created_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
                "court": result["court"],
                "image_size": {
                    "width": cached["image"].shape[1],
                    "height": cached["image"].shape[0],
                },
                "homography_image_to_court": result["homography_image_to_court"],
                "points": [
                    {
                        "image_px": [float(v) for v in p["image_px"]],
                        "court_m": [float(v) for v in p["court_m"]],
                        "role": p["role"],
                        "residual_m": next(residual_iter),
                    }
                    for p in points
                ],
                "errors": {
                    key: result[key]
                    for key in ("calibration_mean_m", "check_mean_m", "check_max_m")
                },
                "max_check_error_m": float(payload.get("max_check_error_m", 0.5)),
                "forced": result["forced"],
                "audit_frame": "frame.jpg",
            }
            try:
                path = self.calibrations.save(document, cached["jpeg"])
            except (OSError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
            result["calibration"] = document
            result["path"] = str(path)
        return result


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
        client_host = request.client.host if request.client else ""
        try:
            loopback_client = ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            loopback_client = False
        if not loopback_client:
            return JSONResponse({"detail": "local access only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            request_origin = f"{request.url.scheme}://{request.url.netloc}".lower()
            if origin.rstrip("/").lower() != request_origin:
                return JSONResponse(
                    {"detail": "cross-origin requests are not allowed"}, status_code=403
                )
        return await call_next(request)

    @app.get("/api/cameras")
    def list_cameras():
        return [
            {
                **entry,
                "name": entry.get("name", entry["camera_id"]),
                "enabled": entry.get("enabled", True),
                "source": mask_credentials(str(entry["source"])),
            }
            for entry in studio.entries()
        ]

    @app.post("/api/cameras")
    async def add_camera(request: Request):
        entry = await request.json()
        entries = studio.entries()
        entries.append(entry)
        studio.save(entries)
        return {
            **entry,
            "source": mask_credentials(str(entry["source"])),
            "name": entry.get("name", entry["camera_id"]),
            "enabled": entry.get("enabled", True),
        }

    @app.put("/api/cameras/{camera_id}")
    async def edit_camera(camera_id: str, request: Request):
        entry = await request.json()
        entries = studio.entries()
        index = next(
            (i for i, value in enumerate(entries) if value["camera_id"] == camera_id), None
        )
        if index is None:
            raise HTTPException(404, "camera not found")
        if entry.get("source") == mask_credentials(str(entries[index]["source"])):
            entry["source"] = entries[index]["source"]
        entries[index] = entry
        studio.save(entries)
        return {
            **entry,
            "source": mask_credentials(str(entry["source"])),
            "name": entry.get("name", entry["camera_id"]),
            "enabled": entry.get("enabled", True),
        }

    @app.delete("/api/cameras/{camera_id}")
    def remove_camera(camera_id: str):
        entries = studio.entries()
        kept = [entry for entry in entries if entry["camera_id"] != camera_id]
        if len(kept) == len(entries):
            raise HTTPException(404, "camera not found")
        studio.save(kept)
        studio.logs.pop(camera_id, None)
        return {"ok": True}

    @app.delete("/api/cameras/{camera_id}/error")
    def dismiss_camera_error(camera_id: str):
        studio.log(camera_id).clear_error()
        return {"ok": True}

    @app.post("/api/cameras/{camera_id}/test")
    def test_camera(camera_id: str):
        return studio.test_camera(camera_id)

    @app.get("/api/court")
    def court_geometry(kind: str = "custom", length_m: float = 28.0, width_m: float = 15.0):
        """The court model the fit uses: named landmarks and the lines to draw, in metres."""
        try:
            court = court_model(kind, length_m, width_m)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "kind": court.kind,
            "length_m": court.length_m,
            "width_m": court.width_m,
            "landmarks": court.landmarks,
            "lines": court_lines(court),
        }

    @app.get("/api/cameras/{camera_id}/calibration")
    def get_calibration(camera_id: str):
        try:
            return studio.calibrations.load(camera_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/cameras/{camera_id}/calibration/frame")
    def calibration_frame(camera_id: str):
        jpeg, token, width, height = studio.calibration_frame(camera_id)
        return Response(
            jpeg,
            media_type="image/jpeg",
            headers={
                "X-Frame-Token": token,
                "X-Frame-Width": str(width),
                "X-Frame-Height": str(height),
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/cameras/{camera_id}/calibration/fit")
    async def fit_camera_calibration(camera_id: str, request: Request):
        return studio.calibration_fit(camera_id, await request.json())

    @app.put("/api/cameras/{camera_id}/calibration")
    async def save_camera_calibration(camera_id: str, request: Request):
        return studio.calibration_fit(camera_id, await request.json(), save=True)

    @app.get("/api/cameras/{camera_id}/calibration/compare")
    def compare_calibration(camera_id: str):
        try:
            saved = studio.calibrations.load(camera_id)
            if saved is None:
                raise HTTPException(404, "no saved calibration")
            audit = studio.calibrations.audit_frame(saved)
            fresh_jpeg, _, width, height = studio.calibration_frame(camera_id, cache=False)
            old_image = cv2.imdecode(np.frombuffer(audit, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            new_image = cv2.imdecode(
                np.frombuffer(fresh_jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
            )
            score = None
            if (
                old_image is not None
                and new_image is not None
                and old_image.shape == new_image.shape
            ):
                score = float(cv2.absdiff(old_image, new_image).mean() / 255)
            return {
                "calibration_id": saved["calibration_id"],
                "difference_score": score,
                "warning": score is None or score > 0.15,
                "audit_frame": base64.b64encode(audit).decode("ascii"),
                "fresh_frame": base64.b64encode(fresh_jpeg).decode("ascii"),
                "resolution": [width, height],
            }
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

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
        if item is None:
            raise HTTPException(404, "preview not available")
        port = item.get("preview_port")
        if port is None:
            raise HTTPException(503, "preview not ready: the camera is still starting")
        try:  # connect before answering: an empty 200 is never retried by an <img>
            response = preview_get(port, kind, timeout=5)
        except OSError as exc:
            raise HTTPException(503, "preview unavailable") from exc
        if kind == "snapshot.jpg":
            with response:
                return StreamingResponse(iter([response.read()]), media_type="image/jpeg")

        def stream():
            try:
                with response:
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


def preview_get(port: int, path: str, timeout: float) -> http.client.HTTPResponse:
    """GET a camera's local preview server. http.client only speaks HTTP, so unlike urlopen it
    cannot be pointed at file: or ftp: URLs. An error status raises OSError, as urlopen did."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", f"/{path}", headers={"Connection": "close"})
        response = conn.getresponse()
    except BaseException:
        conn.close()
        raise
    if response.status >= 400:
        response.close()
        raise OSError(f"preview server answered {response.status} for /{path}")
    return response


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
