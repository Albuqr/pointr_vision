"""Typed edge/launcher lines; DATA_CONTRACTS section 16 owns the wire format.

The module has no run state. The launcher decides whether a failure happened before a
session opened. Multiline text produces one independently parseable message per line.
"""

import re
import sys
from dataclasses import dataclass
from typing import Literal, TextIO, TypeAlias, get_args

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
        if separator and kind in get_args(FailureKind):
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
        header, payload = "", "stop ui" if message.source else "stop"
    elif isinstance(message, PreviewListening):
        header, payload = "", f"preview_port: {message.port}"
    elif isinstance(message, Summary):
        header, payload = "", message.detail
    elif isinstance(message, SessionOpened):
        header, payload = "session: ", message.path
    elif isinstance(message, DeviceChosen):
        header, payload = "device: ", message.device
    elif isinstance(message, StartFailed):
        header, payload = f"error: {message.kind}: ", message.detail
    else:
        raise TypeError(f"unknown protocol message {message!r}")
    output = (
        stream
        if stream is not None
        else (sys.stderr if isinstance(message, StartFailed) else sys.stdout)
    )
    if header:
        # Repeat the message header on each payload line so no line can inject another message.
        payload = payload.replace("\r\n", "\n").replace("\r", "\n")
        lines = [header + part for part in payload.split("\n")]
    else:
        if "\n" in payload or "\r" in payload:
            raise ValueError("summary must be one physical line")
        lines = [payload]
    for line in lines:
        output.write(mask_credentials(prefix + line) + "\n")
    output.flush()
