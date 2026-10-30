"""Calibration intake: one verdict for every way a calibration reaches a camera.

`take_calibration(offer, camera_id, size)` never raises on content. It returns an `Intake`: the
usable `Calibration` or None, the session events to write, the run.json `checks`, and the edge's
own refusal reason. The runtime `Calibration` is one immutable type that resolves the legacy
`kind`/`type` court alias once and produces the session block, the run block and the preview court.
`build_document` makes the calibration file from fitted points, for Studio's fit.

Every run entry point and Studio use this boundary."""

from dataclasses import dataclass
from pathlib import Path

from services.edge import contract
from services.edge.calibration.court import Court, court_model
from services.edge.calibration.homography import check_homography
from services.edge.capture.types import HealthEvent, utc_now


@dataclass(frozen=True)
class FromFile:
    """A calibration file on disk (`--calibration`)."""

    path: str | Path


@dataclass(frozen=True)
class FromRun:
    """The `calibration` block of a recorded run.json (replay)."""

    block: dict


@dataclass(frozen=True)
class Refused:
    """The operator started the camera uncalibrated after Studio refused its calibration (D-057)."""

    reason: str


@dataclass(frozen=True)
class NotUsed:
    """Studio found the saved calibration not usable and did not pass it on."""

    problem: str


Offer = FromFile | FromRun | Refused | NotUsed | None


def court_document(court: Court):
    """The court block saved by Studio, including the legacy file alias."""
    return {
        "kind": court.kind,
        "type": court.kind,
        "length_m": court.length_m,
        "width_m": court.width_m,
        "landmarks": court.landmarks,
    }


def normalize_document(document):
    """Resolve the saved legacy court alias without changing the caller's document."""
    document = dict(document)
    if not isinstance(document.get("court", {}), dict):
        raise ValueError("calibration court must be an object")
    court = dict(document.get("court", {}))
    if "type" not in court and "kind" in court:
        court["type"] = court["kind"]
    if "kind" not in court and "type" in court:
        court["kind"] = court["type"]
    if court.get("type") != court.get("kind"):
        raise ValueError("calibration court kind and type must agree")
    return {**document, "court": court}


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"calibration {name} must be a number")
    return value


def _size_key(size):
    width, height = size
    return int(width), int(height)


@dataclass(frozen=True)
class Calibration:
    """A validated calibration at runtime. Build it with `from_document` or `from_run`."""

    calibration_id: str
    check_error_m: float
    court_type: str  # fiba_full | fiba_half | custom; the legacy `kind` alias is resolved here
    length_m: float
    width_m: float
    landmarks: dict | None  # as saved; None when it came from a run block, which has none
    homography: tuple  # 3 x 3, image to court
    width_px: int
    height_px: int

    @classmethod
    def from_document(cls, document):
        """From a calibration document that passed `validate_calibration`."""
        court = document["court"]
        size = document["image_size"]
        return cls(
            calibration_id=document["calibration_id"],
            check_error_m=document["errors"]["check_mean_m"],
            court_type=court.get("type", court.get("kind")),
            length_m=court["length_m"],
            width_m=court["width_m"],
            landmarks=court.get("landmarks"),
            homography=tuple(tuple(row) for row in document["homography_image_to_court"]),
            width_px=size["width"],
            height_px=size["height"],
        )

    @classmethod
    def from_run(cls, block):
        """From a run.json `calibration` block. Raises ValueError when it is malformed or its
        homography is singular, so a replay never runs "calibrated" with every position empty."""
        if not isinstance(block, dict):
            raise ValueError("run calibration block must be an object")
        try:
            court, size = block["court"], block["image_size"]
            if not isinstance(court, dict) or not isinstance(size, dict):
                raise ValueError("run calibration court and image_size must be objects")
            calibration_id, matrix = block["calibration_id"], block["homography_image_to_court"]
            check_error, court_type = block["check_error_m"], court["type"]
            length_m, width_m = court["length_m"], court["width_m"]
            width_px, height_px = size["width"], size["height"]
        except KeyError as exc:
            raise ValueError(f"run calibration block lacks {exc.args[0]!r}") from exc
        if not isinstance(calibration_id, str):
            raise ValueError("run calibration_id must be a string")
        if _number(check_error, "check_error_m") < 0:
            raise ValueError("run calibration check_error_m must not be negative")
        for name, value in (("width", width_px), ("height", height_px)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"run calibration image_size {name} must be a positive integer")
        if not (
            isinstance(matrix, (list, tuple))
            and len(matrix) == 3
            and all(isinstance(row, (list, tuple)) and len(row) == 3 for row in matrix)
        ):
            raise ValueError("homography must be a finite 3 x 3 matrix")
        rows = tuple(tuple(_number(v, "homography entry") for v in row) for row in matrix)
        court_model(court_type, _number(length_m, "length_m"), _number(width_m, "width_m"))
        check_homography(rows)
        return cls(
            calibration_id=calibration_id,
            check_error_m=check_error,
            court_type=court_type,
            length_m=length_m,
            width_m=width_m,
            landmarks=None,
            homography=rows,
            width_px=width_px,
            height_px=height_px,
        )

    @property
    def image_size(self):
        """(width, height) in pixels."""
        return self.width_px, self.height_px

    def _court_block(self):
        return {"type": self.court_type, "length_m": self.length_m, "width_m": self.width_m}

    def session_block(self):
        """The `calibration` block of session.json."""
        return {
            "calibration_id": self.calibration_id,
            "check_error_m": self.check_error_m,
            "court": self._court_block(),
        }

    def run_block(self):
        """The `calibration` block of run.json."""
        return {
            "calibration_id": self.calibration_id,
            "check_error_m": self.check_error_m,
            "homography_image_to_court": [list(row) for row in self.homography],
            "court": self._court_block(),
            "image_size": {"width": self.width_px, "height": self.height_px},
        }

    def preview_document(self):
        """Legacy preview input, assembled only at intake."""
        return {
            **self.run_block(),
            "court": {**self._court_block(), "kind": self.court_type, "landmarks": self.landmarks},
        }

    def positions(self):
        from services.edge.calibration.homography import CalibrationPositions

        return CalibrationPositions(self.run_block())

    def preview_court(self) -> Court:
        """The court the preview draws over the frame."""
        return court_model(self.court_type, self.length_m, self.width_m, self.landmarks)


