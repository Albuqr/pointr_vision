"""Render projected court markings without changing source frames."""

import cv2
import numpy as np

from services.edge.calibration.court import Court, court_lines
from services.edge.calibration.homography import project_court_to_image


def projected_court_lines(homography, court: Court):
    projected = []
    for line in court_lines(court):
        points = [project_court_to_image(homography, point) for point in line]
        projected.append(points)
    return projected


def draw_projected_court(image, homography, court: Court):
    out = image.copy()
    for line in projected_court_lines(homography, court):
        points = np.rint(line).astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(out, [points], False, (60, 220, 180), 2, cv2.LINE_AA)
    return out
