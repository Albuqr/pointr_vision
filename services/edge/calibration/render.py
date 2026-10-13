"""Render projected court markings without changing source frames."""

import cv2
import numpy as np

from services.edge.calibration.court import Court, court_lines
from services.edge.calibration.homography import _matrix, project_point


def projected_court_lines(homography, court: Court):
    """Court markings in image pixels. Points behind the camera or on its horizon have no
    image and are left out of their line."""
    inverse = np.linalg.inv(_matrix(homography))
    projected = []
    for line in court_lines(court):
        points = [project_point(inverse, point) for point in line]
        projected.append([point for point in points if point is not None])
    return projected


def draw_projected_court(image, homography, court: Court):
    out = image.copy()
    for line in projected_court_lines(homography, court):
        if len(line) < 2:
            continue
        points = np.rint(line).astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(out, [points], False, (60, 220, 180), 2, cv2.LINE_AA)
    return out
