"""What Studio remembers about each camera for the current run of the app: the last error
(kept until dismissed or until the camera next starts) and the last EVENT_LIMIT events.

Held in memory by Studio and served by /api/status, so a page reload shows the same thing.
Every string goes through mask_credentials on the way in: nothing here can leak a password."""

import datetime as dt
import threading
from collections import deque
from collections.abc import Callable, Mapping

from services.edge.session.folder import SessionSnapshot
from services.edge.session.writer import mask_credentials

EVENT_LIMIT = 50
DETAIL_LIMIT = 4000  # characters of technical detail kept per error


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


class CameraLog:
    def __init__(self, on_error: Callable[[str, str], None] | None = None):
        self.on_error = on_error  # told of every error set, already masked (audit trail)
        self.lock = threading.Lock()
        self.last_error: dict | None = None
        self.events: deque[dict] = deque(maxlen=EVENT_LIMIT)  # oldest first
        self.seen: dict[str, int] = {}  # session folder -> events already copied
        self.reported_child: object | None = None  # the launcher child whose end was reported

    def set_error(self, message: str, detail: str = "") -> None:
        with self.lock:
            self.last_error = {
                "message": mask_credentials(message),
                "detail": mask_credentials(detail)[-DETAIL_LIMIT:],
                "at": now_iso(),
            }
            message, detail = self.last_error["message"], self.last_error["detail"]
        if self.on_error:
            self.on_error(message, detail)

    def clear_error(self) -> None:
        with self.lock:
            self.last_error = None

    def add_event(self, kind: str, detail, at: str | None = None) -> None:
        with self.lock:
            self.events.append(
                {
                    "t_wall": at or now_iso(),
                    "kind": kind,
                    "detail": None if detail is None else mask_credentials(str(detail)),
                }
            )

    def ingest_session(self, session: SessionSnapshot) -> None:
        """Ingest the reader's validated events from the same snapshot as status."""
        if session.data is None:
            self.ingest_session_events(
                f"{session.path}#reader", [{"kind": "error", "detail": "; ".join(session.problems)}]
            )
        self.ingest_session_events(str(session.path), session.events or ())

    def ingest_session_events(self, session_key: str, events: list) -> None:
        """Copy the events a session.json gained since the last poll."""
        with self.lock:
            start = self.seen.get(session_key, 0)
            fresh = events[start:]
            self.seen[session_key] = start + len(fresh)
        for event in fresh:
            if isinstance(event, Mapping):
                kind = str(event.get("kind"))
                detail = event.get("detail")
                if kind == "error" and "frame size" in str(detail).lower():
                    kind = "frame_size_mismatch"
                self.add_event(kind, detail, event.get("t_wall"))

    def snapshot(self) -> dict:
        """Newest event first."""
        with self.lock:
            return {
                "last_error": dict(self.last_error) if self.last_error else None,
                "recent_events": list(reversed(self.events)),
            }
