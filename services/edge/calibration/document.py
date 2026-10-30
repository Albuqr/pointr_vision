"""Read and validate the small runtime subset of a saved calibration document."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from services.edge import contract
from services.edge.calibration.court import court_model
from services.edge.calibration.homography import (
    check_homography,
    check_point_set,
    normalize_homography_sign,
    point_residuals,
)
from services.edge.contract import CONTRACT_VERSION, accepts_calibration


def _schema_errors(document):
    schema = contract.schema("calibration")
    # as it will be written: tuples become arrays, and NaN or infinity are not JSON (ValueError)
    as_json = json.loads(json.dumps(document, allow_nan=False))
    errors = sorted(Draft202012Validator(schema).iter_errors(as_json), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or 'calibration'}: {e.message}" for e in errors[:5]]


def validate_calibration(document):
    """Raise ValueError unless `document` passes calibration.schema.json and the checks a
    schema cannot make: the homography is usable, the points hold out, and the stored errors
    match the points. A document that passes can be loaded by every consumer (recording,
    report, preview); a file that does not pass is refused here, not later inside one of them."""
    version = document.get("contract_version") if isinstance(document, dict) else None
    if not accepts_calibration(version):
        low, high = contract.CALIBRATION_FORMATS[contract.CALIBRATION_FORMAT]
        raise ValueError(
            f"calibration contract version {version} is not accepted "
            f"(format {contract.CALIBRATION_FORMAT} covers {low} to {high or CONTRACT_VERSION})"
        )
    from services.edge.calibration.intake import normalize_document

    document = normalize_document(document)
    # An older accepted version is checked against the current schema as if current.
    problems = _schema_errors({**document, "contract_version": CONTRACT_VERSION})
    if problems:
        raise ValueError(
            "calibration does not match calibration.schema.json: " + "; ".join(problems)
        )
    court = document["court"]
    court_model(court["type"], court["length_m"], court["width_m"], court["landmarks"])
    points = document["points"]
    homography = normalize_homography_sign(
        document["homography_image_to_court"], [p["image_px"] for p in points]
    )
    document = {**document, "homography_image_to_court": homography.tolist()}
    check_homography(homography, [p["image_px"] for p in points])
    dimensions = (court["length_m"], court["width_m"]) if court["type"] == "fiba_half" else None
    check_point_set(points, dimensions)
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
