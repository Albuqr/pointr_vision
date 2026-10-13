import queue
import socket
import threading
import time
import urllib.request

import cv2
import numpy as np

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
        with urllib.request.urlopen(f"http://127.0.0.1:{preview.port}/snapshot.jpg") as response:
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
        with urllib.request.urlopen(
            f"http://127.0.0.1:{preview.port}/raw-snapshot.jpg"
        ) as response:
            assert response.headers["Content-Type"] == "image/jpeg"
            decoded = cv2.imdecode(np.frombuffer(response.read(), np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape[:2] == (42, 64)
    finally:
        preview.close()


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
