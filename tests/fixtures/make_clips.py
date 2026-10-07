"""Generate synthetic test clips. No people, no real footage (CLAUDE.md rule 9).

Clips are created at test time; only this script is committed.

    python tests/fixtures/make_clips.py <out_dir>
"""

import sys
from pathlib import Path

import cv2
import numpy as np

WIDTH, HEIGHT = 640, 360
FPS = 15.0
N_FRAMES = 30
BACKGROUND = (90, 90, 90)  # mid grey, so moving/frozen clips are not "dark"
RED, BLUE = (0, 0, 255), (255, 0, 0)  # BGR
STEP = 10  # pixels per frame


def scene(i: int) -> np.ndarray:
    """Frame i of the moving scene: a red box moves right, a blue box moves down."""
    img = np.full((HEIGHT, WIDTH, 3), BACKGROUND, dtype=np.uint8)
    x = 20 + STEP * i
    cv2.rectangle(img, (x, 60), (x + 60, 140), RED, thickness=-1)
    y = 20 + STEP * i // 2
    cv2.rectangle(img, (450, y), (530, y + 50), BLUE, thickness=-1)
    return img


def write_clip(path: Path, frames: list[np.ndarray]) -> Path:
    writer = cv2.VideoWriter()
    if not writer.open(str(path), cv2.VideoWriter.fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT)):
        raise RuntimeError(f"OpenCV could not open a video writer for {path}")
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()
    return path


def make_clips(out_dir: Path) -> dict[str, Path]:
    """Write moving.mp4, black.mp4 and frozen.mp4 into out_dir; return their paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    black = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    still = scene(0)
    return {
        "moving": write_clip(out_dir / "moving.mp4", [scene(i) for i in range(N_FRAMES)]),
        "black": write_clip(out_dir / "black.mp4", [black] * N_FRAMES),
        "frozen": write_clip(out_dir / "frozen.mp4", [still] * N_FRAMES),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for name, path in make_clips(Path(sys.argv[1])).items():
        print(f"{name}: {path}")
