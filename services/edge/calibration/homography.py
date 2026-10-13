"""Homography fitting and coordinate conversions, independent of file/camera state."""

import math

import cv2
import numpy as np


def _matrix(value):
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("homography must be a finite 3 x 3 matrix")
    return matrix


def project_image_to_court(homography, point):
    matrix = _matrix(homography)
    result = cv2.perspectiveTransform(np.asarray([[point]], dtype=np.float64), matrix)[0, 0]
    if not np.isfinite(result).all():
        raise ValueError("image point projects to infinity")
    return float(result[0]), float(result[1])


def project_court_to_image(homography, point):
    return project_image_to_court(np.linalg.inv(_matrix(homography)), point)


def fit_calibration(
    points, max_check_error_m=0.5, save_anyway=False, enforce_limit=True, require_checks=True
):
    if not isinstance(points, list):
        raise ValueError("calibration points must be a list")
    for point in points:
        if not isinstance(point, dict) or point.get("role") not in ("calibration", "check"):
            raise ValueError("each point role must be calibration or check")
        for key in ("image_px", "court_m"):
            values = np.asarray(point.get(key), dtype=np.float64)
            if values.shape != (2,) or not np.isfinite(values).all():
                raise ValueError(f"each point {key} must contain two finite coordinates")
    fit = [point for point in points if point["role"] == "calibration"]
    checks = [point for point in points if point["role"] == "check"]
    if len(fit) < 4:
        raise ValueError("at least four calibration points are required")
    if require_checks and len(checks) < 2:
        raise ValueError("at least two separate check points are required")
    if not math.isfinite(max_check_error_m) or max_check_error_m <= 0:
        raise ValueError("maximum check error must be finite and greater than zero")
    image_points = np.asarray([point["image_px"] for point in fit], dtype=np.float64)
    court_points = np.asarray([point["court_m"] for point in fit], dtype=np.float64)
    if image_points.shape != (len(fit), 2) or court_points.shape != (len(fit), 2):
        raise ValueError("each calibration point must contain two image and court coordinates")
    if not np.isfinite(image_points).all() or not np.isfinite(court_points).all():
        raise ValueError("calibration coordinates must be finite")
    homography, inliers = cv2.findHomography(
        image_points, court_points, cv2.RANSAC, ransacReprojThreshold=0.1
    )
    if homography is None or inliers is None or int(inliers.sum()) < 4:
        raise ValueError("RANSAC could not fit four inlier calibration points")
    homography = _matrix(homography)

    def residual(point):
        projected = project_image_to_court(homography, point["image_px"])
        return math.hypot(projected[0] - point["court_m"][0], projected[1] - point["court_m"][1])

    fit_errors = [residual(point) for point in fit]
    check_errors = [residual(point) for point in checks]
    check_mean = float(np.mean(check_errors)) if check_errors else None
    check_max = max(check_errors) if check_errors else None
    if (
        enforce_limit
        and check_mean is not None
        and check_mean > max_check_error_m
        and not save_anyway
    ):
        raise ValueError(
            f"mean check error {check_mean:.3f} m exceeds {max_check_error_m:.3f} m; "
            "enable Save anyway to override the error limit"
        )
    return {
        "homography_image_to_court": homography.tolist(),
        "calibration_errors_m": fit_errors,
        "check_errors_m": check_errors,
        "calibration_mean_m": float(np.mean(fit_errors)),
        "check_mean_m": check_mean,
        "check_max_m": check_max,
        "forced": bool(save_anyway and check_mean is not None and check_mean > max_check_error_m),
    }


class CalibrationPositions:
    unit = "m"
    calibrated = True

    def __init__(self, calibration, stationary_below=0.5, walking_below=2.5):
        self.calibration = calibration
        self.calibration_id = calibration["calibration_id"]
        self.check_error_m = calibration.get(
            "check_error_m", calibration.get("errors", {}).get("check_mean_m")
        )
        self.length_m = calibration["court"]["length_m"]
        self.width_m = calibration["court"]["width_m"]
        self.stationary_below = stationary_below
        self.walking_below = walking_below

    def __call__(self, x, y):
        return project_image_to_court(self.calibration["homography_image_to_court"], (x, y))

    def in_court(self, x, y):
        return 0 <= x <= self.length_m and 0 <= y <= self.width_m
