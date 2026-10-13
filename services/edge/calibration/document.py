"""Read and validate the small runtime subset of a saved calibration document."""

import json
import math
import re
import uuid
from pathlib import Path

from services.edge.calibration.homography import _matrix, check_homography

CONTRACT_VERSION = "0.8.0"


def validate_calibration(document):
    if not isinstance(document, dict) or document.get("contract_version") != CONTRACT_VERSION:
        raise ValueError(f"calibration must use contract version {CONTRACT_VERSION}")
    for key in (
        "calibration_id",
        "camera_id",
        "created_at",
        "court",
        "image_size",
        "homography_image_to_court",
        "points",
        "errors",
        "max_check_error_m",
        "forced",
        "audit_frame",
    ):
        if key not in document:
            raise ValueError(f"calibration is missing {key}")
    try:
        calibration_id = uuid.UUID(document["calibration_id"])
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("calibration id must be a UUIDv4") from exc
    if calibration_id.version != 4 or str(calibration_id) != document["calibration_id"]:
        raise ValueError("calibration id must be a canonical UUIDv4")
    if not isinstance(document["camera_id"], str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,32}", document["camera_id"]
    ):
        raise ValueError("calibration camera id is invalid")
    court = document["court"]
    size = document["image_size"]
    if not isinstance(court, dict) or not isinstance(size, dict):
        raise ValueError("calibration court and image_size must be objects")
    length, width = court.get("length_m"), court.get("width_m")
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
        for value in (length, width)
    ):
        raise ValueError("calibration court dimensions must be positive finite metres")
    if any(
        not isinstance(size.get(key), int) or isinstance(size[key], bool) or size[key] <= 0
        for key in ("width", "height")
    ):
        raise ValueError("calibration image dimensions must be positive integers")
    if court.get("kind") not in ("fiba_full", "custom"):
        raise ValueError("calibration court kind is invalid")
    threshold = document["max_check_error_m"]
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or threshold <= 0
    ):
        raise ValueError("calibration error limit must be finite and positive")
    _matrix(document["homography_image_to_court"])
    try:
        error = float(document["errors"]["check_mean_m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("calibration has no mean check error") from exc
    if (
        isinstance(document["errors"]["check_mean_m"], bool)
        or not math.isfinite(error)
        or error < 0
    ):
        raise ValueError("calibration check error must be finite and non-negative")
    points = document["points"]
    if not isinstance(points, list) or any(not isinstance(point, dict) for point in points):
        raise ValueError("calibration points must be a list of objects")
    if (
        sum(point.get("role") == "calibration" for point in points) < 4
        or sum(point.get("role") == "check" for point in points) < 2
    ):
        raise ValueError("calibration requires four fit points and two held-out points")
    for point in points:
        if point.get("role") not in ("calibration", "check"):
            raise ValueError("calibration point role is invalid")
        for key in ("image_px", "court_m"):
            values = point.get(key)
            if (
                not isinstance(values, list)
                or len(values) != 2
                or not all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    for value in values
                )
            ):
                raise ValueError(f"calibration point {key} must contain two finite values")
        residual = point.get("residual_m")
        if (
            not isinstance(residual, (int, float))
            or isinstance(residual, bool)
            or not math.isfinite(residual)
            or residual < 0
        ):
            raise ValueError("calibration point residual must be finite and non-negative")
    if document["audit_frame"] != "frame.jpg" or not isinstance(document["forced"], bool):
        raise ValueError("calibration audit frame or forced flag is invalid")
    check_homography(document["homography_image_to_court"], [p["image_px"] for p in points])
    return document


def load_calibration(path: str | Path):
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read calibration file: {exc}") from exc
    return validate_calibration(document)


def run_calibration(document):
    """Persist the projection and provenance needed for offline report regeneration."""
    if document is None:
        return None
    return {
        "calibration_id": document["calibration_id"],
        "check_error_m": document["errors"]["check_mean_m"],
        "homography_image_to_court": document["homography_image_to_court"],
        "court": {
            "length_m": document["court"]["length_m"],
            "width_m": document["court"]["width_m"],
        },
        "image_size": document["image_size"],
    }
