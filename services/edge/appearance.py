"""A track's appearance descriptor (R2a 06, ADR 0007, D-061): clothing colour and box height.

Hand-built with OpenCV and numpy, no learned model. The cross-camera matcher uses it where court
position cannot decide (`matcher.py`); it holds no pixel position, so it never links by where a
box is in the image. Verified against opencv-python 5.0.0: `cv2.calcHist`, `cv2.normalize`,
`cv2.compareHist` with `HISTCMP_BHATTACHARYYA` (0 same, 1 disjoint).
"""

from dataclasses import dataclass

import cv2
import numpy as np

# HSV bins: hue, saturation, value. Value is kept so a black and a white kit differ.
_BINS = [8, 4, 4]
_RANGES = [0, 180, 0, 256, 0, 256]
# The parts of the box taken, as fractions of its height (upper: shirt, below the head; lower:
# shorts and legs) and of its width (the middle, less background).
_UPPER = (0.15, 0.5)
_LOWER = (0.5, 0.85)
_MIDDLE = (0.2, 0.8)


@dataclass(frozen=True, eq=False)  # numpy arrays: compared with distance(), not ==
class Appearance:
    upper: np.ndarray  # normalised HSV histogram of the upper part
    lower: np.ndarray
    height: float  # box height as a fraction of the frame height


def _hist(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, _BINS, _RANGES)
    return cv2.normalize(hist, hist, 1.0, 0.0, cv2.NORM_L1)


def describe(image: np.ndarray, xyxy) -> Appearance | None:
    """The descriptor of the box `xyxy` (pixels) in the BGR `image`; None when the box holds
    too few pixels to describe (outside the frame, or a part narrower than a pixel)."""
    h_img, w_img = image.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in xyxy)
    if not all(np.isfinite([x1, y1, x2, y2])) or x2 <= x1 or y2 <= y1 or h_img == 0:
        return None
    w, h = x2 - x1, y2 - y1

    def part(top: float, bottom: float) -> np.ndarray | None:
        cols = slice(max(int(x1 + w * _MIDDLE[0]), 0), min(int(x1 + w * _MIDDLE[1]), w_img))
        rows = slice(max(int(y1 + h * top), 0), min(int(y1 + h * bottom), h_img))
        crop = image[rows, cols]
        return _hist(crop) if crop.size else None

    upper, lower = part(*_UPPER), part(*_LOWER)
    if upper is None or lower is None:
        return None
    return Appearance(upper, lower, h / h_img)


def colour_distance(a: Appearance, b: Appearance) -> float:
    """Mean Bhattacharyya distance of the upper and of the lower histograms, 0 to 1."""
    return (
        cv2.compareHist(a.upper, b.upper, cv2.HISTCMP_BHATTACHARYYA)
        + cv2.compareHist(a.lower, b.lower, cv2.HISTCMP_BHATTACHARYYA)
    ) / 2


def height_diff(a: Appearance, b: Appearance) -> float:
    """Relative difference of the two box heights, |a - b| / max(a, b)."""
    return abs(a.height - b.height) / max(a.height, b.height)
