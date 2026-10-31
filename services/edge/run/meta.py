"""What run.json takes at the start of a run (R2a follow-up T11, D-071): the settings read from the
command line, `run_meta`, and the small checks that go with them. Moved out of main.py so the run
module needs nothing from an entry point."""

import argparse
import dataclasses
import platform
import sys
import uuid
from importlib.metadata import PackageNotFoundError, version

import cv2
import numpy as np

from services.edge.calibration.intake import Refused, take_calibration
from services.edge.capture.health import HealthConfig
from services.edge.capture.types import HealthEvent, utc_now
from services.edge.power import read_power
from services.edge.session.types import RunMeta


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def normalise_device(device: str) -> str:
    """torch device string to the contract's cpu | cuda:N ("cuda" alone is cuda:0)."""
    return "cuda:0" if device == "cuda" else device


@dataclasses.dataclass(frozen=True)
class RunSettings:
    """What run.json takes from the command line, read once per entry point."""

    requested_size: tuple[int, int] | None
    calibration_refusal: str | None

    @classmethod
    def from_args(cls, args) -> "RunSettings":
        return cls((args.width, args.height), args.calibration_failed)


def run_meta(
    settings: RunSettings,
    info,
    config: HealthConfig,
    detector,
    tracker,
    gpu,
    replay=None,
    model_loaded=None,
) -> RunMeta:
    """run.json fields known at start: input, detector, tracker, thresholds, versions."""
    size = settings.requested_size if info.kind == "camera" else None
    return RunMeta(
        run_id=str(uuid.uuid4()),
        mode="replay" if replay else "live",
        input={
            "kind": info.kind,
            "ref": info.ref,
            "sha256": replay.sha256 if replay else None,
            "requested_width": size[0] if size else None,
            "requested_height": size[1] if size else None,
        },
        detector=None
        if detector is None
        else {
            "name": "rfdetr",
            "variant": "nano",
            "weights": "coco-pretrained",
            "package_version": package_version("rfdetr"),
            "threshold": detector.threshold,
            "det_size": detector.det_size,
        },
        tracker=None
        if tracker is None
        else {
            "name": "bytetrack",
            "package": "trackers",
            "package_version": package_version("trackers"),
            "params": tracker.params,
        },
        health=dataclasses.asdict(config),
        runtime={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "device": None if detector is None else normalise_device(detector.device),
            "gpu": gpu,
            "packages": {
                "opencv": cv2.__version__,
                "numpy": np.__version__,
                "torch": package_version("torch"),
                "supervision": package_version("supervision"),
            },
        },
        started_at=utc_now(),
        power_start=read_power(),
        checks=failed_calibration_checks(settings.calibration_refusal),
        ready={"model_loaded": model_loaded},
    )


def failed_calibration_checks(refusal: str | None) -> list | None:
    """run.json `checks` of a camera the operator started uncalibrated after Studio refused its
    calibration (D-057); None otherwise: the other checks belong to Track R."""
    if not refusal:
        return None
    return take_calibration(Refused(refusal), None, (0, 0)).checks


def calibration_failed_event(refusal: str | None) -> HealthEvent | None:
    """The `startup_check_failed` event that goes with `failed_calibration_checks`. No t0 yet,
    so t_mono is null."""
    if not refusal:
        return None
    return take_calibration(Refused(refusal), None, (0, 0)).events[0]


def health_config(args: argparse.Namespace) -> HealthConfig:
    return HealthConfig(
        lost_reads=args.lost_reads,
        lost_secs=args.lost_secs,
        frozen_diff=args.frozen_diff,
        frozen_secs=args.frozen_secs,
        dark_level=args.dark_level,
        dark_secs=args.dark_secs,
    )


def link_conflict(kind: str, link: str | None) -> str | None:
    """link is file exactly when kind is file, or link is not given (D-020)."""
    if link is not None and (kind == "file") != (link == "file"):
        return f"--link {link} contradicts a {kind} source"
    return None
