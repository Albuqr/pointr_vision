"""One camera's pipeline (R2a 02): capture and health, recorder, session writer, calibration
and frame-size checks, frame and track logging, and the final status.

The caller opens the source, loads (or shares) the detector and tracker, and builds the
session and run metadata; this piece wires them for one camera and owns the one shutdown
path of that camera (ARCHITECTURE section 5). The single-camera command uses it; the group
runner (R2a) runs one per camera. It is not a Protocol: it composes the existing ones.
"""

import dataclasses
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from services.edge.capture.capture import Capture
from services.edge.capture.health import HealthConfig, HealthMonitor
from services.edge.capture.types import HealthEvent, SourceInfo, utc_now
from services.edge.contract import VIDEO_FILE
from services.edge.perception.loop import Processor
from services.edge.power import read_power
from services.edge.session.types import FrameRecord, RunCounts, RunMeta, SessionEvent, SessionMeta
from services.edge.ui.preview import HudInfo

OnEvent = Callable[[HealthEvent, float | None], None]  # the event and the run's t0 (None before)


def load_camera_calibration(path: str, camera_id: str | None, info: SourceInfo):
    """The calibration document and its position map for this camera and capture size. Raises
    ValueError or OSError when it cannot be used: the caller stops the camera before any session."""
    from services.edge.calibration.document import load_calibration
    from services.edge.calibration.homography import CalibrationPositions

    calibration = load_calibration(path)
    if camera_id is None:
        raise ValueError("--camera-id is required when --calibration is used")
    if calibration["camera_id"] != camera_id:
        raise ValueError(
            f"calibration is for camera {calibration['camera_id']!r}, not {camera_id!r}"
        )
    size = calibration["image_size"]
    if (size["width"], size["height"]) != (info.width, info.height):
        raise ValueError(
            f"calibration image size {size['width']}x{size['height']} differs from "
            f"capture size {info.width}x{info.height}"
        )
    return calibration, CalibrationPositions(calibration)


def session_calibration(calibration: dict | None) -> dict | None:
    """The calibration block of session.json (DATA_CONTRACTS), or None for an uncalibrated run."""
    if calibration is None:
        return None
    court = calibration["court"]
    return {
        "calibration_id": calibration["calibration_id"],
        "check_error_m": calibration["errors"]["check_mean_m"],
        "court": {
            "type": court.get("type", court["kind"]),
            "length_m": court["length_m"],
            "width_m": court["width_m"],
        },
    }


