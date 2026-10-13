"""CLI entry point (PHASE_01, PHASE_02, PHASE_03).

    python -m services.edge.main --source <ref> [--preview] [--link usb|wifi|builtin|file]
        [--threshold T] [--device auto|cpu|cuda] [--det-size N] [--width W --height H]
        [--benchmark SECONDS] [--no-detect] [--out DIR]

ref: a webcam index (0, 1, ...), a stream URL (http, https, rtsp) or an .mp4/.mov file.
Each frame taken from capture is detected (RF-DETR Nano, person only) and tracked
(ByteTrack). Once the source opens, the session is logged to DIR/<session_id>/ (default
./sessions): session.json, runs/<run_id>/run.json, frames.csv, tracks.csv (D-020).
"""

import argparse
import dataclasses
import math
import platform
import sys
import threading
import time
import uuid
from collections import Counter
from importlib.metadata import PackageNotFoundError, version

import cv2
import numpy as np

from services.edge.capture.capture import Capture
from services.edge.capture.health import HealthConfig, HealthMonitor
from services.edge.capture.sources import CameraSource, SourceOpenError, open_source
from services.edge.capture.types import Frame, HealthEvent, utc_now
from services.edge.perception.detector import DET_SIZE_MULTIPLE
from services.edge.perception.loop import Processor, delay_stats, rates
from services.edge.session.types import FrameRecord, RunCounts, RunMeta, SessionEvent, SessionMeta
from services.edge.session.writer import FileSessionWriter, device_id
from services.edge.ui.preview import HudInfo, run_preview

EXIT_OPEN_FAILED = 2
EXIT_CAPTURE_ERROR = 1
EXIT_INTERRUPTED = 130


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
    p.add_argument("--width", type=positive(int), default=1280, help="requested camera width")
    p.add_argument("--height", type=positive(int), default=720, help="requested camera height")
    p.add_argument("--threshold", type=confidence, default=0.5, help="person confidence")
    p.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    p.add_argument(
        "--det-size",
        type=det_size,
        help="square side the image is resized to for detection (default: the model's own)",
    )
    p.add_argument(
        "--benchmark",
        type=positive(float),
        metavar="SECONDS",
        help="run for SECONDS, then print processing FPS, app delay p50/p95/max and drops",
    )
    p.add_argument("--no-detect", action="store_true", help="capture only, no detection")
    p.add_argument("--out", default="sessions", help="folder for session data (default sessions)")
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


def load_perception(args: argparse.Namespace):
    """Detector and tracker, warmed up with one inference so the first slow call is not
    counted in the run. Imported here: torch loads only when detection is on. Called before
    the source opens, so a stream does not buffer stale frames during the load (D-018)."""
    import torch

    from services.edge.perception.detector import RFDETRDetector
    from services.edge.perception.tracker import ByteTrackTracker

    t = time.monotonic()
    detector = RFDETRDetector.load(args.threshold, args.det_size, args.device)
    loaded = time.monotonic() - t
    blank = np.zeros((args.height, args.width, 3), np.uint8)
    t = time.monotonic()
    detector.detect(Frame(-1, t, utc_now(), blank, "warmup"))
    warmup = time.monotonic() - t
    tracker = ByteTrackTracker()
    print(
        f"perception: rfdetr {version('rfdetr')} nano, device {detector.device}, "
        f"det-size {detector.det_size}, threshold {detector.threshold}, "
        f"torch {torch.__version__} threads {torch.get_num_threads()}; "
        f"model load {loaded:.1f} s, warm-up {warmup * 1000:.0f} ms"
    )
    print(f"tracker: trackers {version('trackers')} ByteTrack {tracker.params}")
    return detector, tracker


def open_failed(ref: str, e: Exception) -> int:
    reason = str(e).strip()
    # no run, so no t0: t_mono is null (D-014)
    print_event(HealthEvent("source_open_failed", utc_now(), None, reason), None)
    print(f"error: cannot open source {ref!r}: {reason}", file=sys.stderr)
    return EXIT_OPEN_FAILED


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def normalise_device(device: str) -> str:
    """torch device string to the contract's cpu | cuda:N ("cuda" alone is cuda:0)."""
    return "cuda:0" if device == "cuda" else device


def run_meta(args, info, config: HealthConfig, detector, tracker) -> RunMeta:
    """run.json fields known at start: input, detector, tracker, thresholds, versions."""
    camera = info.kind == "camera"
    return RunMeta(
        run_id=str(uuid.uuid4()),
        mode="live",
        input={
            "kind": info.kind,
            "ref": info.ref,
            "sha256": None,
            "requested_width": args.width if camera else None,
            "requested_height": args.height if camera else None,
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
            "packages": {
                "opencv": cv2.__version__,
                "numpy": np.__version__,
                "torch": package_version("torch"),
                "supervision": package_version("supervision"),
            },
        },
        started_at=utc_now(),
    )


