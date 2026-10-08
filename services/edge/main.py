"""CLI entry point (PHASE_01).

    python -m services.edge.main --source <ref> [--preview] [--link usb|wifi|builtin|file]

ref: a webcam index (0, 1, ...), a stream URL (http, https, rtsp) or an .mp4/.mov file.
Events print to the console; nothing is written to disk in phase 01.
"""

import argparse
import dataclasses
import queue
import sys
import threading
import time
from collections import Counter

import cv2
import numpy as np

from services.edge.capture.capture import Capture
from services.edge.capture.health import HealthConfig, HealthMonitor
from services.edge.capture.sources import SourceOpenError, open_source
from services.edge.capture.types import HealthEvent, utc_now
from services.edge.ui.preview import run_preview

CAMERA_APIS = {"any": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}
EXIT_OPEN_FAILED = 2
EXIT_CAPTURE_ERROR = 1
EXIT_INTERRUPTED = 130


def positive(cast):
    """argparse type: a number > 0, so a threshold cannot silently fire on every read."""

    def parse(text: str):
        value = cast(text)
        if value <= 0:
            raise argparse.ArgumentTypeError(f"must be > 0, got {text}")
        return value

    parse.__name__ = cast.__name__  # argparse uses it in error messages
    return parse


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    d = HealthConfig()
    p = argparse.ArgumentParser(prog="python -m services.edge.main", description=__doc__)
    p.add_argument("--source", required=True, help="webcam index, stream URL or .mp4/.mov path")
    p.add_argument("--preview", action="store_true", help="show the preview window")
    p.add_argument(
        "--link",
        choices=["usb", "wifi", "builtin", "file"],
        help="how the source reaches the notebook (recorded, not detected; D-012)",
    )
    p.add_argument(
        "--camera-api",
        choices=list(CAMERA_APIS),
        default="any",
        help="OpenCV backend for webcam indices; try dshow if DroidCam is not found",
    )
    p.add_argument("--lost-reads", type=positive(int), default=d.lost_reads)
    p.add_argument("--lost-secs", type=positive(float), default=d.lost_secs)
    p.add_argument("--frozen-diff", type=positive(float), default=d.frozen_diff)
    p.add_argument("--frozen-secs", type=positive(float), default=d.frozen_secs)
    p.add_argument("--dark-level", type=positive(float), default=d.dark_level)
    p.add_argument("--dark-secs", type=positive(float), default=d.dark_secs)
    return p.parse_args(argv)


def print_event(ev: HealthEvent, t0: float | None) -> None:
    rel = f"+{ev.t_mono - t0:.2f}s" if t0 is not None else "-"
    print(f"[{ev.t_wall}] {rel} {ev.kind}: {ev.detail}", flush=True)


def run_headless(capture: Capture) -> None:
    """Stand-in consumer until phase 02: take frames until capture stops."""
    while not (capture.done.is_set() and capture.proc_queue.empty()):
        try:
            capture.proc_queue.get(timeout=0.1)
        except queue.Empty:
            pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:  # Ctrl+C before capture started (e.g. a slow stream open)
        print_event(HealthEvent("interrupted", utc_now(), None, "Ctrl+C"), None)
        return EXIT_INTERRUPTED


def run(args: argparse.Namespace) -> int:
    config = HealthConfig(
        lost_reads=args.lost_reads,
        lost_secs=args.lost_secs,
        frozen_diff=args.frozen_diff,
        frozen_secs=args.frozen_secs,
        dark_level=args.dark_level,
        dark_secs=args.dark_secs,
    )
    try:
        source = open_source(args.source, CAMERA_APIS[args.camera_api])
        info = source.open()
    except (SourceOpenError, cv2.error) as e:
        reason = str(e).strip()
        # no run, so no t0: t_mono is null (D-014)
        print_event(HealthEvent("source_open_failed", utc_now(), None, reason), None)
        print(f"error: cannot open source {args.source!r}: {reason}", file=sys.stderr)
        return EXIT_OPEN_FAILED

    info = dataclasses.replace(info, link=args.link)
    print(f"source: {info}")
    print(f"health: {config}")
    py = sys.version.split()[0]
    print(f"versions: python {py}, opencv {cv2.__version__}, numpy {np.__version__}")

    events: Counter[str] = Counter()
    events_lock = threading.Lock()  # called from the capture thread and the main thread
    monitor = HealthMonitor(config)

    def on_event(ev: HealthEvent) -> None:
        with events_lock:
            events[ev.kind] += 1
            print_event(ev, capture.t0)

    capture = Capture(source, monitor, on_event)
    status = 0
    capture.start()
    try:
        if args.preview:
            run_preview(capture, lambda: monitor.state)
        else:
            run_headless(capture)
    except KeyboardInterrupt:
        on_event(HealthEvent("interrupted", utc_now(), time.monotonic(), "Ctrl+C"))
        status = EXIT_INTERRUPTED
    except Exception as e:  # one shutdown path; the failure is an event, not a traceback
        on_event(HealthEvent("error", utc_now(), time.monotonic(), f"main loop: {e!r}"))
        status = EXIT_CAPTURE_ERROR
    finally:
        try:
            stopped = capture.stop()
        except KeyboardInterrupt:  # a second Ctrl+C must not skip the summary
            stopped = False
        if stopped:
            source.close()
        else:
            print("warning: capture thread did not stop in time; source left open", file=sys.stderr)
        print(
            f"t0_wall={capture.t0_wall} captured={capture.captured} dropped={capture.dropped} "
            f"failed_reads={capture.failed_reads} events={dict(events.copy())}"
        )
    if capture.error and not status:
        status = EXIT_CAPTURE_ERROR
    return status


if __name__ == "__main__":
    sys.exit(main())