class CameraPipeline:
    """Capture, processing and logging for one camera, from an opened source to a closed session.

    Use: `open_session(...)`, `start()`, wait on `done` (or stop early), then `stop(status)`,
    which always writes the final status. `replay` means the frames come from a recorded video:
    capture is lossless and each frame keeps its own video time."""

    def __init__(
        self,
        source,
        info: SourceInfo,
        writer,
        config: HealthConfig,
        *,
        detector=None,
        tracker=None,
        recorder=None,
        calibration: dict | None = None,
        positions=None,
        replay: bool = False,
        on_event: OnEvent | None = None,
    ):
        self.source = source
        self.info = info
        self.writer = writer
        self.detector = detector
        self.recorder = recorder
        self.calibration = calibration
        self.positions = positions
        self.replay = replay
        self._on_event = on_event or (lambda ev, t0: None)
        self._size_first = True
        self._size_problem: str | None = None
        self.monitor = HealthMonitor(config)
        self.capture = Capture(
            source,
            self.monitor,
            self.log_event,
            on_frame=recorder.write if recorder else None,
            lossless=replay,
            on_first_frame=lambda f: self.writer.set_ready("first_frame", f.t_wall, f.t_recv),
        )
        self.processor = Processor(
            self.capture.proc_queue,
            self.capture.done,
            detector,
            tracker,
            self.log_event,
            on_processed=self._log_frame,
            dropped=lambda: self.capture.dropped,
        )

    @property
    def done(self) -> threading.Event:
        """Set when processing has ended (the source ended, or a failure)."""
        return self.processor.done

    # -- session ---------------------------------------------------------------------------

    def open_session(
        self,
        run: RunMeta,
        meta: SessionMeta | None = None,
        session_dir: Path | str | None = None,
    ) -> None:
        """Start the session (meta) or add a run to a recorded one (session_dir, a replay), then
        the recorder. Raises OSError when the session cannot be written."""
        if self.calibration is not None:
            from services.edge.calibration.document import run_calibration

            run = dataclasses.replace(run, calibration=run_calibration(self.calibration))
        # positions only for a calibrated run: an uncalibrated run keeps the two-argument call
        if session_dir is not None:
            self.writer.start_run(session_dir, run, self.positions)
        elif self.positions:
            self.writer.start(meta, run, self.positions)
        else:
            self.writer.start(meta, run)
        if self.recorder:
            self.recorder.start(self.writer.dir / VIDEO_FILE, self.info)

    def mark_preview_ready(self) -> None:
        """The first annotated preview image is ready to serve (run.json ready, D-052)."""
        self.writer.set_ready("first_preview", utc_now(), time.perf_counter())

    def rel(self, t: float | None) -> float | None:
        """time.perf_counter() to s since the run's t0; None before t0 (D-011, D-014)."""
        t0 = self.capture.t0
        return None if t is None or t0 is None or t < t0 else t - t0

    def log_event(self, ev: HealthEvent) -> None:
        """A session event, also reported to the caller."""
        self.writer.event(SessionEvent(ev.t_wall, self.rel(ev.t_mono), ev.kind, ev.detail))
        self._on_event(ev, self.capture.t0)

    # -- per frame -------------------------------------------------------------------------

    def _frame_size_problem(self, p) -> tuple[str | None, bool]:
        """Why the calibration does not apply to this frame (a different size), else None. The
        first frame decides the run: a calibration made at another size would put every position
        in the wrong place, so the camera fails loudly. A later change (a reconnect at another
        resolution) stops the positions and is an event; the rows stay. Return whether this is the
        first-frame failure so its frame and track rows can be queued before stopping the run."""
        size = self.calibration["image_size"]
        height, width = p.frame.image.shape[:2]
        if (width, height) == (size["width"], size["height"]):
            problem = None
        else:
            problem = (
                f"frame size {width}x{height} differs from the calibration image size "
                f"{size['width']}x{size['height']}"
            )
        first_frame = self._size_first
        self._size_first = False
        if first_frame and problem:
            print(f"error: calibration cannot be used: the first {problem}", file=sys.stderr)
        if problem != self._size_problem and problem:
            self.log_event(
                HealthEvent("error", utc_now(), p.frame.t_recv, f"{problem}; no positions")
            )
        self._size_problem = problem
        return problem, bool(first_frame and problem)

    def _log_frame(self, p) -> None:
        writer, recorder = self.writer, self.recorder
        if writer.done.is_set():  # nothing is saved any more: end the run (status error)
            raise RuntimeError("session writer stopped")
        t0 = self.capture.t0
        n_dets = None if self.detector is None else len(p.dets.xyxy)
        n_tracks = None if self.detector is None else len(p.tracks)
        rec = FrameRecord(
            p.frame.seq,
            p.frame.t_recv - t0,
            p.t_proc_start - t0,
            p.t_proc_end - t0,
            n_dets,
            n_tracks,
            p.dropped_total,
            recorder.t_video(p.frame.seq) if recorder else p.frame.t_video if self.replay else None,
        )
        no_positions, first_size_mismatch = (
            self._frame_size_problem(p) if self.calibration is not None else (None, False)
        )
        writer.frame(rec)
        if p.tracks:
            if no_positions:
                writer.tracks(p.frame.seq, p.tracks, no_positions)
            else:
                writer.tracks(p.frame.seq, p.tracks)
        if first_size_mismatch:
            raise RuntimeError(f"calibration cannot be used: the first {no_positions}")

    def hud(self) -> HudInfo:
        latest = self.processor.latest
        detector = self.detector
        return HudInfo(
            capture_fps=self.capture.fps,
            dropped=self.capture.dropped,
            proc_fps=self.processor.fps,
            app_delay_ms=latest.app_delay_ms if latest else None,
            people=None if detector is None else (len(latest.dets.xyxy) if latest else 0),
            tracks=None if detector is None else (len(latest.tracks) if latest else 0),
        )

    # -- run -------------------------------------------------------------------------------

    def start(self) -> None:
        """Start capture and processing, and give the writer the run's t0."""
        self.capture.start()
        self.processor.start()
        while self.capture.t0_wall is None:  # set first thing by the capture thread
            time.sleep(0.001)
        self.writer.set_t0(self.capture.t0, self.capture.t0_wall)

    def stop(self, session_status: str) -> str:
        """The camera's shutdown path: stop capture, drain processing, stop the recorder and
        write the final status. Every wait is bounded. Returns the status written: `ended` turns
        into `error` when capture, processing or the recorder failed."""
        capture, processor, recorder, writer = (
            self.capture, self.processor, self.recorder, self.writer
        )  # fmt: skip
        # capture first, then processing drains the last frame (ARCHITECTURE section 5)
        cap_ok = capture.stop()
        # without a stopped capture there is no last frame to drain: do not wait for it
        proc_ok = processor.stop(10.0 if cap_ok else 0.0)
        if cap_ok:
            self.source.close()
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
            self.log_event(HealthEvent("error", utc_now(), time.perf_counter(), detail))
        rec_dropped = None
        if recorder:  # after capture has stopped: every frame it offered is queued
            try:  # bounded, and never in the way of the final write below
                rec = recorder.stop()
                rec_dropped = rec.frames_dropped
                if rec.frames_dropped:
                    detail = f"{rec.frames_dropped} frame(s) not recorded (queue full or failure)"
                    self.log_event(
                        HealthEvent("recorder_backlog", utc_now(), time.perf_counter(), detail)
                    )
                if recorder.size_dropped:
                    seq, (w, h) = recorder.first_size_drop
                    fw, fh = recorder.frame_size
                    detail = (
                        f"{recorder.size_dropped} frame(s) not recorded: another size than the "
                        f"first ({fw}x{fh}); the first was seq {seq} at {w}x{h}"
                    )
                    self.log_event(
                        HealthEvent("recorder_backlog", utc_now(), time.perf_counter(), detail)
                    )
                if rec.sha256:
                    writer.set_recording_sha256(rec.sha256)
            except Exception as e:
                recorder.error = recorder.error or e
            if recorder.error:
                detail = f"recording stopped: {recorder.error!r}"
                self.log_event(HealthEvent("error", utc_now(), time.perf_counter(), detail))
                session_status = "error"
        try:
            writer.set_final(power_end=read_power())
        except Exception as e:  # the end state is lost, the rest of the shutdown is not
            print(f"warning: power state at the end not recorded: {e!r}", file=sys.stderr)
        counts = RunCounts(
            capture.captured, processor.processed, capture.dropped, processor.unprocessed,
            rec_dropped,
        )  # fmt: skip
        try:
            writer.close(session_status, counts)
        except Exception as e:  # cannot write at all: say so, keep shutting down
            print(f"error: final session files not written: {e!r}", file=sys.stderr)
        return session_status

    @property
    def failed(self) -> bool:
        """Capture or processing ended with an error."""
        return bool(self.capture.error or self.processor.error)
