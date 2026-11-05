"""Where a tracked box stands on the court: the one place that decides it.

A `Placer` turns a box and the size of the frame it came from into a `Placement`: the court
position, whether it is inside the court, or the reason there is none. The size rule (a
calibration only applies to frames of the size it was made at) and the bottom-centre formula live
here and nowhere else. The tracker (for the matcher) and the pipeline (for tracks.csv) both read
the same placement, so a box is projected once per frame; the writer only formats it.

This module imports nothing from the rest of `services.edge`, so any layer may import it.
"""

from dataclasses import dataclass
from typing import Protocol

OUTSIDE_VIEW = "outside the camera's view"  # the map returned no position for the point


class PositionMap(Protocol):
    """Image point -> court metres, for a calibrated camera. It may return None for a point that
    cannot be projected, and may raise: a `Placer` turns either into a reason."""

    calibration_id: str

    def __call__(self, x: float, y: float) -> tuple[float, float] | None: ...

    def in_court(self, x: float, y: float) -> bool: ...


def bottom_centre(box) -> tuple[float, float]:
    """The point of a box that stands on the floor: the middle of its bottom edge."""
    return (box[0] + box[2]) / 2, box[3]


@dataclass(frozen=True)
class Placement:
    """The verdict for one box. `xy` is the court position in metres, or None with `why` saying
    why there is none (absence is data: the row is still written). `in_court` is None exactly
    when `xy` is."""

    xy: tuple[float, float] | None
    in_court: bool | None
    why: str | None


class Placer:
    """One calibrated camera's box-to-position rule. `image_size` is (width, height) of the frame
    the calibration was made at."""

    def __init__(self, positions: PositionMap, image_size: tuple[int, int]):
        self._positions = positions
        self.image_size = (int(image_size[0]), int(image_size[1]))

    def size_problem(self, frame_size: tuple[int, int]) -> str | None:
        """Why the calibration does not apply to a frame of `frame_size` (width, height)."""
        if tuple(frame_size) == self.image_size:
            return None
        return (
            f"frame size {frame_size[0]}x{frame_size[1]} differs from the calibration image size "
            f"{self.image_size[0]}x{self.image_size[1]}"
        )

    def place(self, box, frame_size: tuple[int, int]) -> Placement:
        """Never raises: a map that fails, or a box it cannot read, is a placement with a reason."""
        problem = self.size_problem(frame_size)
        if problem:
            return Placement(None, None, problem)
        try:
            if len(box) != 4:
                raise ValueError("track box must have four coordinates")
            x, y = bottom_centre(tuple(float(value) for value in box))
            xy = self._positions(x, y)
            if xy is None:
                return Placement(None, None, OUTSIDE_VIEW)
            return Placement(xy, bool(self._positions.in_court(*xy)), None)
        except Exception as e:  # a projection failure is a missing position, not a dead run
            return Placement(None, None, repr(e))
