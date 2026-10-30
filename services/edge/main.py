"""CLI entry point (PHASE_01, PHASE_02, PHASE_03).

    python -m services.edge.main --source <ref> [--preview] [--link usb|wifi|builtin|file]
        [--threshold T] [--device auto|cpu|cuda] [--det-size N] [--width W --height H]
        [--benchmark SECONDS] [--no-detect] [--out DIR] [--camera-id ID] [--group-id ID]
        [--stop-on-stdin]

ref: a webcam index (0, 1, ...), a stream URL (http, https, rtsp) or an .mp4/.mov file.
Each frame taken from capture is detected (RF-DETR Nano, person only) and tracked
(ByteTrack). Once the source opens, the session is logged to DIR/<folder>/ (default
./sessions): session.json, runs/<run_id>/run.json, frames.csv, tracks.csv (D-020).
"""

import _thread
import argparse
import dataclasses
import math
import platform
import re
import select
import signal
import sys
import threading
import time
import uuid
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import cv2
import numpy as np

from services.edge.camera_pipeline import (
    CameraPipeline,
    CameraStats,
    LiveInput,
    ReplayInput,
    load_camera_calibration,
    session_calibration,
)
from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import (
    DEFAULT_CAPTURE_SIZE,
    CameraSource,
    FileSource,
    SourceOpenError,
    open_source,
)
from services.edge.capture.types import Frame, HealthEvent, utc_now
from services.edge.contract import UI_STOP_DETAIL, VIDEO_FILE
from services.edge.perception.detector import DET_SIZE_MULTIPLE
from services.edge.perception.loop import delay_stats, rates
from services.edge.power import read_power
from services.edge.recording.recorder import FileRecorder
from services.edge.replay.resolve import ReplayError, resolve_replay
from services.edge.reports.build import format_summary, write_report
from services.edge.session.types import CAMERA_ID_RE, GROUP_ID_RE, RunMeta, SessionMeta
from services.edge.session.writer import FileSessionWriter, device_id
from services.edge.ui.preview import run_preview

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


def print_event(ev: HealthEvent, t0: float | None, prefix: str = "") -> None:
    rel = f"+{ev.t_mono - t0:.2f}s" if t0 is not None else "-"
    try:
        print(f"{prefix}[{ev.t_wall}] {rel} {ev.kind}: {ev.detail}", flush=True)
    except OSError:  # the launcher that read this pipe is gone: the event still goes to the file
        pass


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
    return [{"check": "calibration", "result": "failed", "detail": refusal, "t_wall": utc_now()}]


def calibration_failed_event(refusal: str | None) -> HealthEvent | None:
    """The `startup_check_failed` event that goes with `failed_calibration_checks`. No t0 yet,
    so t_mono is null."""
    if not refusal:
        return None
    return HealthEvent("startup_check_failed", utc_now(), None, f"calibration: {refusal}")


def ignore_ctrl_c():
    """Replace the Ctrl+C handler with a message for the rest of the shutdown. Returns the
    previous handler, or None off the main thread (handlers cannot be set there)."""

    def wait(signum, frame):
        try:
            print("stopping, please wait: saving the session", file=sys.stderr, flush=True)
        except OSError:  # nobody is reading any more
            pass

    try:
        return signal.signal(signal.SIGINT, wait)
    except ValueError:
        return None


def stdin_ready() -> bool:
    """True when stdin has input or has ended (the writer closed its end). Never blocks and never
    reads: on Windows a thread blocked in a synchronous pipe read stalls other calls on that
    handle, and a DLL's start-up code does make one (`import scipy` hung in the main thread)."""
    fd = sys.stdin.fileno()
    if sys.platform != "win32":
        return bool(select.select([fd], [], [], 0)[0])
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    peek = kernel32.PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]  # fmt: skip
    peek.restype = wintypes.BOOL
    available = wintypes.DWORD()
    if peek(msvcrt.get_osfhandle(fd), None, 0, None, ctypes.byref(available), None):
        return available.value > 0
    error = ctypes.get_last_error()
    if error in (109, 232):  # ERROR_BROKEN_PIPE, ERROR_NO_DATA: the other end is gone
        return True
    raise OSError(error, "stdin is not a pipe")


@dataclasses.dataclass
class StopRequest:
    """Where the launcher's stop came from: `source` is "ui" after a `stop ui` line (Studio's
    stop, D-049) and None after a plain `stop`, the pipe closing, or a Ctrl+C."""

    source: str | None = None

    @property
    def ui(self) -> bool:
        """Studio's stop: the session ends `ended` with a `stopped` event, not `interrupted`."""
        return self.source == "ui"


