"""Studio's audit trail: an append-only JSON Lines file of every operator action and error
(DATA_CONTRACTS section 10, D-054).

Each entry is one line written and flushed before the caller goes on, so a crash can tear at
most the last line. Every string goes through mask_credentials on the way in."""

import json
import logging
import os
import threading
from pathlib import Path

from services.app.camera_log import now_iso
from services.edge.session.writer import mask_credentials


def _masked(value):
    if isinstance(value, str):
        return mask_credentials(value)
    if isinstance(value, dict):
        return {key: _masked(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_masked(item) for item in value]
    return value


log = logging.getLogger(__name__)


class AuditTrail:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.failed_writes = 0  # entries that could not be written (locked or full disk)
        self.lock = threading.Lock()

    def record(self, action: str, camera_id: str | None, outcome: str = "ok", detail=None) -> None:
        entry = {
            "t_wall": now_iso(),
            "action": action,
            "camera_id": camera_id,
            "outcome": _masked(outcome),
            "detail": _masked(detail),
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("ab+") as handle:
                    if handle.seek(0, os.SEEK_END) and self._last_byte(handle) != b"\n":
                        handle.write(
                            b"\n"
                        )  # a crash tore the last line: end it, keep this one whole
                    handle.write(line.encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                # The action being audited has already happened or failed on its own; a trail
                # that cannot be written must not change that. Counted and said, not raised.
                self.failed_writes += 1
                log.warning("audit entry not written (%s): %s", action, exc)

    @staticmethod
    def _last_byte(handle) -> bytes:
        handle.seek(-1, os.SEEK_END)
        byte = handle.read(1)
        handle.seek(0, os.SEEK_END)
        return byte

    def read(self) -> list[dict]:
        """Every readable entry, oldest first; a torn or garbled line is skipped."""
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries
