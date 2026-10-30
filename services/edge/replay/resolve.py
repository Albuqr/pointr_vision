"""Find the video a replay reads (PHASE_04, RF09, RNF05)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from services.edge.capture.sources import FILE_SUFFIXES
from services.edge.contract import VIDEO_FILE
from services.edge.session.folder import SessionDamaged, find_sessions, read_session


class ReplayError(Exception):
    """The replay target cannot be used. The message is the reason shown to the user."""


@dataclass(frozen=True)
class ReplayTarget:
    video: Path
    sha256: str
    session_dir: Path | None  # the session the replay adds a run to; None for a bare video file
    camera_id: str | None  # of that session
    verified: bool = True  # False when the video could not be checked against session.json


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_session(target: str, out_dir: Path) -> Path | None:
    found = find_sessions(out_dir, session_id=target)
    return found[0].path if found else None


def resolve_replay(target: str, out_dir: Path | str) -> ReplayTarget:
    """target: a .mp4/.mov/.mkv file, a session folder, or a session id found under out_dir.

    A bare file starts a new session. A session adds a run to it and its video must still be the
    one that was recorded (sha256 of session.json), because labels and runs refer to its frames."""
    path = Path(target)
    if path.suffix.lower() in FILE_SUFFIXES and path.is_file():
        video = path.resolve()
        return ReplayTarget(video, sha256_file(video), None, None)
    folder = path if path.is_dir() else _find_session(target, Path(out_dir))
    if folder is None:
        raise ReplayError(f"no video file, session folder or session id {target!r}")
    try:
        snapshot = read_session(folder)
        session = snapshot.require()
        recording = snapshot.get("recording")
        if recording is not None:
            snapshot.require(
                *(
                    f"recording.{key}"
                    for key in ("path", "sha256")
                    if recording.get(key) is not None
                ),
                expected=str,
            )
    except SessionDamaged as e:
        raise ReplayError(str(e)) from e
    # the file the session says it recorded (an older session may be a video.mp4), inside its folder
    name = (session.get("recording") or {}).get("path") or VIDEO_FILE
    video = (folder / name).resolve()
    if folder.resolve() not in video.parents or not video.is_file():
        raise ReplayError(f"{folder} has no {name} (was it recorded with --no-record?)")
    sha = sha256_file(video)
    expected = (session.get("recording") or {}).get("sha256")
    if expected and expected != sha:
        raise ReplayError(
            f"{video} changed since it was recorded: sha256 {sha[:12]}... differs from "
            f"session.json {expected[:12]}..."
        )
    return ReplayTarget(video, sha, folder.resolve(), session.get("camera_id"), bool(expected))