def link_conflict(kind: str, link: str | None) -> str | None:
    """link is file exactly when kind is file, or link is not given (D-020)."""
    if link is not None and (kind == "file") != (link == "file"):
        return f"--link {link} contradicts a {kind} source"
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:  # Ctrl+C before capture started (model load, slow stream open)
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
    events: Counter[str] = Counter()
    events_lock = threading.Lock()  # called from the capture, processing and main threads
    capture: Capture | None = None

    def on_event(ev: HealthEvent) -> None:
        with events_lock:
            events[ev.kind] += 1
            print_event(ev, capture.t0 if capture else None)

    try:
        source = open_source(args.source, (args.width, args.height))  # checks the ref only
    except SourceOpenError as e:
        return open_failed(args.source, e)
    conflict = args.link and link_conflict(source.kind, args.link)
    if conflict:  # before the slow model load
        print(f"error: {conflict}", file=sys.stderr)
        return EXIT_OPEN_FAILED

    detector = tracker = None
    if not args.no_detect:
        try:
            detector, tracker = load_perception(args)
        except Exception as e:  # e.g. no network for the first weights download
            # before any run, so no t0: t_mono is null (D-014)
            on_event(HealthEvent("error", utc_now(), None, f"model load failed: {e!r}"))
            return EXIT_CAPTURE_ERROR

    try:
        info = source.open()
    except (SourceOpenError, cv2.error) as e:
        return open_failed(args.source, e)

    info = dataclasses.replace(info, link=args.link)
    print(f"source: {info}")
    if isinstance(source, CameraSource):  # streams and files deliver their own size
        print(f"requested {args.width}x{args.height}, camera delivers {info.width}x{info.height}")
    print(f"health: {config}")
    py = sys.version.split()[0]
    print(f"versions: python {py}, opencv {cv2.__version__}, numpy {np.__version__}")

    writer = FileSessionWriter(args.out)
    try:
        session_id = str(uuid.uuid4())
        meta = SessionMeta(session_id, device_id(args.out), utc_now(), info, False)
        writer.start(meta, run_meta(args, info, config, detector, tracker))
    except OSError as e:
        source.close()
        print(f"error: cannot write session data under {args.out!r}: {e}", file=sys.stderr)
        return EXIT_CAPTURE_ERROR
    print(f"session: {writer.dir}")

    def rel(t: float | None) -> float | None:
        """time.monotonic() to s since the run's t0; None before t0 (D-011, D-014)."""
        t0 = capture.t0 if capture else None
        return None if t is None or t0 is None or t < t0 else t - t0

    def log_event(ev: HealthEvent) -> None:
        on_event(ev)
        writer.event(SessionEvent(ev.t_wall, rel(ev.t_mono), ev.kind, ev.detail))

    def log_frame(p) -> None:
        t0 = capture.t0
        n_dets = None if detector is None else len(p.dets.xyxy)
        n_tracks = None if detector is None else len(p.tracks)
        rec = FrameRecord(
            p.frame.seq,
            p.frame.t_recv - t0,
            p.t_proc_start - t0,
            p.t_proc_end - t0,
            n_dets,
            n_tracks,
            p.dropped_total,
        )
        writer.frame(rec)
        if p.tracks:
            writer.tracks(p.frame.seq, p.tracks)

    monitor = HealthMonitor(config)
    capture = Capture(source, monitor, log_event)
    processor = Processor(
        capture.proc_queue,
        capture.done,
        detector,
        tracker,
        log_event,
        on_processed=log_frame,
        dropped=lambda: capture.dropped,
    )

    def hud() -> HudInfo:
        latest = processor.latest
        return HudInfo(
            capture_fps=capture.fps,
            dropped=capture.dropped,
            proc_fps=processor.fps,
            app_delay_ms=latest.app_delay_ms if latest else None,
            people=None if detector is None else (len(latest.dets.xyxy) if latest else 0),
            tracks=None if detector is None else (len(latest.tracks) if latest else 0),
        )

    status = 0
    session_status = "ended"
    capture.start()
    processor.start()
    until = time.monotonic() + args.benchmark if args.benchmark else None
    try:
        while capture.t0_wall is None:  # set first thing by the capture thread
            time.sleep(0.001)
        writer.set_t0(capture.t0, capture.t0_wall)
        if args.preview:
            run_preview(lambda: processor.latest, processor.done, hud, lambda: monitor.state, until)
        else:
            while not processor.done.wait(0.1):
                if until is not None and time.monotonic() >= until:
                    break
    except KeyboardInterrupt:
        session_status = "interrupted"
        status = EXIT_INTERRUPTED
        log_event(HealthEvent("interrupted", utc_now(), time.monotonic(), "Ctrl+C"))
    except Exception as e:  # one shutdown path; the failure is an event, not a traceback
        session_status = "error"
        status = EXIT_CAPTURE_ERROR
        log_event(HealthEvent("error", utc_now(), time.monotonic(), f"main loop: {e!r}"))
    finally:
        # capture first, then processing drains the last frame (ARCHITECTURE section 5).
        # A second Ctrl+C must not skip a step or the summary.
        cap_ok = proc_ok = False
        try:
            cap_ok = capture.stop()
        except KeyboardInterrupt:  # _stop is already set: the thread ends within one read
            cap_ok = capture.done.wait(1.0)
        try:
            # without a stopped capture there is no last frame to drain: do not wait for it
            proc_ok = processor.stop(10.0 if cap_ok else 0.0)
        except KeyboardInterrupt:
            pass
        try:
            if cap_ok:
                source.close()
        except KeyboardInterrupt:
            pass
        if not cap_ok:
            print(
                "warning: capture thread did not stop in time; source left open; "
                "counts may be short",
                file=sys.stderr,
            )
        if not proc_ok:
            print("warning: processing did not stop in time; counts may be short", file=sys.stderr)
        if session_status == "ended" and (
            capture.error or processor.error or not (cap_ok and proc_ok)
        ):
            session_status = "error"
        if not (cap_ok and proc_ok):  # the shortfall goes into the data, not only stderr
            which = " and ".join(
                n for n, ok in (("capture", cap_ok), ("processing", proc_ok)) if not ok
            )
            detail = f"{which} did not stop in time; counts may be short"
            log_event(HealthEvent("error", utc_now(), time.monotonic(), detail))
        counts = RunCounts(
            capture.captured, processor.processed, capture.dropped, processor.unprocessed
        )
        while writer.status is None:  # a second Ctrl+C must not skip the final write
            try:
                writer.close(session_status, counts)
            except KeyboardInterrupt:
                pass
            except Exception as e:  # cannot write at all: say so, keep shutting down
                print(f"error: final session files not written: {e!r}", file=sys.stderr)
                break
        try:
            print(f"session {writer.status}: {writer.dir}")
            print(
                f"t0_wall={capture.t0_wall} captured={capture.captured} dropped={capture.dropped} "
                f"failed_reads={capture.failed_reads} processed={processor.processed} "
                f"unprocessed={processor.unprocessed} events={dict(events.copy())}"
            )
            if args.benchmark:
                det = "off" if detector is None else detector.det_size
                device = "-" if detector is None else detector.device
                print_benchmark(args.benchmark, info.link, det, device, capture, processor)
        except KeyboardInterrupt:
            status = EXIT_INTERRUPTED
    if (capture.error or processor.error or writer.status != session_status) and not status:
        status = EXIT_CAPTURE_ERROR
    return status


