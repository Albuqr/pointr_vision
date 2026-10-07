"""A3: the fixture script generates the three clips and OpenCV can read them."""

import cv2
import numpy as np
import pytest

from fixtures.make_clips import HEIGHT, N_FRAMES, STEP, WIDTH


def read_all(path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    assert cap.isOpened(), f"OpenCV cannot open {path}"
    frames = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        cap.release()
    return frames


def mean_abs_diffs(frames: list[np.ndarray]) -> list[float]:
    return [float(cv2.absdiff(a, b).mean()) for a, b in zip(frames, frames[1:], strict=False)]


def red_centroid_x(frame: np.ndarray) -> float:
    b, g, r = (frame[..., c].astype(int) for c in range(3))
    xs = np.nonzero((r > 150) & (g < 100) & (b < 100))[1]
    assert xs.size, "red box not found"
    return float(xs.mean())


@pytest.mark.parametrize("name", ["moving", "black", "frozen"])
def test_clip_readable(clips, name):
    path = clips[name]
    assert path.suffix == ".mp4" and path.stat().st_size > 0
    frames = read_all(path)
    assert len(frames) == N_FRAMES
    assert all(f.shape == (HEIGHT, WIDTH, 3) and f.dtype == np.uint8 for f in frames)


def test_black_clip_is_black(clips):
    assert max(float(f.mean()) for f in read_all(clips["black"])) < 2


def test_frozen_clip_does_not_change(clips):
    frames = read_all(clips["frozen"])
    assert min(float(f.mean()) for f in frames) > 40  # frozen, not dark
    assert max(mean_abs_diffs(frames)) < 1.0


def test_moving_clip_moves(clips):
    frames = read_all(clips["moving"])
    assert min(float(f.mean()) for f in frames) > 40  # moving, not dark
    assert min(mean_abs_diffs(frames)) > 0.5
    xs = [red_centroid_x(f) for f in frames]
    steps = np.diff(xs)
    assert np.allclose(steps, STEP, atol=2), steps
