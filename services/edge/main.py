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

import argparse
import dataclasses
import math
import platform
import re
import sys
import threading
import time
import uuid
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import cv2
import numpy as np

from services.edge.calibration.intake import FromFile, FromRun, NotUsed, Refused, take_calibration
from services.edge.camera_pipeline import (
    CameraPipeline,
    CameraStats,
    LiveInput,
    ReplayInput,
)
from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import (
    DEFAULT_CAPTURE_SIZE,
    CameraSource,
    FileSource,
    SourceOpenError,
    open_source,
)
from services.edge.capture.types import HealthEvent, utc_now
from services.edge.contract import VIDEO_FILE
from services.edge.perception.detector import DET_SIZE_MULTIPLE
from services.edge.perception.loop import delay_stats, rates
from services.edge.power import read_power
from services.edge.recording.recorder import FileRecorder
from services.edge.replay.resolve import ReplayError, resolve_replay
from services.edge.reports.build import format_summary, write_report

# Moved to services.edge.run (T9); re-exported until T12, tests replace these names on this module
from services.edge.run.perception import (  # noqa: F401
    create_tracker,
    load_perception,
    resolve_device,
    start_perception,
)
from services.edge.run.stop import (  # noqa: F401
    EXIT_INTERRUPTED,
    StopRequest,
    hold_ctrl_c,
    ignore_ctrl_c,
    release_ctrl_c,
    stdin_ready,
    stop_before_session,
    stop_end,
    stop_on_stdin,
    stop_source,
)
from services.edge.session.types import CAMERA_ID_RE, GROUP_ID_RE, RunMeta, SessionMeta
from services.edge.session.writer import FileSessionWriter, device_id
from services.edge.ui.preview import run_preview

EXIT_OPEN_FAILED = 2
EXIT_CAPTURE_ERROR = 1


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
    return take_calibration(Refused(refusal), None, (0, 0)).checks


def calibration_failed_event(refusal: str | None) -> HealthEvent | None:
    """The `startup_check_failed` event that goes with `failed_calibration_checks`. No t0 yet,
    so t_mono is null."""
    if not refusal:
        return None
    return take_calibration(Refused(refusal), None, (0, 0)).events[0]


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
        return stop_before_session(stop, print_event)


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
        calibration=pipeline.calibration.preview_document() if pipeline.calibration else None,
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
            return run_replay(args, group, stop)
    ref = args.replay or args.source
    replay = None
    offer = FromFile(args.calibration) if args.calibration else None
    if offer is None and args.calibration_failed:
        offer = Refused(args.calibration_failed)
    elif offer is None and args.calibration_problem:
        offer = NotUsed(args.calibration_problem)
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
            if offer is None and replay.session_dir is not None:
                from services.edge.session.folder import SessionDamaged, read_session

                saved = read_session(replay.session_dir)
                try:
                    if not saved.runs or saved.runs[0] is None:
                        raise ReplayError("the recorded session has no readable live run")
                    live = saved.runs[0]
                    block = live.require().get("calibration")
                except SessionDamaged as exc:
                    raise ReplayError(str(exc)) from exc
                # Tolerant snapshots replace malformed optional fields with None; damage is
                # a refused offer, while a genuinely absent calibration stays uncalibrated.
                if any("calibration" in problem for problem in live.problems):
                    block = {}
                offer = FromRun(block) if block is not None else None
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

    perception = start_perception(
        args, resolve_device=resolve_device, load_perception=load_perception, emit=print_event
    )
    if perception is None:
        return EXIT_CAPTURE_ERROR
    detector, tracker = perception.detector, perception.tracker

    try:
        info = source.open()
    except (SourceOpenError, cv2.error) as e:
        return open_failed(ref, e)

    info = dataclasses.replace(info, link=args.link)
    intake = take_calibration(offer, args.camera_id, (info.width, info.height))
    calibration = intake.calibration
    positions = calibration.positions() if calibration else None
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
                calibration.session_block() if calibration else None,
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
            dataclasses.replace(
                run_meta(
                    settings,
                    info,
                    config,
                    detector,
                    tracker,
                    perception.gpu,
                    replay,
                    perception.model_loaded,
                ),
                checks=intake.checks,
            ),
        )
    except OSError as e:
        release_ctrl_c(held)
        source.close()
        print(f"error: cannot write session data under {args.out!r}: {e}", file=sys.stderr)
        return EXIT_CAPTURE_ERROR
    print(f"session: {pipeline.session_dir}")

    for event in intake.events:
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
        end = stop_end(ui=stop is not None and stop.ui, session=True)
        session_status, status = end.status, end.exit_code
        log_event(end.event(time.perf_counter()))
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
            release_ctrl_c(previous)
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
