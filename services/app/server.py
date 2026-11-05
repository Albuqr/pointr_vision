import base64
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
from collections import Counter
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from services.app.audit import AuditTrail
from services.app.calibrations import CalibrationStore
from services.app.camera_log import CameraLog
from services.app.camera_status import camera_view
from services.app.config import CameraConfig, resolve_camera_source
from services.edge.calibration.court import court_lines, court_model
from services.edge.calibration.homography import fit_calibration
from services.edge.calibration.render import projected_court_lines
from services.edge.capture.sources import DEFAULT_CAPTURE_SIZE, SourceOpenError, open_source
from services.edge.capture.types import SourceEnded
from services.edge.launcher import ConfigError, Launcher, Options, parse_config
from services.edge.reports.build import build_report
from services.edge.session.folder import (
    FrameTail,
    find_sessions,
    mark_interrupted,
    read_session,
)
from services.edge.session.writer import mask_credentials

ROOT = Path(__file__).resolve().parents[2]
UI_DIST = Path(__file__).parent / "ui" / "dist"


class Studio:
    def __init__(self, out: str, config=None, launcher_factory=Launcher):
        self.out = str(Path(out).resolve())
        self.config = config or CameraConfig()
        self.calibrations = CalibrationStore(self.config.path.parent)
        self.audit = AuditTrail(self.config.path.with_name("audit.jsonl"))
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
        self.refusals: dict[str, str] = {}  # camera_id -> last calibration refusal (one line)
        self.uncalibrated: dict[str, str] = {}  # camera_id -> refusal the operator chose to skip
        self.active_group_path = self.config.path.with_name("active_group.json")
        self.recover_interrupted_group()

    def recover_interrupted_group(self):
        try:
            group_id = json.loads(self.active_group_path.read_text(encoding="utf-8"))["group_id"]
        except (OSError, ValueError, KeyError, TypeError):
            return
        for session in find_sessions(self.out, group_id=group_id):
            for problem in mark_interrupted(session):
                self.audit.record("recovery", session.get("camera_id"), problem)
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
            if camera_id not in self.logs:
                self.logs[camera_id] = CameraLog(
                    lambda message, detail: self.audit.record(
                        "error", camera_id, message, {"reason": detail}
                    )
                )
            return self.logs[camera_id]

    @contextmanager
    def audited(self, action, camera_id=None):
        """Write one audit entry when the block ends: `ok`, or the error that ended it. The block
        may fill the yielded dict: `detail`, and `outcome` for a failure it returns, not raises."""
        note = {}
        try:
            yield note
        except HTTPException as exc:
            reason = exc.detail
            if isinstance(reason, dict):  # field errors: the message and each field's own message
                fields = [str(f.get("message")) for f in reason.get("fields", [])]
                reason = "; ".join([str(reason.get("message")), *fields])
            self.audit.record(action, camera_id, str(reason), note.get("detail"))
            raise
        except Exception as exc:
            self.audit.record(action, camera_id, f"{type(exc).__name__}: {exc}", note.get("detail"))
            raise
        self.audit.record(action, camera_id, note.get("outcome") or "ok", note.get("detail"))

    def camera_settings(self, camera):
        return {
            "camera_id": camera.camera_id,
            "name": camera.name,
            "source": camera.source,
            "link": camera.link,
            "det_size": camera.det_size,
            "fps_cap": camera.fps_cap,
        }

    def apply_view(self, log, view, snapshot):
        """Copy a camera's news into its camera log: session events, run-time errors once each
        (the error stays until dismissed or the camera next starts) and, once per child, why it
        ended or never recorded."""
        if snapshot is not None and view.session_folder:
            log.ingest_session(snapshot)
            key = f"{view.session_folder}#run_errors"
            with log.lock:  # two polls at once must not report the same error twice
                start = log.seen.get(key, 0)
                log.seen[key] = len(view.run_errors)
            for run_error in view.run_errors[start:]:
                log.set_error("The camera reported an error while recording.", run_error.detail)
                log.add_event("error", run_error.error)
        problem = view.problem
        if problem is None:
            return
        with log.lock:
            if log.reported_child is problem.token:
                return
            log.reported_child = problem.token
        if problem.is_error:
            log.set_error(problem.message, problem.detail)
            log.add_event(problem.event_kind, problem.event_detail)
            return
        if problem.event_kind:
            log.add_event(problem.event_kind, problem.event_detail)
        self.audit.record("recording_stop", view.camera_id, detail={"reason": problem.detail})

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
            failed: dict[str, str] = dict(self.uncalibrated)  # the operator's choice (D-057)
            for camera in cameras:
                calibration_paths[camera.camera_id] = None
                if reason := failed.get(camera.camera_id):
                    warnings[camera.camera_id] = (
                        f"calibration refused: {reason}; recording without calibration "
                        "(positions in pixels)"
                    )
                    continue
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
                    dataclasses.replace(
                        camera,
                        http_preview_port=self.preview_ports[camera.camera_id],
                        calibration_path=calibration_paths[camera.camera_id],
                        calibration_problem=(
                            None if camera.camera_id in failed else warnings.get(camera.camera_id)
                        ),
                        calibration_failed=failed.get(camera.camera_id),
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

    def stop(self, source: Literal["ui"] | None = None):
        """Stop the group. `source` "ui" is the operator's stop: each session ends normally with
        a `stopped` event (D-049); without it (Studio shutting down) they end `interrupted`."""
        with self.lock:
            launcher = self.launcher
            worker = self.worker
        if worker and worker.is_alive():
            launcher.stop_all("[app] stop requested", source=source)
            worker.join(timeout=50)
        if not worker or not worker.is_alive():
            self.active_group_path.unlink(missing_ok=True)
        return self.status()

    def status(self):
        with self.lock:
            launcher = self.launcher
            active = self.recording()
            finals = dict(self.final)
            uncalibrated = dict(self.uncalibrated)
        cameras = []
        for child in getattr(launcher, "children", []):
            progress = child.progress()
            snapshot = read_session(progress.session_dir) if progress.session_dir else None
            frames, frames_skipped = self.recent_frames(snapshot)
            live = self.read_live(progress.confirmed_preview_port)
            view = camera_view(progress, snapshot, frames, live)
            log = self.log(view.camera_id)
            self.apply_view(log, view, snapshot)
            cameras.append(
                {
                    "camera_id": view.camera_id,
                    "frame_rows_skipped": frames_skipped,  # damaged frames.csv rows, not shown
                    "name": view.name,
                    "state": view.state,
                    "processed_fps": view.processed_fps,
                    "people": view.people,
                    "tracks": view.tracks,
                    "drops": view.drops,
                    "preview_drops": view.preview_drops,
                    "health": view.health,
                    "last_event": view.last_event,
                    "session_folder": view.session_folder,
                    "preview_port": view.preview_port,
                    "error": view.error,
                    "calibration_warning": self.calibration_warnings.get(view.camera_id),
                    **log.snapshot(),
                    "calibration": view.calibration,
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
            "uncalibrated": uncalibrated,
            "final": finals,
        }

    @staticmethod
    def read_live(port):
        """The preview's status.json, or {} when there is no confirmed preview or it is silent."""
        if not port:
            return {}
        try:
            with preview_get(port, "status.json", timeout=0.1) as response:
                live = json.loads(response.read())
        except (OSError, ValueError):
            return {}
        return live if isinstance(live, dict) else {}

    def recent_frames(self, snapshot):
        """The latest frame rows of the session's last listed run, read as far as the file has
        grown since the previous poll."""
        run = snapshot.latest_run if snapshot else None
        if run is None:
            return [], 0
        tail = self.frame_cache.get(str(run.path))
        if tail is None:
            tail = self.frame_cache[str(run.path)] = FrameTail(run.path)
        return tail.poll(), tail.skipped

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
            frame, reads = read_frames(source, duration)
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
            progress = next(
                (
                    p
                    for p in (c.progress() for c in getattr(self.launcher, "children", []))
                    if p.cam.camera_id == camera_id and p.alive
                ),
                None,
            )
            port = progress.preview_port if progress else None
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
                    frame, _ = read_frames(source, 3, stop_at_first=True)
                    if frame is None:
                        raise ValueError("no frame received")
                    image = frame.image.copy()
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
            )
        except (KeyError, TypeError, ValueError, np.linalg.LinAlgError, cv2.error) as exc:
            message = str(exc) or exc.__class__.__name__
            with self.lock:
                self.refusals[camera_id] = " ".join(message.split())[:300]  # fits a command line
            raise CalibrationRefusal(message, getattr(exc, "refusal", {"kind": "invalid"})) from exc
        with self.lock:
            self.refusals.pop(camera_id, None)
        result["projected_court_lines"] = projected_court_lines(
            result["homography_image_to_court"], court
        )
        from services.edge.calibration.intake import court_document

        result["court"] = court_document(court)
        errors = {
            "calibration": iter(result["calibration_errors_m"]),
            "check": iter(result["check_errors_m"]),
        }
        result["point_errors_m"] = [
            next(errors["calibration" if point["role"] == "calibration" else "check"])
            for point in points
        ]
        if save:
            from services.edge.calibration.intake import build_document

            document = build_document(
                camera_id=camera_id,
                court=court,
                image_size=cached["image"].shape[1::-1],
                points=points,
                fit=result,
                max_check_error_m=float(payload.get("max_check_error_m", 0.5)),
                calibration_id=str(uuid.uuid4()),
                created_at=dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            )
            try:
                path = self.calibrations.save(document, cached["jpeg"])
            except (OSError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
            result["calibration"] = document
            result["path"] = str(path)
            with self.lock:
                self.uncalibrated.pop(camera_id, None)  # a saved calibration is the way forward
        return result


class CalibrationRefusal(HTTPException):
    """A 422 whose body also carries `refusal`: what the operator needs to retry (D-057)."""

    def __init__(self, message, refusal):
        super().__init__(422, message)
        self.refusal = refusal


def _camera_id(entry):
    camera_id = entry.get("camera_id") if isinstance(entry, dict) else None
    return None if camera_id is None else str(camera_id)


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

    @app.exception_handler(CalibrationRefusal)
    async def calibration_refused(request, exc):
        return JSONResponse(
            {"detail": exc.detail, "refusal": exc.refusal}, status_code=exc.status_code
        )

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
        return [public_entry(entry) for entry in studio.entries()]

    @app.post("/api/cameras")
    async def add_camera(request: Request):
        entry = await request.json()
        with studio.audited("camera_add", _camera_id(entry)) as note:
            entries = studio.entries()
            entries.append(entry)
            studio.save(entries)
            note["detail"] = entry
        return public_entry(entry)

    @app.put("/api/cameras/{camera_id}")
    async def edit_camera(camera_id: str, request: Request):
        entry = await request.json()
        with studio.audited("camera_edit", camera_id) as note:
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
            note["detail"] = entry
        return public_entry(entry)

    @app.delete("/api/cameras/{camera_id}")
    def remove_camera(camera_id: str):
        with studio.audited("camera_remove", camera_id):
            entries = studio.entries()
            kept = [entry for entry in entries if entry["camera_id"] != camera_id]
            if len(kept) == len(entries):
                raise HTTPException(404, "camera not found")
            studio.save(kept)
        studio.logs.pop(camera_id, None)
        with studio.lock:
            studio.refusals.pop(camera_id, None)
            studio.uncalibrated.pop(camera_id, None)
        return {"ok": True}

    @app.delete("/api/cameras/{camera_id}/error")
    def dismiss_camera_error(camera_id: str):
        studio.log(camera_id).clear_error()
        return {"ok": True}

    @app.post("/api/cameras/{camera_id}/test")
    def test_camera(camera_id: str):
        with studio.audited("camera_test", camera_id) as note:
            result = studio.test_camera(camera_id)
            note["outcome"] = result.get("error")
        return result

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
        payload = await request.json()
        with studio.audited("calibration_save", camera_id):
            return studio.calibration_fit(camera_id, payload, save=True)

    @app.post("/api/cameras/{camera_id}/calibration/uncalibrated")
    def start_uncalibrated(camera_id: str):
        """After a refusal: this camera's next start is uncalibrated, recorded as a failed
        calibration check. The reason is Studio's own record of the refusal (D-057)."""
        with studio.audited("calibration_uncalibrated", camera_id) as note:
            with studio.lock:
                reason = studio.refusals.get(camera_id)
                if reason is None:
                    raise HTTPException(409, "this camera has no refused calibration")
                studio.uncalibrated[camera_id] = reason
            note["detail"] = {"reason": reason}
            return {"camera_id": camera_id, "reason": reason}

    @app.delete("/api/cameras/{camera_id}/calibration/uncalibrated")
    def clear_uncalibrated(camera_id: str):
        with studio.audited("calibration_uncalibrated_clear", camera_id):
            with studio.lock:
                studio.uncalibrated.pop(camera_id, None)
            return {"camera_id": camera_id}

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
        with studio.audited("recording_start") as note:
            status = studio.start()
            started = {c.camera_id for c in studio.launcher.cameras}
            skipped = [
                {"camera_id": e["camera_id"], "reason": error["message"] if error else None}
                for e in studio.entries()
                if e.get("enabled", True) and e["camera_id"] not in started
                for error in [studio.log(e["camera_id"]).snapshot()["last_error"]]
            ]
            note["detail"] = {
                "group_id": studio.group_id,
                "cameras": [studio.camera_settings(c) for c in studio.launcher.cameras],
                "skipped": skipped,
            }
        return status

    @app.post("/api/recording/stop")
    def stop_recording():
        with studio.audited("recording_stop"):
            return studio.stop(source="ui")

    @app.get("/api/status")
    def recording_status():
        return studio.status()

    @app.get("/api/sessions")
    def sessions():
        rows = [session_row(session.path) for session in find_sessions(studio.out)]
        rows.sort(key=lambda row: str(row["started_at"] or ""), reverse=True)
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

    @app.get("/api/{path:path}")
    def unknown_api(path: str):
        raise HTTPException(404)

    app.mount("/", StaticFiles(directory=UI_DIST, html=True, check_dir=False), name="ui")

    return app


def read_frames(source, duration, stop_at_first=False):
    """Read `source` for `duration` seconds (or until its first frame): the last frame and how
    many frames arrived. The frame is None when none did or the source ended first."""
    deadline = time.monotonic() + duration
    frame, reads = None, 0
    while time.monotonic() < deadline and not (stop_at_first and frame is not None):
        try:
            current = source.read()
        except SourceEnded:
            break
        if current is not None:
            frame, reads = current, reads + 1
    return frame, reads


def public_entry(entry):
    """A camera entry as the API shows it: credentials masked, name and enabled filled in."""
    return {
        **entry,
        "name": entry.get("name", entry["camera_id"]),
        "enabled": entry.get("enabled", True),
        "source": mask_credentials(str(entry["source"])),
    }


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


def _why(error):
    """One readable reason for a file that could not be read (no full path, no traceback)."""
    if isinstance(error, FileNotFoundError):
        return f"{Path(str(error.filename)).name} missing"
    if isinstance(error, OSError):
        return f"{Path(str(error.filename)).name} unreadable ({error.strerror})"
    return f"{type(error).__name__}: {str(error)[:80]}"


def session_row(path: Path) -> dict:
    """One sessions-page row, from the session folder's files only (B7). Whatever cannot be
    read stays None and is named in `missing`: a damaged session is listed, never dropped."""
    row = {
        "folder": path.name,
        "camera_id": None,
        "group_id": None,
        "status": None,
        "started_at": None,
        "duration": None,
        "fps": None,
        "captured": None,
        "dropped": None,
        "drop_rate": None,
        "events": {},
        "missing": [],
    }
    missing = row["missing"]
    snapshot = read_session(path)
    missing.extend(snapshot.problems)
    if snapshot.data is None:
        return row
    value = snapshot.document()
    for key in ("camera_id", "group_id", "status", "started_at"):
        row[key] = value.get(key)
    try:
        row["duration"] = session_duration(value)
    except (TypeError, ValueError, AttributeError):
        missing.append("started_at or ended_at in session.json is not a valid time")
    if row["started_at"] is None:
        missing.append("started_at not recorded")
    events = value.get("events")
    if isinstance(events, list):
        row["events"] = dict(Counter(str(e.get("kind")) for e in events if isinstance(e, dict)))
    else:
        missing.append("events not readable in session.json")
    latest = snapshot.latest_run
    if latest is None:
        missing.append("no run recorded in this session")
        return row
    try:
        stats = build_report(latest.path).session
    except Exception as error:  # a damaged run must not hide the session
        missing.append(f"report for run {latest.path.name[:8]}: {_why(error)}")
        return row
    row.update(
        fps=stats.processed_fps.value,
        captured=stats.n_captured,
        dropped=stats.n_dropped,
        drop_rate=stats.drop_rate.value,
    )
    if stats.n_dropped is None:
        missing.append("counts not recorded (the run did not end)")
    return row
