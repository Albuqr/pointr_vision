"""A1: file source reads every frame in order; open_source dispatch and errors."""

import os
import time

import cv2
import numpy as np
import pytest

from fixtures.make_clips import FPS, HEIGHT, N_FRAMES, WIDTH, scene
from services.edge.capture.sources import (
    CameraSource,
    FileSource,
    SourceEnded,
    SourceOpenError,
    StreamSource,
    open_source,
)
from services.edge.capture.types import SourceInfo


def read_all(source) -> list:
    frames = []
    while True:
        try:
            frame = source.read()
        except SourceEnded:
            return frames
        assert frame is not None, "a file read failed before the end"
        frames.append(frame)


@pytest.mark.parametrize("name", ["moving", "moving_mov"])
def test_file_reads_every_frame_in_order(clips, name):
    source = FileSource(clips[name], realtime=False)
    info = source.open()
    try:
        frames = read_all(source)
    finally:
        source.close()
    assert info == SourceInfo("file", str(clips[name]), WIDTH, HEIGHT, FPS, None)
    assert len(frames) == N_FRAMES
    assert [f.seq for f in frames] == list(range(N_FRAMES))
    assert all(a.t_recv <= b.t_recv for a, b in zip(frames, frames[1:], strict=False))
    scenes = [scene(i).astype(int) for i in range(N_FRAMES)]
    for i, frame in enumerate(frames):  # frame i is closest to scene i: right content, in order
        diffs = [np.abs(frame.image.astype(int) - s).mean() for s in scenes]
        assert int(np.argmin(diffs)) == i


def test_file_realtime_is_paced_to_its_fps(clips):
    source = FileSource(clips["moving"])
    source.open()
    start = time.perf_counter()
    try:
        assert len(read_all(source)) == N_FRAMES
    finally:
        source.close()
    assert time.perf_counter() - start >= 0.9 * (N_FRAMES - 1) / FPS


def test_open_source_dispatch(clips, tmp_path):
    assert isinstance(open_source("0"), CameraSource)
    assert isinstance(open_source("1"), CameraSource)
    assert isinstance(open_source("http://192.168.0.5:8080/video"), StreamSource)
    assert isinstance(open_source("rtsp://cam/stream"), StreamSource)
    assert isinstance(open_source(str(clips["moving"])), FileSource)
    mov = tmp_path / "clip.MOV"
    mov.write_bytes(b"")
    assert isinstance(open_source(str(mov)), FileSource)


def test_stream_capture_disables_ffmpeg_redirects(monkeypatch):
    captured = {}

    def video_capture(ref, backend, params):
        captured["options"] = os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]
        captured["ref"] = ref
        captured["backend"] = backend
        captured["params"] = params
        return object()

    monkeypatch.setenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|max_redirects;4")
    monkeypatch.setattr(cv2, "VideoCapture", video_capture)
    StreamSource("http://192.0.2.1/video")._new_capture()
    assert captured["options"] == "rtsp_transport;tcp|max_redirects;0"
    assert captured["ref"] == "http://192.0.2.1/video"


@pytest.mark.parametrize(
    "name,reason",
    [
        ("missing.mp4", "file not found"),
        ("notes.txt", "unsupported file type"),
        ("not-a-source", "not a camera index"),
    ],
)
def test_open_source_rejects(tmp_path, name, reason):
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(SourceOpenError, match=reason):
        open_source(str(tmp_path / name) if name != "not-a-source" else name)


def test_corrupt_file_fails_on_open(tmp_path):
    bad = tmp_path / "corrupt.mp4"
    bad.write_bytes(b"this is not a video")
    with pytest.raises(SourceOpenError, match="did not open"):
        open_source(str(bad)).open()


class FakeCap:
    """Stands in for cv2.VideoCapture: n_good frames, then failed reads."""

    def __init__(self, n_good: int):
        self.n_good = n_good

    def isOpened(self):  # noqa: N802 - cv2 name
        return True

    def get(self, prop):
        return 0.0

    def read(self):
        if self.n_good:
            self.n_good -= 1
            return True, np.zeros((4, 4, 3), np.uint8)
        return False, None

    def release(self):
        pass


class ScriptedCamera(CameraSource):
    reopen_after = 0.0

    def __init__(self, caps):
        super().__init__(0)
        self._caps = iter(caps)
        self.opened = 0

    def _new_capture(self):
        self.opened += 1
        return next(self._caps)


def test_live_source_reopens_after_failures():
    """A device that comes back is reopened and delivers again (A8 recovery path)."""
    camera = ScriptedCamera([FakeCap(1), FakeCap(5)])
    info = camera.open()
    assert (info.width, info.height, info.reported_fps) == (None, None, None)  # 0 -> None
    reads = [camera.read() for _ in range(4)]
    assert [r is not None for r in reads] == [True, False, False, True]
    assert camera.opened == 2
    assert (reads[0].seq, reads[3].seq) == (0, 3)  # gaps in seq mark the failed reads


def test_live_source_waits_before_reopening():
    camera = ScriptedCamera([FakeCap(0), FakeCap(5)])
    camera.reopen_after = 60.0
    camera.open()
    assert [camera.read() for _ in range(5)] == [None] * 5
    assert camera.opened == 1


class SizedCap(FakeCap):
    """A camera that accepts a size request but delivers its own, like many webcams."""

    def __init__(self, index, api):
        super().__init__(n_good=0)
        self.index, self.api, self.sets = index, api, {}
        SizedCap.made.append(self)

    def set(self, prop, value):
        self.sets[prop] = value
        return True

    def get(self, prop):
        return {cv2.CAP_PROP_FRAME_WIDTH: 640.0, cv2.CAP_PROP_FRAME_HEIGHT: 480.0}.get(prop, 0.0)


def test_camera_requests_size_and_reports_what_it_delivers(monkeypatch):
    SizedCap.made = []
    monkeypatch.setattr(cv2, "VideoCapture", SizedCap)
    camera = CameraSource(1, size=(1280, 720))
    camera.reopen_after = 0.0
    info = camera.open()
    assert (info.width, info.height) == (640, 480)  # delivered, not requested
    camera.read(), camera.read()  # failed reads: the second one reopens
    assert len(SizedCap.made) == 2
    for cap in SizedCap.made:  # requested on the first open and on the reopen
        assert (cap.index, cap.api) == (1, cv2.CAP_ANY)
        assert cap.sets == {cv2.CAP_PROP_FRAME_WIDTH: 1280, cv2.CAP_PROP_FRAME_HEIGHT: 720}


def test_camera_requests_configured_fps_cap(monkeypatch):
    SizedCap.made = []
    monkeypatch.setattr(cv2, "VideoCapture", SizedCap)
    camera = CameraSource(1, fps_cap=24)
    camera.open()
    assert SizedCap.made[0].sets[cv2.CAP_PROP_FPS] == 24


def test_camera_without_size_requests_nothing(monkeypatch):
    SizedCap.made = []
    monkeypatch.setattr(cv2, "VideoCapture", SizedCap)
    CameraSource(0).open()
    assert SizedCap.made[0].sets == {}


def test_open_source_passes_size_to_cameras_only(clips):
    camera = open_source("1", (1280, 720))
    assert camera.size == (1280, 720)
    assert not hasattr(open_source(str(clips["moving"]), (1280, 720)), "size")