@dataclass(frozen=True)
class Intake:
    """What became of a calibration offer. `checks` is None unless a check failed (run.json
    `checks` is null until the startup checks have run)."""

    calibration: Calibration | None
    events: tuple[HealthEvent, ...] = ()
    checks: list | None = None
    refused_at_edge: str | None = None


def _failed_check(reason):
    """run.json `checks` and the `startup_check_failed` event of a refused calibration. The
    event precedes the run's t0, so t_mono is null."""
    now = utc_now()
    checks = [{"check": "calibration", "result": "failed", "detail": reason, "t_wall": now}]
    return checks, HealthEvent("startup_check_failed", now, None, f"calibration: {reason}")


def _refusal(reason, *, at_edge):
    checks, event = _failed_check(reason)
    events = (
        (HealthEvent("error", event.t_wall, None, f"calibration not used: {reason}"), event)
        if at_edge
        else (event,)
    )
    return Intake(None, events, checks, reason if at_edge else None)


def _size_problem(have, want):
    if _size_key(have) != _size_key(want):
        return (
            f"calibration image size {have[0]}x{have[1]} differs from "
            f"capture size {want[0]}x{want[1]}"
        )
    return None


def _from_file(path, camera_id, size):
    from services.edge.calibration.document import load_calibration

    document = load_calibration(path)
    if camera_id is None:
        raise ValueError("--camera-id is required when --calibration is used")
    if document["camera_id"] != camera_id:
        raise ValueError(f"calibration is for camera {document['camera_id']!r}, not {camera_id!r}")
    return Calibration.from_document(document)


def take_calibration(offer: Offer, camera_id: str | None, size: tuple[int, int] | None) -> Intake:
    """The verdict on a calibration offer for `camera_id` and a capture `size` (width, height).

    `size=None` checks a saved file before a source is opened (Studio pre-start warning).
    Never raises on content: a file or block that cannot be used (ValueError, OSError) becomes an
    edge refusal, recorded as a failed `calibration` check plus a `startup_check_failed` event
    (the same as an operator's refusal, D-057). A non-None calibration has been validated and its
    image size equals `size`."""
    if offer is None:
        return Intake(None)
    if isinstance(offer, Refused):  # the operator's refusal: the edge detected nothing
        return _refusal(offer.reason, at_edge=False)
    if isinstance(offer, NotUsed):  # Studio's finding; recorded as an error event, no check
        event = HealthEvent("error", utc_now(), None, f"calibration not used: {offer.problem}")
        return Intake(None, (event,))
    try:
        if isinstance(offer, FromFile):
            calibration = _from_file(offer.path, camera_id, size)
        elif isinstance(offer, FromRun):
            calibration = Calibration.from_run(offer.block)
        else:
            raise TypeError(f"not a calibration offer: {offer!r}")
        if size is not None and (problem := _size_problem(calibration.image_size, size)):
            raise ValueError(problem)
    except (ValueError, OSError) as exc:
        return _refusal(" ".join(str(exc).split()) or exc.__class__.__name__, at_edge=True)
    return Intake(calibration)


def build_document(
    *,
    camera_id: str,
    court: Court,
    image_size: tuple[int, int],
    points: list,
    fit: dict,
    max_check_error_m: float,
    calibration_id: str,
    created_at: str,
) -> dict:
    """The calibration file for a fit that Studio saves.

    `fit` is the result of `fit_calibration` for `points` (in order); `image_size` is the
    captured frame's (width, height). The id and time are arguments so the builder stays pure."""
    errors = iter(fit["calibration_errors_m"])
    check_errors = iter(fit["check_errors_m"])
    return {
        "contract_version": contract.CONTRACT_VERSION,
        "calibration_id": calibration_id,
        "camera_id": camera_id,
        "created_at": created_at,
        "court": court_document(court),
        "image_size": {"width": image_size[0], "height": image_size[1]},
        "homography_image_to_court": fit["homography_image_to_court"],
        "points": [
            {
                "image_px": [float(v) for v in p["image_px"]],
                "court_m": [float(v) for v in p["court_m"]],
                "role": p["role"],
                "residual_m": next(errors if p["role"] == "calibration" else check_errors),
            }
            for p in points
        ],
        "errors": {key: fit[key] for key in ("calibration_mean_m", "check_mean_m", "check_max_m")},
        "max_check_error_m": float(max_check_error_m),
        "forced": fit["forced"],
        "audit_frame": "frame.jpg",
    }
