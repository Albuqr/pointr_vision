"""A1: file source reads every frame in order; open_source dispatch and errors."""

import time

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


def test_file_reads_every_frame_in_order(clips):
    source = FileSource(clips["moving"], realtime=False)
    info = source.open()
    try:
        frames = read_all(source)
    finally:
        source.close()
    assert info == SourceInfo("file", str(clips["moving"]), WIDTH, HEIGHT, FPS, None)
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
    start = time.monotonic()
    try:
        assert len(read_all(source)) == N_FRAMES
    finally:
        source.close()
    assert time.monotonic() - start >= 0.9 * (N_FRAMES - 1) / FPS


def test_open_source_dispatch(clips, tmp_path):
    assert isinstance(open_source("0"), CameraSource)
    assert isinstance(open_source("1"), CameraSource)
    assert isinstance(open_source("http://192.168.0.5:8080/video"), StreamSource)
    assert isinstance(open_source("rtsp://cam/stream"), StreamSource)
    assert isinstance(open_source(str(clips["moving"])), FileSource)
    mov = tmp_path / "clip.MOV"
    mov.write_bytes(b"")
    assert isinstance(open_source(str(mov)), FileSource)


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