def print_benchmark(
    seconds: float,
    link: str | None,
    det: int | str,
    device: str,
    capture: Capture,
    processor: Processor,
) -> None:
    """The A7 baseline block. Every figure comes from this run. The run time is t0 to now,
    so it includes the shutdown (about one inference)."""
    elapsed = time.monotonic() - capture.t0 if capture.t0 else 0.0
    latest = processor.latest
    frame = f"{latest.frame.image.shape[1]}x{latest.frame.image.shape[0]}" if latest else "-"
    proc_fps, drop_rate = rates(
        capture.captured,
        capture.dropped,
        processor.processed,
        processor.first_start,
        processor.last_end,
    )
    fps = "-" if proc_fps is None else f"{proc_fps:.2f}"
    rate = "-" if drop_rate is None else f"{100 * drop_rate:.1f}%"
    stats = delay_stats(processor.delays_ms)
    delay = (
        f"p50 {stats['p50']:.1f}, p95 {stats['p95']:.1f}, max {stats['max']:.1f}" if stats else "-"
    )
    print(
        f"benchmark: {elapsed:.1f} s run ({seconds:g} s requested), link {link}, "
        f"frames {frame}, det-size {det}, device {device}, cpu {platform.processor() or '-'}\n"
        f"benchmark: captured {capture.captured}, processed {processor.processed} "
        f"({fps} fps), dropped {capture.dropped} ({rate} of captured), "
        f"failed reads {capture.failed_reads}, unprocessed {processor.unprocessed}\n"
        f"benchmark: app delay ms {delay} over {len(processor.delays_ms)} frames"
    )


if __name__ == "__main__":
    sys.exit(main())
