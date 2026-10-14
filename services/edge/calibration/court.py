"""Court-coordinate models, origin at the diagram's near-left corner."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Court:
    kind: str
    length_m: float
    width_m: float
    landmarks: dict[str, tuple[float, float]]


def court_model(kind="fiba_full", length_m=28.0, width_m=15.0, custom_landmarks=None):
    if kind not in ("fiba_full", "custom"):
        raise ValueError("court kind must be fiba_full or custom")
    if length_m <= 0 or width_m <= 0:
        raise ValueError("court length and width must be greater than zero")
    if kind == "fiba_full" and (length_m != 28.0 or width_m != 15.0):
        raise ValueError("FIBA full court dimensions are 28 x 15 m; choose custom for other sizes")

    sx, sy = length_m / 28.0, width_m / 15.0
    values = {
        "corner_near_left": (0.0, 0.0),
        "corner_far_left": (28.0, 0.0),
        "corner_far_right": (28.0, 15.0),
        "corner_near_right": (0.0, 15.0),
        "centre_line_left": (14.0, 0.0),
        "centre_line_right": (14.0, 15.0),
        "centre_circle": (14.0, 7.5),
        "near_key_near_left": (0.0, 5.05),
        "near_key_far_left": (5.8, 5.05),
        "near_key_far_right": (5.8, 9.95),
        "near_key_near_right": (0.0, 9.95),
        "near_basket_floor": (1.575, 7.5),
        "far_key_near_left": (22.2, 5.05),
        "far_key_far_left": (28.0, 5.05),
        "far_key_far_right": (28.0, 9.95),
        "far_key_near_right": (22.2, 9.95),
        "far_basket_floor": (26.425, 7.5),
    }
    landmarks = {name: (x * sx, y * sy) for name, (x, y) in values.items()}
    for name, point in (custom_landmarks or {}).items():
        if not isinstance(name, str) or len(point) != 2:
            raise ValueError("each custom landmark must have a name and an (x, y) point")
        x, y = map(float, point)
        if not (0 <= x <= length_m and 0 <= y <= width_m):
            raise ValueError(f"custom landmark {name!r} must be within the court dimensions")
        landmarks[name] = (x, y)
    return Court(kind, float(length_m), float(width_m), landmarks)


def court_lines(court: Court) -> list[list[tuple[float, float]]]:
    """Court boundary, centre line/circle and lane/free-throw markings in metres."""
    length, width = court.length_m, court.width_m
    sx, sy = length / 28.0, width / 15.0

    def scale(points):
        return [(x * sx, y * sy) for x, y in points]

    lines = [
        scale([(0, 0), (28, 0), (28, 15), (0, 15), (0, 0)]),
        scale([(14, 0), (14, 15)]),
        scale([(0, 5.05), (5.8, 5.05), (5.8, 9.95), (0, 9.95)]),
        scale([(22.2, 5.05), (28, 5.05), (28, 9.95), (22.2, 9.95)]),
        scale([(5.8, 5.05), (5.8, 9.95)]),
        scale([(22.2, 5.05), (22.2, 9.95)]),
    ]
    lines.append(
        [
            (
                14 * sx + 1.8 * sx * math.cos(i * math.tau / 64),
                7.5 * sy + 1.8 * sy * math.sin(i * math.tau / 64),
            )
            for i in range(65)
        ]
    )
    return lines