def stop_source(line: str) -> str | None:
    """The source a stop line names; anything but `stop ui` is a plain stop."""
    return "ui" if line.split() == ["stop", "ui"] else None


def stop_on_stdin(request: StopRequest | None = None) -> None:
    """Start a thread that turns any input on stdin, or its end, into Ctrl+C: the launcher's way
    to stop this process, also when the launcher itself dies (D-022). Fires once. The line's
    source goes into `request` before the Ctrl+C, so the main thread reads it in its handler."""

    if hasattr(signal, "SIGBREAK"):
        # Ctrl+Break (unlike Ctrl+C) reaches a child in its own process group and would kill it
        # before it saves: the launcher's stdin is the only stop channel
        try:
            signal.signal(signal.SIGBREAK, signal.SIG_IGN)
        except ValueError:  # not the main thread
            pass

    def watch() -> None:
        try:
            while not stdin_ready():
                time.sleep(0.1)
        except (OSError, ValueError, AttributeError) as e:  # a terminal, a file, no stdin
            print(f"warning: --stop-on-stdin cannot watch stdin ({e}); use Ctrl+C", file=sys.stderr)
            return
        if request is not None:
            try:  # the launcher writes whole lines; a closed pipe reads as "" at once
                request.source = stop_source(sys.stdin.readline())
            except (OSError, ValueError, AttributeError):  # unreadable: a plain stop
                pass
        _thread.interrupt_main()  # the same path as Ctrl+C: KeyboardInterrupt in the main thread

    threading.Thread(target=watch, name="stdin-stop", daemon=True).start()


def hold_ctrl_c(arrived: threading.Event):
    """Until release_ctrl_c, a Ctrl+C (or interrupt_main) only sets `arrived`. Returns the
    previous handler, or None off the main thread (handlers cannot be set there)."""
    try:
        return signal.signal(signal.SIGINT, lambda signum, frame: arrived.set())
    except ValueError:
        return None


def release_ctrl_c(previous) -> None:
    if previous is not None:
        signal.signal(signal.SIGINT, previous)


def link_conflict(kind: str, link: str | None) -> str | None:
    """link is file exactly when kind is file, or link is not given (D-020)."""
    if link is not None and (kind == "file") != (link == "file"):
        return f"--link {link} contradicts a {kind} source"
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stop = StopRequest()
    try:
        if args.stop_on_stdin:
            stop_on_stdin(stop)
        return run(args, stop)
    except KeyboardInterrupt:  # Ctrl+C before capture started (model load, slow stream open)
        if stop.ui:  # no session yet; Studio's stop is still a normal end
            print_event(HealthEvent("stopped", utc_now(), None, UI_STOP_DETAIL), None)
            return 0
        print_event(HealthEvent("interrupted", utc_now(), None, "Ctrl+C"), None)
        return EXIT_INTERRUPTED


def health_config(args: argparse.Namespace) -> HealthConfig:
    return HealthConfig(
        lost_reads=args.lost_reads,
        lost_secs=args.lost_secs,
        frozen_diff=args.frozen_diff,
        frozen_secs=args.frozen_secs,
        dark_level=args.dark_level,
        dark_secs=args.dark_secs,
    )


def start_http_preview(port: int, pipeline: CameraPipeline):
    """The camera's loopback preview server, started and fed by its processing thread."""
    from services.edge.ui.http_preview import HttpPreview

    preview = HttpPreview(
        port,
        pipeline.health_state,
        pipeline.hud,
        lambda error: pipeline.log_event(
            HealthEvent(
                "error", utc_now(), time.perf_counter(), f"preview encoding failed: {error!r}"
            )
        ),
        raw_snapshot=pipeline.raw_snapshot,
        calibration=pipeline.calibration,
        on_first_preview=pipeline.mark_preview_ready,
    )
    pipeline.on_preview(preview.publish)
    preview.start()
    return preview


