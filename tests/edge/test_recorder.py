"""Phase 04 recorder: raw frames to video.mp4 off the capture thread (RF08, RF09, RNF04).

Phase 04 A1 (frame count), A2 (no annotations), A5 (sha256)."""

import hashlib
import threading
import time

import cv2
import numpy as np
import pytest

from services.edge.capture.types import Frame, SourceInfo
from services.edge.recording.recorder import FileRecorder
from services.edge.recording.types import Recorder

INFO = SourceInfo("file", "fake", 64, 48, 10.0)


def frame(seq: int) -> Frame:
    image = np.full((48, 64, 3), 90, np.uint8)
    cv2.rectangle(image, (4 + 2 * seq, 10), (24 + 2 * seq, 30), (0, 0, 255), -1)
    return Frame(seq, time.perf_counter(), "2026-10-19T12:00:00Z", image, "fake")


def video_frames(path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, image = cap.read()
        if not ok:
            break
        out.append(image)
    cap.release()
    return out


def test_is_a_recorder():
    assert isinstance(FileRecorder(), Recorder)


def test_A1_video_has_every_written_frame(tmp_path):
    rec = FileRecorder()
    rec.start(tmp_path / "video.mp4", INFO)
    for i in range(20):
        rec.write(frame(i))
    info = rec.stop()
    assert (info.frames_written, info.frames_dropped) == (20, 0)
    assert len(video_frames(info.path)) == 20


def test_A2_frames_are_raw(tmp_path):
    """The video holds the source pixels: no box, no HUD (RF09). A lossy codec moves values a
    little, so compare with a tolerance far below what a drawn box would change."""
    rec = FileRecorder()
    rec.start(tmp_path / "video.mp4", INFO)
    source = frame(3)
    rec.write(source)
    info = rec.stop()
    (decoded,) = video_frames(info.path)
    assert decoded.shape == source.image.shape
    assert np.abs(decoded.astype(int) - source.image.astype(int)).mean() < 6


def test_A5_sha256_is_the_files(tmp_path):
    rec = FileRecorder()
    rec.start(tmp_path / "video.mp4", INFO)
    rec.write(frame(0))
    info = rec.stop()
    assert info.sha256 == hashlib.sha256(info.path.read_bytes()).hexdigest()


def test_t_video_is_the_frame_position_in_the_video(tmp_path):
    rec = FileRecorder()
    rec.start(tmp_path / "video.mp4", INFO)
    for seq in (0, 1, 5, 6):  # seq 2-4 were never offered, e.g. failed reads
        rec.write(frame(seq))
    assert [rec.t_video(s) for s in (0, 1, 5, 6)] == pytest.approx([0.0, 0.1, 0.2, 0.3])
    assert rec.t_video(3) is None  # not in the video
    rec.stop()


def test_unknown_fps_falls_back_to_30(tmp_path):
    rec = FileRecorder()
    rec.start(tmp_path / "video.mp4", SourceInfo("camera", "1", 64, 48, None))
    rec.write(frame(0))
    rec.write(frame(1))
    assert rec.t_video(1) == pytest.approx(1 / 30)
    rec.stop()


class GatedWriter:
    """A writer that blocks until released, so the queue fills."""

    def __init__(self):
        self.gate = threading.Event()
        self.written = 0

    def write(self, image):
        self.gate.wait(5)
        self.written += 1

    def release(self):
        pass


def test_full_queue_drops_and_counts_never_blocks(tmp_path):
    writer = GatedWriter()
    rec = FileRecorder(max_queue=2, writer_factory=lambda path, fps, size: writer)
    rec.start(tmp_path / "video.mp4", INFO)
    t = time.perf_counter()
    for i in range(10):
        rec.write(frame(i))
    assert time.perf_counter() - t < 1.0, "write() blocked the capture thread"
    writer.gate.set()
    info = rec.stop()
    assert info.frames_dropped > 0
    assert info.frames_written + info.frames_dropped == 10
    assert writer.written == info.frames_written
    # a dropped frame has no position in the video
    assert sum(rec.t_video(i) is None for i in range(10)) == info.frames_dropped


def test_stop_without_frames_leaves_no_file(tmp_path):
    rec = FileRecorder()
    rec.start(tmp_path / "video.mp4", INFO)
    info = rec.stop()
    assert (info.frames_written, info.sha256) == (0, "")
    assert not (tmp_path / "video.mp4").exists()
