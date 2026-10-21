"""Phase 04 recorder: raw frames to video.mkv off the capture thread (RF08, RF09, RNF04).

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
    rec.start(tmp_path / "video.mkv", INFO)
    for i in range(20):
        rec.write(frame(i))
    info = rec.stop()
    assert (info.frames_written, info.frames_dropped) == (20, 0)
    assert len(video_frames(info.path)) == 20


def test_A2_frames_are_raw(tmp_path):
    """The video holds the source pixels: no box, no HUD (RF09). A lossy codec moves values a
    little, so compare with a tolerance far below what a drawn box would change."""
    rec = FileRecorder()
    rec.start(tmp_path / "video.mkv", INFO)
    source = frame(3)
    rec.write(source)
    info = rec.stop()
    (decoded,) = video_frames(info.path)
    assert decoded.shape == source.image.shape
    assert np.abs(decoded.astype(int) - source.image.astype(int)).mean() < 6


def test_A5_sha256_is_the_files(tmp_path):
    rec = FileRecorder()
    rec.start(tmp_path / "video.mkv", INFO)
    rec.write(frame(0))
    info = rec.stop()
    assert info.sha256 == hashlib.sha256(info.path.read_bytes()).hexdigest()


def test_t_video_is_the_frame_position_in_the_video(tmp_path):
    rec = FileRecorder()
    rec.start(tmp_path / "video.mkv", INFO)
    for seq in (0, 1, 5, 6):  # seq 2-4 were never offered, e.g. failed reads
        rec.write(frame(seq))
    assert [rec.t_video(s) for s in (0, 1, 5, 6)] == pytest.approx([0.0, 0.1, 0.2, 0.3])
    assert rec.t_video(3) is None  # not in the video
    rec.stop()


def test_unknown_fps_falls_back_to_30(tmp_path):
    rec = FileRecorder()
    rec.start(tmp_path / "video.mkv", SourceInfo("camera", "1", 64, 48, None))
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
    rec.start(tmp_path / "video.mkv", INFO)
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
    rec.start(tmp_path / "video.mkv", INFO)
    info = rec.stop()
    assert (info.frames_written, info.sha256) == (0, "")
    assert not (tmp_path / "video.mkv").exists()


class FailingWriter:
    """Writes `ok` frames, then raises like a full disk or a lost codec."""

    def __init__(self, ok: int):
        self.ok = ok
        self.written = 0
        self.released = False

    def write(self, image):
        if self.written >= self.ok:
            raise OSError("disk full")
        self.written += 1

    def release(self):
        self.released = True


def test_failed_writer_leaves_no_time_for_frames_it_never_wrote(tmp_path):
    """A frame that is not in the file has no t_video, and every offered frame is accounted for:
    written, or dropped (the one that failed and the queued ones included)."""
    writer = FailingWriter(ok=3)
    rec = FileRecorder(writer_factory=lambda path, fps, size: writer)
    rec.start(tmp_path / "video.mkv", INFO)
    for i in range(20):
        rec.write(frame(i))
        time.sleep(0.002)
    info = rec.stop()
    assert isinstance(rec.error, OSError) and writer.released
    assert info.frames_written == 3
    assert info.frames_written + info.frames_dropped == 20
    in_file = [rec.t_video(i) for i in range(20)]
    assert [t is not None for t in in_file] == [True] * 3 + [False] * 17
    assert in_file[:3] == pytest.approx([0.0, 0.1, 0.2])


def test_frame_of_another_size_is_dropped_not_counted_as_written(tmp_path):
    """OpenCV silently skips a frame whose size differs from the file's (a stream reconnecting at
    another resolution): it must not take a position in the video."""
    rec = FileRecorder()
    rec.start(tmp_path / "video.mkv", INFO)
    for i in range(5):
        rec.write(frame(i))
    for i in range(5, 10):
        small = Frame(i, 0.0, "t", np.full((24, 32, 3), 50, np.uint8), "fake")
        rec.write(small)
    rec.write(frame(10))  # back to the first size: the next position in the video
    info = rec.stop()
    assert (info.frames_written, info.frames_dropped) == (6, 5)
    assert len(video_frames(info.path)) == 6
    assert [rec.t_video(i) for i in (5, 9)] == [None, None]
    assert rec.t_video(10) == pytest.approx(0.5)


def test_stop_is_bounded_when_the_writer_is_stuck(tmp_path):
    writer = GatedWriter()  # never released: a stalled disk
    rec = FileRecorder(max_queue=2, writer_factory=lambda p, f, s: writer, stop_timeout=0.5)
    rec.start(tmp_path / "video.mkv", INFO)
    for i in range(6):
        rec.write(frame(i))
    t = time.perf_counter()
    info = rec.stop()
    assert time.perf_counter() - t < 3.0, "stop() waited for a stuck writer"
    assert isinstance(rec.error, TimeoutError)
    assert info.sha256 == "", "an unfinished file must not get a hash"
    writer.gate.set()  # let the daemon thread end


def test_index_does_not_grow_without_bound(tmp_path, monkeypatch):
    from services.edge.recording import recorder as recorder_mod

    monkeypatch.setattr(recorder_mod, "INDEX_MAX", 10)
    rec = FileRecorder(writer_factory=lambda p, f, s: FailingWriter(10**6))
    rec.start(tmp_path / "video.mkv", INFO)
    for i in range(50):  # frames that capture drops never ask for their t_video
        rec.write(frame(i))
        time.sleep(0.001)
    rec.stop()
    assert rec.t_video(0) is None and rec.t_video(49) is not None


KILL_SCRIPT = """
import sys, time
import numpy as np
from services.edge.capture.types import Frame, SourceInfo
from services.edge.recording.recorder import FileRecorder
rec = FileRecorder()
rec.start(sys.argv[1], SourceInfo("file", "x", 320, 240, 30.0))
rng = np.random.default_rng(0)
i = 0
while True:
    image = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)  # camera-like: not flat
    rec.write(Frame(i, time.perf_counter(), "t", image, "x"))
    i += 1
    if i % 15 == 0:
        print(i, flush=True)
    time.sleep(0.02)
"""


def test_a_killed_session_leaves_a_readable_video(tmp_path):
    """NFR-004 / R-A1: the process is killed mid-recording (not stopped). An MP4 from OpenCV would
    have no index and not open at all; the MKV opens and holds most of what was written."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    path = tmp_path / "video.mkv"
    proc = subprocess.Popen(
        [sys.executable, "-c", KILL_SCRIPT, str(path)],
        cwd=root,
        stdout=subprocess.PIPE,
        text=True,
    )
    printed = 0
    while printed < 120:  # about 2.5 s of video
        printed = int(proc.stdout.readline())
    proc.kill()
    proc.wait(10)
    readable = len(video_frames(path))
    assert readable > printed * 0.5, f"{readable} frames readable of {printed}+ written"
