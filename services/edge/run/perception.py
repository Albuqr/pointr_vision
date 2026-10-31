"""Device and model load, written once (R2a follow-up T9, D-069). Single camera, group and group
replay all start their perception through `start_perception`, so a load failure is reported the same
way on every path: the event line on stdout (what the launcher reads for a failure before a session)
and the `error:` line on stderr (what Studio shows)."""

import argparse
import dataclasses
import sys
import time
from collections.abc import Callable
from importlib.metadata import version

import numpy as np

from services.edge.capture.types import Frame, HealthEvent, utc_now


def resolve_device(requested: str) -> tuple[str, str | None]:
    """--device to (cpu | cuda:0, GPU name or None). auto is cuda when torch sees a CUDA GPU,
    else cpu. Raises RuntimeError for a forced cuda with no usable GPU. Imports torch."""
    import torch

    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            f"--device cuda but torch {torch.__version__} cannot use a CUDA GPU "
            "(a CPU-only wheel, no NVIDIA GPU, or an old driver); see README, Install on a new PC"
        )
    if requested == "cpu" or not torch.cuda.is_available():
        return "cpu", None
    return "cuda:0", torch.cuda.get_device_name(0)


def create_tracker(args: argparse.Namespace):
    from services.edge.perception.tracker import ByteTrackTracker

    return ByteTrackTracker(
        track_lost_secs=args.track_lost_secs,
        track_activation=args.track_activation,
        track_min_frames=args.track_min_frames,
    )


def load_perception(args: argparse.Namespace, device: str):
    """Detector and tracker, warmed up with one inference so the first slow call is not
    counted in the run. Imported here: torch loads only when detection is on. Called before
    the source opens, so a stream does not buffer stale frames during the load (D-018)."""
    import torch

    from services.edge.perception.detector import RFDETRDetector

    t = time.perf_counter()
    detector = RFDETRDetector.load(args.threshold, args.det_size, device)
    loaded = time.perf_counter() - t
    blank = np.zeros((args.height, args.width, 3), np.uint8)
    t = time.perf_counter()
    detector.detect(Frame(-1, t, utc_now(), blank, "warmup"))
    warmup = time.perf_counter() - t
    tracker = create_tracker(args)
    print(
        f"perception: rfdetr {version('rfdetr')} nano, device {detector.device}, "
        f"det-size {detector.det_size}, threshold {detector.threshold}, "
        f"torch {torch.__version__} threads {torch.get_num_threads()}; "
        f"model load {loaded:.1f} s, warm-up {warmup * 1000:.0f} ms"
    )
    print(f"tracker: trackers {version('trackers')} ByteTrack {tracker.params}")
    return detector, tracker


@dataclasses.dataclass(frozen=True)
class Perception:
    """What a run takes from the load. All None with --no-detect."""

    detector: object | None = None
    tracker: object | None = None
    gpu: str | None = None
    model_loaded: dict | None = None  # {"t_wall", "t_pc"} when the model finished loading


def start_perception(
    args: argparse.Namespace,
    *,
    resolve_device: Callable[[str], tuple[str, str | None]],
    load_perception: Callable[[argparse.Namespace, str], tuple],
    emit: Callable[[HealthEvent, float | None], None],
) -> Perception | None:
    """Resolve the device and load the model, or nothing with --no-detect. A failure is reported
    here (an `error:` line on stderr; a model failure also as an event through `emit`, with no t0:
    t_mono is null, D-014) and returns None: the caller exits EXIT_CAPTURE_ERROR.

    The entry points pass their own `resolve_device` and `load_perception`, so a test can replace
    them in the module it drives."""
    if args.no_detect:
        return Perception()
    try:
        device, gpu = resolve_device(args.device)
    except Exception as e:  # forced cuda without a GPU, or a broken torch install
        note = "" if isinstance(e, RuntimeError) else "device check failed: "
        print(f"error: {note}{e}", file=sys.stderr)
        return None
    print(f"device: {device}" + (f" ({gpu})" if gpu else " (no CUDA GPU in use)"))
    try:
        detector, tracker = load_perception(args, device)
    except Exception as e:  # e.g. no network for the first weights download
        emit(HealthEvent("error", utc_now(), None, f"model load failed: {e!r}"), None)
        print(f"error: model load failed: {e!r}", file=sys.stderr)
        return None
    return Perception(detector, tracker, gpu, {"t_wall": utc_now(), "t_pc": time.perf_counter()})
