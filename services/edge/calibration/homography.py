"""Homography fitting and coordinate conversions, independent of file/camera state."""

import math

import cv2
import numpy as np


def _matrix(value):
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("homography must be a finite 3 x 3 matrix")
    return matrix


EPS_W = 1e-6  # a point whose homogeneous scale w is at or below this is on or beyond the horizon
RANSAC_THRESHOLD_M = 0.1  # a fit point farther than this from the fit is an outlier and is ignored
MAX_CHECK_ERROR_LIMIT_M = 2.0  # the largest "maximum mean check error" a user may set
COINCIDENT_COURT_M = 1e-6  # two points this close in court metres are the same physical mark
COINCIDENT_IMAGE_PX = 1.0  # ... or this close in the image
MIN_SPREAD = 0.1  # sqrt(minor / major variance) of the fit points, in the image and on the court
MIN_HALF_COURT_COVERAGE = 0.2  # fit-point bounding box / full 14 x 15 m half-court area
COND_LIMIT = 1e7  # a larger condition number is treated as singular or numerically unstable


def _divide(matrix, x, y):
    """Explicit homogeneous divide. None when the point has no valid image: w is not positive
    (cv2.perspectiveTransform returns (0, 0) there, which would read as a real position) or
    the result is not finite."""
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    with np.errstate(all="ignore"):
        # A homography is unchanged when multiplied by a non-zero scalar. Normalize by a
        # positive factor before applying EPS_W so equivalent matrix scales project identically.
        scale = float(np.max(np.abs(matrix)))
        if not math.isfinite(scale) or scale == 0:
            return None
        normalized = matrix / scale
        w = normalized[2, 0] * x + normalized[2, 1] * y + normalized[2, 2]
        if not math.isfinite(w) or w <= EPS_W:
            return None
        px = (normalized[0, 0] * x + normalized[0, 1] * y + normalized[0, 2]) / w
        py = (normalized[1, 0] * x + normalized[1, 1] * y + normalized[1, 2]) / w
    if not (math.isfinite(px) and math.isfinite(py)):
        return None
    return float(px), float(py)


def project_point(homography, point):
    """(x, y) after the homography, or None when the point cannot be projected."""
    try:
        matrix = _matrix(homography)
        x, y = float(point[0]), float(point[1])
    except (ValueError, TypeError, IndexError):
        return None
    return _divide(matrix, x, y)


def project_image_to_court(homography, point):
    result = project_point(homography, point)
    if result is None:
        raise ValueError("image point cannot be projected (on or beyond the horizon)")
    return result


def project_court_to_image(homography, point):
    return project_image_to_court(np.linalg.inv(_matrix(homography)), point)


def check_homography(homography, image_points=()):
    """Raise ValueError unless the matrix is finite, invertible, not ill-conditioned, and every
    given image point lies in front of the horizon. Used by fit and by validate: no override."""
    matrix = _matrix(homography)
    try:
        with np.errstate(all="ignore"):
            cond = float(np.linalg.cond(matrix))
    except np.linalg.LinAlgError:
        cond = math.inf
    if not math.isfinite(cond) or cond > COND_LIMIT:
        raise ValueError(
            f"homography is singular or ill-conditioned (condition number {cond:.3g}, "
            f"limit {COND_LIMIT:g}); the points do not define a usable floor mapping"
        )
    for point in image_points:
        if _divide(matrix, float(point[0]), float(point[1])) is None:
            raise ValueError("a calibration point lies on or beyond the horizon of the homography")


def normalize_homography_sign(homography, image_points):
    """Return an equivalent matrix with positive w at saved floor points, when all signs agree.

    Earlier writers could persist the same projective mapping with its arbitrary global sign
    reversed. Mixed signs still mean the saved points cross the horizon and are rejected by
    check_homography after normalization.
    """
    matrix = _matrix(homography)
    scale = float(np.max(np.abs(matrix)))
    if not math.isfinite(scale) or scale == 0:
        return matrix
    matrix = matrix / scale
    with np.errstate(all="ignore"):
        weights = [matrix[2, 0] * x + matrix[2, 1] * y + matrix[2, 2] for x, y in image_points]
    if weights and all(math.isfinite(w) and w < 0 for w in weights):
        matrix = -matrix
    return matrix


def point_residuals(homography, points):
    """Metres between each point's court position and its image position projected through the
    homography, in the order of `points`. Raises ValueError if a point cannot be projected."""
    out = []
    for point in points:
        x, y = project_image_to_court(homography, point["image_px"])
        out.append(math.hypot(x - point["court_m"][0], y - point["court_m"][1]))
    return out