def run(args: argparse.Namespace, stop: StopRequest | None = None) -> int:
    config = health_config(args)
    settings = RunSettings.from_args(args)
    events: Counter[str] = Counter()
    events_lock = threading.Lock()  # called from the capture, processing and main threads

    def on_event(ev: HealthEvent, t0: float | None) -> None:
        with events_lock:
            events[ev.kind] += 1
            print_event(ev, t0)

    if args.replay and not Path(args.replay).exists():  # a group id: replay the group (D-060)
        from services.edge.replay.group import resolve_group, run_replay

        try:
            group = resolve_group(args.replay, args.out)
        except ReplayError as e:
            return open_failed(args.replay, e)
        if group is not None:
            return run_replay(args, group)
    ref = args.replay or args.source
    replay = None
    try:
        if args.replay:
            replay = resolve_replay(args.replay, args.out)
            if not replay.verified:
                print(
                    "warning: the session has no video hash (its recording did not finish), so "
                    "the video cannot be checked against it",
                    file=sys.stderr,
                )
            args.link = "file"
            args.camera_id = args.camera_id or replay.camera_id
            source = FileSource(replay.video, realtime=False)  # as fast as processing allows
        else:
            source = open_source(args.source, (args.width, args.height))
        source.fps_cap = args.fps_cap
    except (SourceOpenError, ReplayError) as e:
        return open_failed(ref, e)
    conflict = args.link and link_conflict(source.kind, args.link)
    if conflict:  # before the slow model load
        print(f"error: {conflict}", file=sys.stderr)
        return EXIT_OPEN_FAILED

    detector = tracker = gpu = model_loaded = None
    if not args.no_detect:
        try:
            device, gpu = resolve_device(args.device)
        except Exception as e:  # forced cuda without a GPU, or a broken torch install
            note = "" if isinstance(e, RuntimeError) else "device check failed: "
            print(f"error: {note}{e}", file=sys.stderr)
            return EXIT_CAPTURE_ERROR
        print(f"device: {device}" + (f" ({gpu})" if gpu else " (no CUDA GPU in use)"))
        try:
            detector, tracker = load_perception(args, device)
            model_loaded = {"t_wall": utc_now(), "t_pc": time.perf_counter()}
        except Exception as e:  # e.g. no network for the first weights download
            # before any run, so no t0: t_mono is null (D-014)
            on_event(HealthEvent("error", utc_now(), None, f"model load failed: {e!r}"), None)
            print(f"error: model load failed: {e!r}", file=sys.stderr)
            return EXIT_CAPTURE_ERROR

    try:
        info = source.open()
    except (SourceOpenError, cv2.error) as e:
        return open_failed(ref, e)

    info = dataclasses.replace(info, link=args.link)
    calibration = positions = None
    if args.calibration:
        try:
            calibration, positions = load_camera_calibration(args.calibration, args.camera_id, info)
        except (ValueError, OSError) as e:
            source.close()
            print(f"error: calibration cannot be used: {e}", file=sys.stderr)
            return EXIT_CAPTURE_ERROR
    print(f"source: {info}")
    if isinstance(source, CameraSource):  # streams and files deliver their own size
        print(f"requested {args.width}x{args.height}, camera delivers {info.width}x{info.height}")
    print(f"health: {config}")
    py = sys.version.split()[0]
    print(f"versions: python {py}, opencv {cv2.__version__}, numpy {np.__version__}")

    # A stop (Ctrl+C, or the launcher's) between the session folder and the main try would leave
    # session.json "running": hold it back here and raise it inside the try.
    stop_early = threading.Event()
    held = hold_ctrl_c(stop_early)
    record = not args.no_record and replay is None  # a replay already has its video
    session_replay = replay is not None and replay.session_dir is not None
    try:
        meta = (
            None
            if session_replay
            else SessionMeta(
                str(uuid.uuid4()),
                device_id(args.out),
                utc_now(),
                info,
                record,
                args.camera_id,
                args.group_id,
                session_calibration(calibration),
            )
        )
        input = (
            ReplayInput(source, info, replay.session_dir, meta)
            if replay is not None
            else LiveInput(source, info, meta, FileRecorder() if record else None)
        )
        pipeline = CameraPipeline(
            input,
            FileSessionWriter(args.out),
            config,
            detector=detector,
            tracker=tracker,
            calibration=calibration,
            positions=positions,
            on_event=on_event,
        )
        log_event = pipeline.log_event
        pipeline.open_session(
            run_meta(settings, info, config, detector, tracker, gpu, replay, model_loaded),
        )
    except OSError as e:
        release_ctrl_c(held)
        source.close()
        print(f"error: cannot write session data under {args.out!r}: {e}", file=sys.stderr)
        return EXIT_CAPTURE_ERROR
    print(f"session: {pipeline.session_dir}")

    if args.calibration_problem:  # before any run, so no t0: t_mono is null
        problem = args.calibration_problem
        log_event(HealthEvent("error", utc_now(), None, f"calibration not used: {problem}"))
    if event := calibration_failed_event(settings.calibration_refusal):
        log_event(event)

    http_preview = None

    release_ctrl_c(held)
    status = 0
    session_status = "ended"
    until = time.perf_counter() + args.benchmark if args.benchmark else None
    try:
        # inside the try: a stop request right after "session:" must still end the session
        if stop_early.is_set():
            raise KeyboardInterrupt
        if args.http_preview is not None:
            http_preview = start_http_preview(args.http_preview, pipeline)
            print(f"preview_port: {http_preview.port}", flush=True)
        pipeline.start()
        if args.preview:
            title = f"Pointr {args.camera_id} (q to quit)" if args.camera_id else None
            run_preview(
                pipeline.latest,
                pipeline.done,
                pipeline.hud,
                pipeline.health_state,
                until,
                title,
            )
        else:
            while not pipeline.done.wait(0.1):
                if until is not None and time.perf_counter() >= until:
                    break
    except KeyboardInterrupt:
        if stop is not None and stop.ui:  # Studio's stop: a normal end (D-049)
            log_event(HealthEvent("stopped", utc_now(), time.perf_counter(), UI_STOP_DETAIL))
        else:
            session_status = "interrupted"
            status = EXIT_INTERRUPTED
            log_event(HealthEvent("interrupted", utc_now(), time.perf_counter(), "Ctrl+C"))
    except Exception as e:  # one shutdown path; the failure is an event, not a traceback
        session_status = "error"
        status = EXIT_CAPTURE_ERROR
        log_event(HealthEvent("error", utc_now(), time.perf_counter(), f"main loop: {e!r}"))
    finally:
        if http_preview is not None:
            http_preview.close()
        # The camera's shutdown path (ARCHITECTURE section 5). More Ctrl+C presses must not skip
        # a step or the final write: every wait in it is bounded, so they are ignored until the
        # session is saved.
        previous = ignore_ctrl_c()
        try:
            session_status = pipeline.stop(session_status)
        finally:
            if previous is not None:
                signal.signal(signal.SIGINT, previous)
        try:
            snapshot = pipeline.stats()
            print(f"session {pipeline.status}: {pipeline.session_dir}")
            print(
                f"t0_wall={snapshot.t0_wall} captured={snapshot.captured} "
                f"dropped={snapshot.dropped} "
                f"failed_reads={snapshot.failed_reads} processed={snapshot.processed} "
                f"unprocessed={snapshot.unprocessed} events={dict(events.copy())}"
            )
            if args.benchmark:
                det = "off" if detector is None else detector.det_size
                device = "-" if detector is None else detector.device
                print_benchmark(
                    args.benchmark,
                    info.link,
                    det,
                    device,
                    snapshot,
                    preview=args.http_preview is not None or args.preview,
                )
            print_report(pipeline.run_dir)
        except KeyboardInterrupt:
            status = EXIT_INTERRUPTED
        except OSError:  # stdout is gone (the launcher died): the files are already saved
            pass
    if (pipeline.failed or pipeline.status != session_status) and not status:
        status = EXIT_CAPTURE_ERROR
    return status


