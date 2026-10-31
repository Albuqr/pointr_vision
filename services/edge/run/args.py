"""A camera's command line (moved out of main.py by T12, #74), parsed the same way by
services.edge.main and, for each camera, by services.edge.group_main.

    python -m services.edge.main --source <ref> [--preview] [--link usb|wifi|builtin|file]
        [--threshold T] [--device auto|cpu|cuda] [--det-size N] [--width W --height H]
        [--benchmark SECONDS] [--no-detect] [--out DIR] [--camera-id ID] [--group-id ID]
        [--stop-on-stdin]

ref: a webcam index (0, 1, ...), a stream URL (http, https, rtsp) or an .mp4/.mov file.
Each frame taken from capture is detected (RF-DETR Nano, person only) and tracked
(ByteTrack). Once the source opens, the session is logged to DIR/<folder>/ (default
./sessions): session.json, runs/<run_id>/run.json, frames.csv, tracks.csv (D-020).
"""

import argparse
import math
import re

from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import DEFAULT_CAPTURE_SIZE
from services.edge.contract import VIDEO_FILE
from services.edge.perception.detector import DET_SIZE_MULTIPLE
from services.edge.session.types import CAMERA_ID_RE, GROUP_ID_RE


def positive(cast):
    """argparse type: a finite number > 0, so a threshold cannot silently fire on every read
    and a --benchmark of nan or inf cannot run forever."""

    def parse(text: str):
        value = cast(text)
        if not math.isfinite(value) or value <= 0:
            raise argparse.ArgumentTypeError(f"must be > 0, got {text}")
        return value

    parse.__name__ = cast.__name__  # argparse uses it in error messages
    return parse


def confidence(text: str) -> float:
    """argparse type: a detector threshold in (0, 1]."""
    value = float(text)
    if not 0 < value <= 1:  # also rejects nan
        raise argparse.ArgumentTypeError(f"must be in (0, 1], got {text}")
    return value


def det_size(text: str) -> int:
    """argparse type: a positive multiple of the detector's block size (32 for Nano)."""
    value = int(text)
    if value <= 0 or value % DET_SIZE_MULTIPLE:
        raise argparse.ArgumentTypeError(
            f"must be a positive multiple of {DET_SIZE_MULTIPLE}, got {text}"
        )
    return value


def token(pattern: re.Pattern):
    """argparse type: an id that is safe in a file name (DATA_CONTRACTS section 2)."""

    def parse(text: str) -> str:
        if not pattern.fullmatch(text):
            raise argparse.ArgumentTypeError(
                f"must match {pattern.pattern} (letters, digits, _ and -), got {text!r}"
            )
        return text

    parse.__name__ = "id"
    return parse


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    d = HealthConfig()
    p = argparse.ArgumentParser(prog="python -m services.edge.main", description=__doc__)
    p.add_argument("--source", help="webcam index, stream URL or .mp4/.mov path")
    p.add_argument(
        "--replay",
        metavar="TARGET",
        help="process a recorded video again as a new run, at file speed, every frame: a session "
        "id or folder (adds a run to it), a group id (adds a run to each camera's session of the "
        "group, processed together, D-060) or an .mp4/.mov file (starts a new session)",
    )
    p.add_argument("--preview", action="store_true", help="show the preview window")
    p.add_argument("--http-preview", type=int, help="serve annotated loopback preview on this port")
    p.add_argument("--calibration", help="calibration JSON file for metre positions")
    p.add_argument(
        "--calibration-problem",
        help="why the launcher did not pass a saved calibration: recorded as an event",
    )
    p.add_argument(
        "--calibration-failed",
        help="why Studio refused this camera's calibration and the operator started it "
        "uncalibrated: recorded as a failed calibration check (D-057)",
    )
    p.add_argument(
        "--link",
        choices=["usb", "wifi", "builtin", "file"],
        help="how the source reaches the notebook (recorded, not detected; D-012)",
    )
    p.add_argument(
        "--width",
        type=positive(int),
        default=DEFAULT_CAPTURE_SIZE[0],
        help="requested camera width",
    )
    p.add_argument(
        "--height",
        type=positive(int),
        default=DEFAULT_CAPTURE_SIZE[1],
        help="requested camera height",
    )
    p.add_argument("--threshold", type=confidence, default=0.5, help="person confidence")
    p.add_argument(
        "--track-lost-secs",
        type=positive(float),
        default=1.0,
        metavar="SECONDS",
        help="seconds to keep a lost track (default: 1.0)",
    )
    p.add_argument(
        "--track-activation",
        type=confidence,
        default=0.7,
        help="minimum detection confidence to start a track (default: 0.7)",
    )
    p.add_argument(
        "--track-min-frames",
        type=positive(int),
        default=2,
        help="consecutive detections required to confirm a track (default: 2)",
    )
    p.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
        help="auto: cuda when torch sees a CUDA GPU, else cpu; cuda fails if there is none",
    )
    p.add_argument(
        "--det-size",
        type=det_size,
        help="square side the image is resized to for detection (default: the model's own)",
    )
    p.add_argument(
        "--fps-cap",
        type=positive(float),
        help="maximum source read rate requested for this camera (does not guarantee camera FPS)",
    )
    p.add_argument(
        "--benchmark",
        type=positive(float),
        metavar="SECONDS",
        help="run for SECONDS, then print processing FPS, app delay p50/p95/max and drops",
    )
    p.add_argument("--no-detect", action="store_true", help="capture only, no detection")
    p.add_argument(
        "--no-record",
        action="store_true",
        help=f"do not keep the raw video; by default {VIDEO_FILE} is written in the session folder",
    )
    p.add_argument(
        "--camera-id",
        type=token(CAMERA_ID_RE),
        help="label of this camera in a multi-camera recording, e.g. cam1 (D-022)",
    )
    p.add_argument(
        "--group-id",
        type=token(GROUP_ID_RE),
        help="shared by the cameras recorded together; the launcher sets it (D-022)",
    )
    p.add_argument(
        "--stop-on-stdin",
        action="store_true",
        help="launcher use: a line 'stop' on stdin, or its end, stops like Ctrl+C",
    )
    p.add_argument("--out", default="sessions", help="folder for session data (default sessions)")
    p.add_argument("--lost-reads", type=positive(int), default=d.lost_reads)
    p.add_argument("--lost-secs", type=positive(float), default=d.lost_secs)
    p.add_argument("--frozen-diff", type=positive(float), default=d.frozen_diff)
    p.add_argument("--frozen-secs", type=positive(float), default=d.frozen_secs)
    p.add_argument("--dark-level", type=positive(float), default=d.dark_level)
    p.add_argument("--dark-secs", type=positive(float), default=d.dark_secs)
    args = p.parse_args(argv)
    if (args.source is None) == (args.replay is None):
        p.error("give exactly one of --source and --replay")
    return args
