"""Read and validate the small runtime subset of a saved calibration document."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from services.edge.calibration.court import court_model
from services.edge.calibration.homography import (
    check_homography,
    check_point_set,
    normalize_homography_sign,
    point_residuals,
)
from services.edge.contract import CONTRACT_VERSION

# Versions of this file format the loader accepts. A later contract bump that leaves the
# calibration format unchanged adds the previous version here, so saved calibrations stay usable;
# a bump that changes it does not, and the old files are refused with a clear message.
ACCEPTED_VERSIONS = (CONTRACT_VERSION, "0.8.0")
_SCHEMA = Path(__file__).with_name("calibration.schema.json")


def _schema_errors(document):
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    # as it will be written: tuples become arrays, and NaN or infinity are not JSON (ValueError)
    as_json = json.loads(json.dumps(document, allow_nan=False))
    errors = sorted(Draft202012Validator(schema).iter_errors(as_json), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or 'calibration'}: {e.message}" for e in errors[:5]]


def validate_calibration(document):
    """Raise ValueError unless `document` passes calibration.schema.json and the checks a
    schema cannot make: the homography is usable, the points hold out, and the stored errors
    match the points. A document that passes can be loaded by every consumer (recording,
    report, preview); a file that does not pass is refused here, not later inside one of them."""
    if not isinstance(document, dict) or document.get("contract_version") not in ACCEPTED_VERSIONS:
        raise ValueError(
            f"calibration must use contract version {' or '.join(ACCEPTED_VERSIONS)}, "
            f"not {document.get('contract_version') if isinstance(document, dict) else None!r}"
        )
    # an older accepted version is checked against the current schema as if it were current
    problems = _schema_errors({**document, "contract_version": CONTRACT_VERSION})
    if problems:
        raise ValueError(
            "calibration does not match calibration.schema.json: " + "; ".join(problems)
        )
    court = document["court"]
    court_model(court["kind"], court["length_m"], court["width_m"], court["landmarks"])
    points = document["points"]
    homography = normalize_homography_sign(
        document["homography_image_to_court"], [p["image_px"] for p in points]
    )
    document = {**document, "homography_image_to_court": homography.tolist()}
    check_homography(homography, [p["image_px"] for p in points])
    check_point_set(points)
    _check_recomputed_errors(document, homography, points)
    return document


def _check_recomputed_errors(document, homography, points, tolerance=1e-6):
    """The per-point residuals, the mean errors and the forced flag are recomputed from the
    homography and the points: a stored value that disagrees (or a check point that was never
    held out) means the file was edited or written by a buggy writer."""
    residuals = point_residuals(homography, points)
    for stored, recomputed in zip((p["residual_m"] for p in points), residuals, strict=True):
        if abs(stored - recomputed) > tolerance:
            raise ValueError("calibration point residual does not match the homography")
    fit = [r for r, p in zip(residuals, points, strict=True) if p["role"] == "calibration"]
    check = [r for r, p in zip(residuals, points, strict=True) if p["role"] == "check"]
    expected = {
        "calibration_mean_m": sum(fit) / len(fit),
        "check_mean_m": sum(check) / len(check),
        "check_max_m": max(check),
    }
    for key, value in expected.items():
        stored = document["errors"].get(key)
        if not isinstance(stored, (int, float)) or abs(stored - value) > tolerance:
            raise ValueError(f"calibration {key} does not match the points and homography")
    if document["forced"] != (expected["check_mean_m"] > document["max_check_error_m"]):
        raise ValueError("calibration forced flag does not match its check error and limit")


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