def print_report(run_dir) -> None:
    """Write report.json and print its summary. A failure is a warning: the session is saved
    and its status and exit code stay as they are (D-023)."""
    try:
        print(format_summary(write_report(run_dir)))
    except Exception as e:
        print(f"warning: report not written: {e!r}", file=sys.stderr)
    except KeyboardInterrupt:  # Ctrl+C now would turn a saved "ended" session into exit 130
        print("warning: report interrupted; run python -m services.edge.report", file=sys.stderr)


def print_benchmark(
    seconds: float,
    link: str | None,
    det: int | str,
    device: str,
    snapshot: CameraStats,
    preview: bool = False,
) -> None:
    """The A7 baseline block. Every figure comes from this run. The run time is t0 to now,
    so it includes the shutdown (about one inference)."""
    elapsed = time.perf_counter() - snapshot.t0 if snapshot.t0 else 0.0
    frame = "-" if snapshot.frame_size is None else "x".join(map(str, snapshot.frame_size))
    proc_fps, drop_rate = rates(
        snapshot.captured,
        snapshot.dropped,
        snapshot.processed,
        snapshot.first_start,
        snapshot.last_end,
    )
    fps = "-" if proc_fps is None else f"{proc_fps:.2f}"
    rate = "-" if drop_rate is None else f"{100 * drop_rate:.1f}%"
    stats = delay_stats(snapshot.delays_ms)
    delay = (
        f"p50 {stats['p50']:.1f}, p95 {stats['p95']:.1f}, max {stats['max']:.1f}" if stats else "-"
    )
    print(
        f"benchmark: {elapsed:.1f} s run ({seconds:g} s requested), link {link}, "
        f"frames {frame}, det-size {det}, device {device}, preview {'on' if preview else 'off'}, "
        f"cpu {platform.processor() or '-'}\n"
        f"benchmark: captured {snapshot.captured}, processed {snapshot.processed} "
        f"({fps} fps), dropped {snapshot.dropped} ({rate} of captured), "
        f"failed reads {snapshot.failed_reads}, unprocessed {snapshot.unprocessed}\n"
        f"benchmark: app delay ms {delay} over {len(snapshot.delays_ms)} frames"
    )


if __name__ == "__main__":
    sys.exit(main())
