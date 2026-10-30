"""Typed edge/launcher lines; DATA_CONTRACTS section 16 owns the wire format.

The module has no run state. The launcher decides whether a failure happened before a
session opened. Multiline text produces one independently parseable message per line.
"""

import re
import sys
from dataclasses import dataclass
from typing import Literal, TextIO, TypeAlias

from services.edge.session.types import CAMERA_ID_RE
from services.edge.session.writer import mask_credentials

FailureKind = Literal[
    "source_open_failed",
    "model_load_failed",
    "calibration_refused",
    "config_conflict",
    "start_timeout",
    "spawn_failed",
    "exited",
]
FAILURE_KINDS = (
    "source_open_failed",
    "model_load_failed",
    "calibration_refused",
    "config_conflict",
    "start_timeout",
    "spawn_failed",
    "exited",
)


@dataclass(frozen=True)
class SessionOpened:
    path: str


@dataclass(frozen=True)
class DeviceChosen:
    device: str


@dataclass(frozen=True)
class PreviewListening:
    port: int

    def __post_init__(self):
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("preview port must be an integer in 1..65535")


@dataclass(frozen=True)
class StartFailed:
    kind: FailureKind
    detail: str

    def __post_init__(self):
        if self.kind not in FAILURE_KINDS:
            raise ValueError(f"unknown failure kind {self.kind!r}")


@dataclass(frozen=True)
class Summary:
    detail: str

    @property
    def failed_reads(self) -> str | None:
        match = re.search(r"\bfailed_reads=(\d+)\b", self.detail)
        return match.group(1) if match else None


@dataclass(frozen=True)
class Stop:
    source: Literal["ui"] | None = None

    def __post_init__(self):
        if self.source not in (None, "ui"):
            raise ValueError(f"unknown stop source {self.source!r}")


Message: TypeAlias = SessionOpened | DeviceChosen | PreviewListening | StartFailed | Summary | Stop
_CAMERA = re.compile(r"^\[([^\]\s]+)\] (.*)$")


def parse(line: str) -> tuple[str | None, Message | None]:
    """Read one physical line; legacy errors keep their complete detail as kind exited."""
    text = mask_credentials(line.rstrip("\r\n"))
    camera = None
    if match := _CAMERA.fullmatch(text):
        camera, text = match.groups()
    if text.startswith("session: "):
        return camera, SessionOpened(text[len("session: ") :])
    if text.startswith("device: "):
        return camera, DeviceChosen(text[len("device: ") :])
    if text.startswith("preview_port: "):
        try:
            return camera, PreviewListening(int(text[len("preview_port: ") :]))
        except ValueError:
            return camera, None
    if text.startswith("error: "):
        detail = text[len("error: ") :]
        kind, separator, reason = detail.partition(": ")
        if separator and kind in FAILURE_KINDS:
            return camera, StartFailed(kind, reason)
        return camera, StartFailed("exited", detail)
    if text.startswith("t0_wall=") and Summary(text).failed_reads is not None:
        return camera, Summary(text)
    if camera is None and text in ("stop", "stop ui"):
        return None, Stop("ui" if text == "stop ui" else None)
    return camera, None


def emit(message: Message, camera_id: str | None = None, *, stream: TextIO | None = None) -> None:
    """Write and flush complete physical lines. Stop requires the child's stdin stream."""
    if camera_id is not None and (not CAMERA_ID_RE.fullmatch(camera_id)):
        raise ValueError(f"camera id must match {CAMERA_ID_RE.pattern}")
    prefix = f"[{camera_id}] " if camera_id is not None else ""
    if isinstance(message, Stop):
        if camera_id is not None or stream is None:
            raise ValueError("stop requires an untagged explicit stdin stream")
        text = "stop ui" if message.source else "stop"
    elif isinstance(message, SessionOpened):
        text = "session: " + message.path
    elif isinstance(message, DeviceChosen):
        text = "device: " + message.device
    elif isinstance(message, PreviewListening):
        text = f"preview_port: {message.port}"
    elif isinstance(message, StartFailed):
        text = f"error: {message.kind}: " + message.detail
    elif isinstance(message, Summary):
        text = message.detail
    else:
        raise TypeError(f"unknown protocol message {message!r}")
    output = (
        stream
        if stream is not None
        else (sys.stderr if isinstance(message, StartFailed) else sys.stdout)
    )
    # Repeat the message header on each payload line so no line can inject another message.
    if isinstance(message, (SessionOpened, DeviceChosen, StartFailed)):
        header, payload = (
            ("session: ", message.path)
            if isinstance(message, SessionOpened)
            else ("device: ", message.device)
            if isinstance(message, DeviceChosen)
            else (f"error: {message.kind}: ", message.detail)
        )
        lines = [
            header + part for part in payload.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        ]
    else:
        if "\n" in text or "\r" in text:
            raise ValueError("summary must be one physical line")
        lines = [text]
    for line in lines:
        output.write(mask_credentials(prefix + line) + "\n")
    output.flush()