def _spread(points):
    """sqrt(minor / major variance) of the points: 0 for collinear points or a point cloud with
    no extent, near 1 for points spread evenly over an area, small for a thin sliver."""
    array = np.asarray(points, dtype=np.float64)
    minor, major = np.linalg.eigvalsh(np.cov(array.T))
    return 0.0 if major <= 0 else float(math.sqrt(max(minor, 0.0) / major))


def check_point_set(points, court_dimensions=None):
    """Hold-out integrity. A check point only tests the fit if it is a different physical mark
    from every fit point, so no two points may coincide, and the fit points must be spread out
    (not collinear, not bunched) in the image and on the court. Raises ValueError."""
    for i, a in enumerate(points):
        for b in points[i + 1 :]:
            if math.dist(a["court_m"], b["court_m"]) <= COINCIDENT_COURT_M:
                raise ValueError(
                    f"two points are at the same court position {tuple(a['court_m'])}: a check "
                    "point must be a different floor mark from every calibration point"
                )
            if math.dist(a["image_px"], b["image_px"]) <= COINCIDENT_IMAGE_PX:
                raise ValueError(
                    f"two points are at the same image position {tuple(a['image_px'])}: a check "
                    "point must be a different floor mark from every calibration point"
                )
    fit = [point for point in points if point["role"] == "calibration"]
    for name, key in (("image", "image_px"), ("court", "court_m")):
        spread = _spread([point[key] for point in fit])
        if spread < MIN_SPREAD:
            raise ValueError(
                f"the calibration points are collinear or bunched together in the {name} "
                f"(spread {spread:.3f}, at least {MIN_SPREAD} needed): spread them over the floor"
            )
    if court_dimensions is not None and tuple(map(float, court_dimensions)) == (14.0, 15.0):
        court_points = np.asarray([point["court_m"] for point in fit], dtype=np.float64)
        area_fraction = (
            float(np.ptp(court_points[:, 0]) * np.ptp(court_points[:, 1])) / (14.0 * 15.0)
        )
        if area_fraction < MIN_HALF_COURT_COVERAGE:
            raise ValueError(
                f"fit points cover {area_fraction:.0%} of the half-court area; at least "
                f"{MIN_HALF_COURT_COVERAGE:.0%} coverage is required: fit points too close "
                "together, add the baseline corners or midcourt line points or measured floor marks"
            )


def fit_calibration(
    points, max_check_error_m=0.5, save_anyway=False, enforce_limit=True, require_checks=True,
    court_dimensions=None,
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
    if (
        not math.isfinite(max_check_error_m)
        or max_check_error_m <= 0
        or max_check_error_m > MAX_CHECK_ERROR_LIMIT_M
    ):
        raise ValueError(
            f"maximum check error must be greater than zero and at most {MAX_CHECK_ERROR_LIMIT_M} m"
        )
    check_point_set(points, court_dimensions)
    image_points = np.asarray([point["image_px"] for point in fit], dtype=np.float64)
    court_points = np.asarray([point["court_m"] for point in fit], dtype=np.float64)
    if image_points.shape != (len(fit), 2) or court_points.shape != (len(fit), 2):
        raise ValueError("each calibration point must contain two image and court coordinates")
    if not np.isfinite(image_points).all() or not np.isfinite(court_points).all():
        raise ValueError("calibration coordinates must be finite")
    homography, inliers = cv2.findHomography(
        image_points, court_points, cv2.RANSAC, ransacReprojThreshold=RANSAC_THRESHOLD_M
    )
    if homography is None or inliers is None or int(inliers.sum()) < 4:
        raise ValueError("RANSAC could not fit four inlier calibration points")
    homography = _matrix(homography)
    inlier = iter(bool(value) for value in inliers.ravel())
    dropped = [  # indices into `points` of fit points RANSAC left out of the fit
        index
        for index, point in enumerate(points)
        if point["role"] == "calibration" and not next(inlier)
    ]
    every_image_point = [point["image_px"] for point in fit + checks]
    with np.errstate(all="ignore"):
        scale = [homography[2, 0] * x + homography[2, 1] * y + homography[2, 2]
                 for x, y in every_image_point]  # fmt: skip
    if all(value < 0 for value in scale):  # the overall sign is arbitrary: make w positive
        homography = -homography
    check_homography(homography, every_image_point)

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
        "ransac_threshold_m": RANSAC_THRESHOLD_M,
        "ransac_dropped_points": dropped,
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
        try:  # a bad matrix must not stop a writer or a report: every point is then invalid
            self._matrix = _matrix(calibration["homography_image_to_court"])
            check_homography(self._matrix)  # a singular matrix would map every point to one place
        except ValueError:
            self._matrix = None

    def __call__(self, x, y):
        """(x_m, y_m), or None when the point cannot be projected."""
        return None if self._matrix is None else _divide(self._matrix, x, y)

    def in_court(self, x, y):
        return 0 <= x <= self.length_m and 0 <= y <= self.width_m
