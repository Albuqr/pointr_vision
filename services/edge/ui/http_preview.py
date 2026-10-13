"""Loopback HTTP preview; annotation and JPEG work run outside the perception thread."""

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

from services.edge.calibration.court import court_model
from services.edge.calibration.render import draw_projected_court
from services.edge.perception.loop import Processed
from services.edge.ui.preview import draw_hud, draw_tracks


class HttpPreview:
    def __init__(
        self,
        port: int,
        state,
        hud,
        on_error=lambda error: None,
        raw_snapshot=lambda: None,
        calibration=None,
    ):
        self.port = port
        self.state = state
        self.hud = hud
        self.on_error = on_error
        self.raw_snapshot = raw_snapshot
        self.calibration = calibration
        self.court = None
        if calibration:
            court = calibration["court"]
            self.court = court_model(
                court["kind"], court["length_m"], court["width_m"], court["landmarks"]
            )
        self._failure_active = False
        self.pending: queue.Queue[Processed] = queue.Queue(maxsize=1)
        self.preview_dropped = 0
        self._stop = threading.Event()
        self._ready = threading.Condition()
        self._jpeg: bytes | None = None
        self._last_encoded = 0.0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/raw-snapshot.jpg":
                    image = owner.raw_snapshot()
                    if image is None:
                        self.send_error(503, "raw capture frame not ready")
                        return
                    ok, encoded = cv2.imencode(".jpg", image)
                    if not ok:
                        self.send_error(503, "raw snapshot encoding failed")
                        return
                    payload = encoded.tobytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if self.path == "/status.json":
                    hud = owner.hud()
                    payload = json.dumps(
                        {
                            "health": owner.state(),
                            "capture_fps": hud.capture_fps,
                            "processed_fps": hud.proc_fps,
                            "people": hud.people,
                            "tracks": hud.tracks,
                            "drops": hud.dropped,
                            "preview_drops": owner.preview_dropped,
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if self.path not in ("/snapshot.jpg", "/mjpeg"):
                    self.send_error(404)
                    return
                if self.path == "/snapshot.jpg":
                    with owner._ready:
                        owner._ready.wait_for(lambda: owner._jpeg is not None, timeout=5)
                        payload = owner._jpeg
                    if payload is None:
                        self.send_error(503, "preview not ready")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(200)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while not owner._stop.is_set():
                        with owner._ready:
                            owner._ready.wait(timeout=0.2)
                            payload = owner._jpeg
                        if payload is not None:
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                            self.wfile.write(payload + b"\r\n")
                            self.wfile.flush()
                            time.sleep(0.2)
                except OSError:
                    pass

            def log_message(self, fmt, *args):
                return

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.server.daemon_threads = True
        self._http_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._worker = threading.Thread(target=self._encode, name="preview-encoder", daemon=True)

    def start(self):
        self._http_thread.start()
        self._worker.start()

    def publish(self, item: Processed):
        try:
            self.pending.put_nowait(item)
        except queue.Full:
            try:
                self.pending.get_nowait()
                self.preview_dropped += 1
            except queue.Empty:
                pass
            try:
                self.pending.put_nowait(item)
            except queue.Full:
                pass

    def _encode(self):
        while not self._stop.is_set():
            try:
                item = self.pending.get(timeout=0.1)
            except queue.Empty:
                continue
            delay = 0.2 - (time.monotonic() - self._last_encoded)
            if delay > 0:
                time.sleep(delay)
            try:
                image = draw_tracks(item.frame.image, item.tracks)
                if self.calibration:
                    image = draw_projected_court(
                        image, self.calibration["homography_image_to_court"], self.court
                    )
                image = draw_hud(image, self.state(), self.hud())
                width = image.shape[1]
                if width > 640:
                    height = max(1, round(image.shape[0] * 640 / width))
                    image = cv2.resize(image, (640, height), interpolation=cv2.INTER_AREA)
                ok, encoded = cv2.imencode(".jpg", image)
                if not ok:
                    raise RuntimeError("OpenCV could not encode the annotated frame as JPEG")
                with self._ready:
                    self._jpeg = encoded.tobytes()
                    self._last_encoded = time.monotonic()
                    self._ready.notify_all()
                self._failure_active = False
            except Exception as error:
                if not self._failure_active:
                    self.on_error(error)
                    self._failure_active = True

    def close(self):
        self._stop.set()
        self.server.shutdown()
        self.server.server_close()
        self._http_thread.join(timeout=2)
        self._worker.join(timeout=2)
