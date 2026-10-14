import ipaddress
import json
import math
import os
import shutil
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from services.edge.launcher import ConfigError, parse_config
from services.edge.session.types import CAMERA_ID_RE
from services.edge.session.writer import mask_credentials

DET_SIZES = frozenset(range(320, 1281, 32))
MAX_FPS_CAP = 60.0
URL_SCHEMES = {"http", "https", "rtsp"}


def resolve_camera_source(source: str) -> str:
    """Resolve and pin network camera URLs so validation and connection use one address."""
    if not isinstance(source, str) or "://" not in source:
        return source
    problem = _url_problem(source)
    if problem:
        raise ConfigError(problem)
    parts = urlsplit(source)
    host = parts.hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        return source
    port = parts.port or {"http": 80, "https": 443, "rtsp": 554}[parts.scheme.lower()]
    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ConfigError(f"camera hostname could not be resolved: {host}") from exc
    addresses = []
    for result in results:
        try:
            resolved = ipaddress.ip_address(result[4][0])
        except ValueError:
            continue
        # A hostname is only accepted when every answer is globally routable. This
        # prevents a mixed DNS response from selecting an internal service.
        if not resolved.is_global:
            raise ConfigError("camera hostname resolves to a non-public address")
        addresses.append(resolved)
    if not addresses:
        raise ConfigError("camera hostname did not resolve to an IP address")
    pinned = addresses[0]
    netloc = ""
    if parts.username is not None:
        netloc = parts.netloc.rsplit("@", 1)[0] + "@"
    netloc += f"[{pinned}]" if pinned.version == 6 else str(pinned)
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _url_problem(source: str) -> str | None:
    try:
        parts = urlsplit(source)
        if parts.scheme.lower() not in URL_SCHEMES:
            return "URL scheme must be http, https, or rtsp"
        host = parts.hostname
        if not host:
            return "URL must include a host"
        if host.lower() == "localhost" or host.lower().endswith(".localhost"):
            return "loopback camera URLs are not allowed"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and (
            address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            or address.is_multicast
        ):
            return "loopback and link-local camera URLs are not allowed"
        _ = parts.port  # reject malformed ports
    except ValueError:
        return "URL is malformed"
    return None


def _field_errors(entries) -> list[dict]:
    if not isinstance(entries, list):
        return [{"index": None, "field": "cameras", "message": "must be a list"}]
    errors = []
    names: dict[str, int] = {}
    camera_ids: dict[str, int] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            errors.append({"index": index, "field": "camera", "message": "must be an object"})
            continue
        camera_id = item.get("camera_id", f"camera {index + 1}")
        if not isinstance(camera_id, str) or not CAMERA_ID_RE.fullmatch(camera_id):
            errors.append(
                {
                    "index": index,
                    "field": "camera_id",
                    "message": "use 1-32 letters, digits, _ or -",
                }
            )
        elif camera_id in camera_ids:
            errors.append({"index": index, "field": "camera_id", "message": "ID must be unique"})
        camera_ids[str(camera_id)] = index
        name = item.get("name", camera_id)
        if not isinstance(name, str) or not name.strip():
            errors.append({"index": index, "field": "name", "message": "name is required"})
        else:
            key = name.strip().casefold()
            if key in names:
                errors.append({"index": index, "field": "name", "message": "name must be unique"})
            names[key] = index
        source = item.get("source")
        if isinstance(source, int) and not isinstance(source, bool):
            source = str(source)
        if not isinstance(source, str) or not source.strip():
            errors.append({"index": index, "field": "source", "message": "source is required"})
        elif "://" in source or source.lower().startswith(("http:", "https:", "rtsp:", "file:")):
            problem = _url_problem(source)
            if problem:
                errors.append({"index": index, "field": "source", "message": problem})
        det_size = item.get("det_size")
        if det_size is not None and (
            not isinstance(det_size, int) or isinstance(det_size, bool) or det_size not in DET_SIZES
        ):
            errors.append(
                {"index": index, "field": "det_size", "message": "choose an allowed detection size"}
            )
        fps_cap = item.get("fps_cap")
        valid_fps = fps_cap is None
        if isinstance(fps_cap, (int, float)) and not isinstance(fps_cap, bool):
            try:
                valid_fps = math.isfinite(float(fps_cap)) and 0 < fps_cap <= MAX_FPS_CAP
            except OverflowError:
                valid_fps = False
        if not valid_fps:
            errors.append(
                {
                    "index": index,
                    "field": "fps_cap",
                    "message": "must be greater than 0 and at most 60",
                }
            )
        if "enabled" in item and not isinstance(item["enabled"], bool):
            errors.append({"index": index, "field": "enabled", "message": "must be true or false"})
        link = item.get("link", "builtin")
        if not isinstance(link, str) or link not in {"builtin", "usb", "wifi", "file"}:
            errors.append(
                {"index": index, "field": "link", "message": "choose a listed connection type"}
            )
    return errors


def config_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    return base / "pointr" / "cameras.json"


class CameraConfig:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path()
        self.warning: str | None = None

    def read(self) -> list[dict]:
        try:
            entries = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.warning = None
            return []
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            self.warning = mask_credentials(
                f"Camera settings could not be read: {exc}. Add cameras again."
            )
            return []
        errors = _field_errors(entries)
        if errors:
            self.warning = (
                "Camera settings are invalid; no cameras were loaded. "
                "Review or replace cameras.json."
            )
            return []
        try:
            if entries:
                parse_config(entries)
        except ConfigError as exc:
            self.warning = mask_credentials(
                f"Camera settings are invalid; no cameras were loaded: {exc}"
            )
            return []
        self.warning = None
        return entries

    def write(self, entries: list[dict]) -> None:
        errors = _field_errors(entries)
        if errors:
            error = ConfigError("camera settings have field errors")
            error.field_errors = errors
            raise error
        if entries:
            try:
                parse_config(entries)
            except ConfigError as exc:
                detail = str(exc)
                field = next(
                    (
                        key
                        for key in ("camera_id", "det_size", "track_", "link", "source")
                        if key in detail
                    ),
                    "source",
                )
                if field == "track_":
                    field = next(
                        (
                            key
                            for key in ("track_lost_secs", "track_activation", "track_min_frames")
                            if key in detail
                        ),
                        "source",
                    )
                error = ConfigError(str(exc))
                error.field_errors = [
                    {"index": None, "field": field, "message": mask_credentials(detail)}
                ]
                raise error from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix="cameras-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(entries, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            backup = self.path.with_name(self.path.name + ".bak")
            if self.path.exists():
                try:
                    previous = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError, UnicodeError, RecursionError):
                    previous = None
                if previous is not None and not _field_errors(previous):
                    try:
                        if previous:
                            parse_config(previous)
                    except ConfigError:
                        pass  # never replace the last good backup with a corrupt active file
                    else:
                        backup_fd, backup_temporary = tempfile.mkstemp(
                            dir=self.path.parent, prefix="cameras-backup-", suffix=".tmp"
                        )
                        os.close(backup_fd)
                        try:
                            shutil.copyfile(self.path, backup_temporary)
                            os.replace(backup_temporary, backup)
                        finally:
                            if os.path.exists(backup_temporary):
                                os.unlink(backup_temporary)
            os.replace(temporary, self.path)
            self.warning = None
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
