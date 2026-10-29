import queue
import socket
import struct
import threading
import time

import cv2
import numpy as np

from services.app.server import preview_get
from services.edge.capture.types import Frame
from services.edge.perception.loop import Processed, Processor
from services.edge.perception.types import Detections
from services.edge.ui.http_preview import HttpPreview
from services.edge.ui.preview import HudInfo


def test_preview_endpoint_encodes_fake_frame_and_falls_back_on_busy_port():
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    occupied_port = blocker.getsockname()[1]
    preview = HttpPreview(occupied_port, lambda: "OK", lambda: HudInfo(0, 0, 0, 0, 0, 0))
    blocker.close()
    assert preview.port != occupied_port
    preview.start()
    try:
        frame = Frame(
            1,
            time.perf_counter(),
            "2026-01-01T00:00:00Z",
            np.zeros((80, 120, 3), np.uint8),
            "fake",
        )
        detections = Detections(
            np.empty((0, 4), np.float32), np.empty(0, np.float32), np.empty(0, np.int64)
        )
        preview.publish(Processed(frame, detections, [], 0.0, 0.0))
        deadline = time.monotonic() + 3
        while preview._jpeg is None and time.monotonic() < deadline:
            time.sleep(0.02)
        with preview_get(preview.port, "snapshot.jpg", timeout=5) as response:
            assert response.headers["Content-Type"] == "image/jpeg"
            assert response.read().startswith(b"\xff\xd8")
    finally:
        preview.close()


def test_raw_snapshot_endpoint_uses_a_copy_from_the_capture_provider():
    image = np.full((42, 64, 3), 180, np.uint8)
    preview = HttpPreview(
        0, lambda: "OK", lambda: HudInfo(0, 0, 0, 0, 0, 0), raw_snapshot=lambda: image.copy()
    )
    preview.start()
    try:
        with preview_get(preview.port, "raw-snapshot.jpg", timeout=5) as response:
            assert response.headers["Content-Type"] == "image/jpeg"
            decoded = cv2.imdecode(np.frombuffer(response.read(), np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape[:2] == (42, 64)
    finally:
        preview.close()


def test_calibration_overlay_is_only_used_at_the_saved_frame_size():
    calibration = {
        "image_size": {"width": 120, "height": 80},
        "court": {"kind": "custom", "length_m": 4.0, "width_m": 3.0, "landmarks": {}},
    }
    preview = HttpPreview(
        0, lambda: "OK", lambda: HudInfo(0, 0, 0, 0, 0, 0), calibration=calibration
    )
    assert preview._matches_calibration_size(np.zeros((80, 120, 3), np.uint8))
    assert not preview._matches_calibration_size(np.zeros((180, 320, 3), np.uint8))
    preview.server.server_close()


def test_publish_drops_old_results_without_waiting():
    preview = HttpPreview(0, lambda: "OK", lambda: HudInfo(0, 0, 0, 0, 0, 0))
    frame = Frame(1, 0.0, "2026-01-01T00:00:00Z", np.zeros((8, 8, 3), np.uint8), "fake")
    detections = Detections(
        np.empty((0, 4), np.float32), np.empty(0, np.float32), np.empty(0, np.int64)
    )
    result = Processed(frame, detections, [], 0.0, 0.0)
    preview.pending.put_nowait(result)
    start = time.perf_counter()
    for _ in range(1000):
        preview.publish(result)
    assert time.perf_counter() - start < 0.1
    assert preview.preview_dropped == 1000
    preview.server.server_close()


def test_processing_preview_hook_only_hands_off_the_unmodified_frame():
    image = np.zeros((8, 8, 3), np.uint8)
    frame = Frame(1, 0.0, "2026-01-01T00:00:00Z", image, "fake")
    frames = queue.Queue()
    frames.put(frame)
    source_done = threading.Event()
    source_done.set()
    received = []
    processor = Processor(
        frames, source_done, None, None, lambda event: None, on_preview=received.append
    )
    processor.start()
    assert processor.done.wait(2)
    assert processor.stop()
    assert received[0].frame.image is image


def preview_with_frame():
    preview = HttpPreview(0, lambda: "OK", lambda: HudInfo(0, 0, 0, 0, 0, 0))
    preview.start()
    frame = Frame(
        1, time.perf_counter(), "2026-01-01T00:00:00Z", np.zeros((80, 120, 3), np.uint8), "fake"
    )
    detections = Detections(
        np.empty((0, 4), np.float32), np.empty(0, np.float32), np.empty(0, np.int64)
    )
    preview.publish(Processed(frame, detections, [], 0.0, 0.0))
    deadline = time.monotonic() + 3
    while preview._jpeg is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return preview


def open_mjpeg(port: int, path: str = "/mjpeg") -> socket.socket:
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.sendall(f"GET {path} HTTP/1.0\r\n\r\n".encode())
    data = b""
    while b"--frame" not in data:  # the stream is running
        chunk = client.recv(65536)
        assert chunk, "the server closed the stream"
        data += chunk
    return client


def drop_abruptly(client: socket.socket) -> None:
    client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))  # RST
    client.close()


def test_b3_clients_that_leave_mid_stream_leave_no_traceback_and_others_keep_frames(capfd):
    preview = preview_with_frame()
    try:
        staying = open_mjpeg(preview.port)
        open_mjpeg(preview.port).close()  # a browser tab closed mid-stream
        drop_abruptly(open_mjpeg(preview.port))  # a dropped socket
        # connections that leave before or while a plain request is answered
        for path in ("/snapshot.jpg", "/status.json", "/raw-snapshot.jpg"):
            early = socket.create_connection(("127.0.0.1", preview.port), timeout=5)
            early.sendall(f"GET {path} HTTP/1.0\r\n\r\n".encode())
            drop_abruptly(early)
        drop_abruptly(socket.create_connection(("127.0.0.1", preview.port), timeout=5))
        time.sleep(1)  # let the server threads hit the dead sockets
        staying.settimeout(5)
        data = b""
        while data.count(b"--frame") < 2:  # frames still arrive after the others left
            data += staying.recv(65536)
        staying.close()
    finally:
        preview.close()
    captured = capfd.readouterr()
    assert "Traceback" not in captured.out + captured.err


def test_b3_a_client_leaving_is_one_readable_line(capfd):
    preview = preview_with_frame()
    try:
        client = open_mjpeg(preview.port)
        mine = f"127.0.0.1:{client.getsockname()[1]} "  # other tests' threads may still print
        drop_abruptly(client)
        time.sleep(1)
    finally:
        preview.close()
    captured = capfd.readouterr()
    lines = [line for line in (captured.out + captured.err).splitlines() if mine in line]
    assert len(lines) == 1
    assert lines[0].startswith("preview client ")


def test_b3_a_failure_that_is_not_a_client_leaving_still_shows_its_traceback(capfd):
    preview = HttpPreview(0, lambda: "OK", lambda: HudInfo(0, 0, 0, 0, 0, 0))
    try:
        raise ValueError("a real bug")
    except ValueError:
        preview.server.handle_error(None, ("127.0.0.1", 1))
    preview.server.server_close()
    assert "Traceback" in capfd.readouterr().err
