"""What a run prints (R2a follow-up T11, D-071): the event line, the benchmark block, the report
summary, and the `Reporter` that says them for one camera (plain) or for each camera of a group
(tagged `[camera_id] `, so the launcher can tell them apart). Lines about the whole run (the device,
the model load, a stop before any session) are never tagged."""

import platform
import sys
import time

from services.edge.camera_pipeline import CameraStats
from services.edge.capture.types import HealthEvent, utc_now
from services.edge.child_protocol import Message, StartFailed, emit
from services.edge.perception.loop import delay_stats, rates
from services.edge.reports.build import format_summary, write_report


def print_event(ev: HealthEvent, t0: float | None, prefix: str = "") -> None:
    rel = f"+{ev.t_mono - t0:.2f}s" if t0 is not None else "-"
    try:
        print(f"{prefix}[{ev.t_wall}] {rel} {ev.kind}: {ev.detail}", flush=True)
    except OSError:  # the launcher that read this pipe is gone: the event still goes to the file
        pass


def format_benchmark(
    seconds: float,
    link: str | None,
    det: int | str,
    device: str,
    snapshot: CameraStats,
    preview: bool = False,
) -> str:
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
    return (
        f"benchmark: {elapsed:.1f} s run ({seconds:g} s requested), link {link}, "
        f"frames {frame}, det-size {det}, device {device}, preview {'on' if preview else 'off'}, "
        f"cpu {platform.processor() or '-'}\n"
        f"benchmark: captured {snapshot.captured}, processed {snapshot.processed} "
        f"({fps} fps), dropped {snapshot.dropped} ({rate} of captured), "
        f"failed reads {snapshot.failed_reads}, unprocessed {snapshot.unprocessed}\n"
        f"benchmark: app delay ms {delay} over {len(snapshot.delays_ms)} frames"
    )


def print_benchmark(*args, **kwargs) -> None:
    print(format_benchmark(*args, **kwargs))


def print_report(run_dir) -> None:
    """Write report.json and print its summary. A failure is a warning: the session is saved
    and its status and exit code stay as they are (D-023)."""
    Reporter().report(None, run_dir)


class Reporter:
    """Says a run's lines. tagged=False is one camera: no tag, so a single camera's output is the
    same on every path. tagged=True is a group: `[camera_id] ` before every line about a camera."""

    def __init__(self, tagged: bool = False):
        self.tagged = tagged

    def _tag(self, camera_id: str | None) -> str:
        return f"[{camera_id}] " if self.tagged and camera_id is not None else ""

    def event(self, camera_id: str | None, ev: HealthEvent, t0: float | None) -> None:
        print_event(ev, t0, self._tag(camera_id))

    def line(self, camera_id: str | None, text: str) -> None:
        try:
            for line in text.splitlines():
                print(self._tag(camera_id) + line, flush=True)
        except OSError:  # the launcher that read this pipe is gone: the files still get everything
            pass

    def tell(self, camera_id: str | None, message: Message) -> None:
        """A protocol line (child_protocol), with `line`'s pipe-gone guard."""
        try:
            emit(message, camera_id if self.tagged else None)
        except OSError:
            pass

    def unverified(self, camera_id: str | None) -> None:
        """A replay of a session whose video has no hash."""
        if self.tagged:
            self.line(
                camera_id, "warning: the session has no video hash, so the video is unchecked"
            )
        else:
            print(
                "warning: the session has no video hash (its recording did not finish), so "
                "the video cannot be checked against it",
                file=sys.stderr,
            )

    def source_open_failed(self, camera_id: str | None, ref: str, reason: str) -> None:
        """No run, so no t0: the event's t_mono is null (D-014). A single camera also prints the
        event line, which the launcher shows when it has no `error:` line to show."""
        if self.tagged:
            self.tell(camera_id, StartFailed("source_open_failed", f"cannot open source: {reason}"))
            return
        self.event(None, HealthEvent("source_open_failed", utc_now(), None, reason), None)
        self.tell(None, StartFailed("source_open_failed", f"cannot open source {ref!r}: {reason}"))

    def report(self, camera_id: str | None, run_dir) -> None:
        """Write report.json and say its summary. A failure is a warning: the session is saved and
        its status and exit code stay as they are (D-023)."""
        who = f"{camera_id}: " if self.tagged and camera_id is not None else ""
        try:
            self.line(camera_id, format_summary(write_report(run_dir)))
        except Exception as e:
            print(f"warning: {who}report not written: {e!r}", file=sys.stderr)
        except KeyboardInterrupt:  # Ctrl+C now would turn a saved "ended" session into exit 130
            print(
                f"warning: {who}report interrupted; run python -m services.edge.report",
                file=sys.stderr,
            )
