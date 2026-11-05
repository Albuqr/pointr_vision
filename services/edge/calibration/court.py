"""Court-coordinate models, origin at the diagram's near-left corner (x along the length, y along
the width). One table of landmarks and one list of lines, used by the fit, the saved file, the
preview overlay and the Studio diagram, so a click on a drawn feature gives the right metres.

Markings with a fixed size on a real court (key depth and width, centre circle, basket offset)
keep that size on a custom court; only the court's own dimensions change them. A marking that does
not fit the court (a key on a court narrower than 4.9 m) is left out, with its landmarks."""

import math
from dataclasses import dataclass

FIBA_LENGTH_M, FIBA_WIDTH_M = 28.0, 15.0
FIBA_HALF_LENGTH_M = 14.0
KEY_DEPTH_M = 5.8  # baseline to the free-throw line
KEY_WIDTH_M = 4.9  # lane width, centred on the court's width (FIBA: y 5.05 to 9.95 of 15)
BASKET_OFFSET_M = 1.575  # baseline to the floor point under the basket
CIRCLE_RADIUS_M = 1.8  # centre circle


@dataclass(frozen=True)
class Court:
    kind: str
    length_m: float
    width_m: float
    landmarks: dict[str, tuple[float, float]]


def _has_keys(length_m: float, width_m: float) -> bool:
    return width_m >= KEY_WIDTH_M and length_m >= 2 * KEY_DEPTH_M


def _has_circle(length_m: float, width_m: float) -> bool:
    diameter = 2 * CIRCLE_RADIUS_M
    return length_m >= diameter and width_m >= diameter


def court_model(kind="fiba_full", length_m=28.0, width_m=15.0, custom_landmarks=None):
    if kind not in ("fiba_full", "fiba_half", "custom"):
        raise ValueError("court kind must be fiba_full, fiba_half or custom")
    if not (math.isfinite(length_m) and math.isfinite(width_m)) or length_m <= 0 or width_m <= 0:
        raise ValueError("court length and width must be greater than zero")
    if kind == "fiba_full" and (length_m != FIBA_LENGTH_M or width_m != FIBA_WIDTH_M):
        raise ValueError("FIBA full court dimensions are 28 x 15 m; choose custom for other sizes")
    if kind == "fiba_half" and (length_m != FIBA_HALF_LENGTH_M or width_m != FIBA_WIDTH_M):
        raise ValueError("FIBA half court dimensions are 14 x 15 m; choose custom for other sizes")

    if kind == "fiba_half":
        full = court_model("fiba_full", FIBA_LENGTH_M, FIBA_WIDTH_M)
        landmarks = {
            name: point for name, point in full.landmarks.items() if point[0] <= FIBA_HALF_LENGTH_M
        }
        landmarks.update(
            {
                "midcourt_near_corner": (FIBA_HALF_LENGTH_M, 0.0),
                "midcourt_far_corner": (FIBA_HALF_LENGTH_M, FIBA_WIDTH_M),
                "midcourt_center": (FIBA_HALF_LENGTH_M, FIBA_WIDTH_M / 2),
            }
        )
        return Court(kind, FIBA_HALF_LENGTH_M, FIBA_WIDTH_M, landmarks)

    length, width, middle = float(length_m), float(width_m), width_m / 2
    landmarks = {
        "corner_near_left": (0.0, 0.0),
        "corner_far_left": (length, 0.0),
        "corner_far_right": (length, width),
        "corner_near_right": (0.0, width),
        "centre_line_left": (length / 2, 0.0),
        "centre_line_right": (length / 2, width),
        "centre_circle": (length / 2, middle),
    }
    if _has_keys(length, width):
        low, high = middle - KEY_WIDTH_M / 2, middle + KEY_WIDTH_M / 2
        far = length - KEY_DEPTH_M
        landmarks |= {
            "near_key_near_left": (0.0, low),
            "near_key_far_left": (KEY_DEPTH_M, low),
            "near_key_far_right": (KEY_DEPTH_M, high),
            "near_key_near_right": (0.0, high),
            "near_basket_floor": (BASKET_OFFSET_M, middle),
            "far_key_near_left": (far, low),
            "far_key_far_left": (length, low),
            "far_key_far_right": (length, high),
            "far_key_near_right": (far, high),
            "far_basket_floor": (length - BASKET_OFFSET_M, middle),
        }
    for name, point in (custom_landmarks or {}).items():
        if not isinstance(name, str) or len(point) != 2:
            raise ValueError("each custom landmark must have a name and an (x, y) point")
        x, y = map(float, point)
        if not (0 <= x <= length and 0 <= y <= width):
            raise ValueError(f"custom landmark {name!r} must be within the court dimensions")
        landmarks[name] = (x, y)
    return Court(kind, length, width, landmarks)


def court_lines(court: Court) -> list[list[tuple[float, float]]]:
    """Court boundary, centre line and circle, and lane/free-throw markings, in metres."""
    if court.kind == "fiba_half":
        low = court.width_m / 2 - KEY_WIDTH_M / 2
        high = court.width_m / 2 + KEY_WIDTH_M / 2
        return [
            [
                (0.0, 0.0),
                (court.length_m, 0.0),
                (court.length_m, court.width_m),
                (0.0, court.width_m),
                (0.0, 0.0),
            ],
            [(court.length_m, 0.0), (court.length_m, court.width_m)],
            [(0.0, low), (KEY_DEPTH_M, low), (KEY_DEPTH_M, high), (0.0, high)],
            [
                (
                    court.length_m + CIRCLE_RADIUS_M * math.cos(i * math.tau / 128),
                    court.width_m / 2 + CIRCLE_RADIUS_M * math.sin(i * math.tau / 128),
                )
                for i in range(32, 97)
            ],
        ]
    length, width, middle = court.length_m, court.width_m, court.width_m / 2
    lines = [
        [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width), (0.0, 0.0)],
        [(length / 2, 0.0), (length / 2, width)],
    ]
    if _has_keys(length, width):
        low, high = middle - KEY_WIDTH_M / 2, middle + KEY_WIDTH_M / 2
        far = length - KEY_DEPTH_M
        lines += [
            [(0.0, low), (KEY_DEPTH_M, low), (KEY_DEPTH_M, high), (0.0, high)],
            [(length, low), (far, low), (far, high), (length, high)],
        ]
    if _has_circle(length, width):
        lines.append(
            [
                (
                    length / 2 + CIRCLE_RADIUS_M * math.cos(i * math.tau / 64),
                    middle + CIRCLE_RADIUS_M * math.sin(i * math.tau / 64),
                )
                for i in range(65)
            ]
        )
    return lines
