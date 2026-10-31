"""The stop policy of a run (R2a follow-up T9, D-069): the stop request, the Ctrl+C hold and ignore
helpers, and the one table that says how a stop ends a run, whoever stopped it (Studio or Ctrl+C)
and whichever phase it came in (before any session exists, or with sessions open: group setup and
mid-run alike). main, group_main, group_runner and the group replay all end a stop through it."""

import _thread
import dataclasses
import select
import signal
import sys
import threading
import time
from collections.abc import Callable

from services.edge.capture.types import HealthEvent, utc_now
from services.edge.child_protocol import Stop, parse
from services.edge.contract import UI_STOP_DETAIL

EXIT_INTERRUPTED = 130


@dataclasses.dataclass
class StopRequest:
    """Where the launcher's stop came from: `source` is "ui" after a `stop ui` line (Studio's
    stop, D-049) and None after a plain `stop`, the pipe closing, or a Ctrl+C."""

    source: str | None = None

    @property
    def ui(self) -> bool:
        """Studio's stop: the session ends `ended` with a `stopped` event, not `interrupted`."""
        return self.source == "ui"


@dataclasses.dataclass(frozen=True)
class StopEnd:
    """How a stop ends the run: the event to log, the sessions' final status (None: no session was
    opened) and the exit code."""

    kind: str
    detail: str
    status: str | None
    exit_code: int

    def event(self, t_mono: float | None) -> HealthEvent:
        """t_mono is None before any run, so before any t0 (D-014)."""
        return HealthEvent(self.kind, utc_now(), t_mono, self.detail)


# (Studio's stop, a session is open) -> the end. A Studio stop is a normal end (D-049) at every
# phase; any other stop is an interruption.
STOP_ENDS = {
    (True, False): StopEnd("stopped", UI_STOP_DETAIL, None, 0),
    (False, False): StopEnd("interrupted", "Ctrl+C", None, EXIT_INTERRUPTED),
    (True, True): StopEnd("stopped", UI_STOP_DETAIL, "ended", 0),
    (False, True): StopEnd("interrupted", "Ctrl+C", "interrupted", EXIT_INTERRUPTED),
}


def stop_end(*, ui: bool, session: bool) -> StopEnd:
    """The end of a stop that arrived with a session open (`session`) or before any."""
    return STOP_ENDS[(ui, session)]


def stop_before_session(
    stop: StopRequest, emit: Callable[[HealthEvent, float | None], None]
) -> int:
    """End a run stopped before its sessions exist (model load, slow stream open): print the event
    through `emit` (main.print_event) and return the exit code."""
    end = stop_end(ui=stop.ui, session=False)
    emit(end.event(None), None)
    return end.exit_code


def stop_source(line: str) -> str | None:
    """The source a stop line names; anything but `stop ui` is a plain stop."""
    message = parse(line.strip())[1]
    return message.source if isinstance(message, Stop) else None


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
