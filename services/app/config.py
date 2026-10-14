import ipaddress
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from services.edge.launcher import ConfigError, parse_config
from services.edge.session.writer import mask_credentials

DET_SIZES = frozenset(range(320, 1281, 32))
MAX_FPS_CAP = 60.0
URL_SCHEMES = {"http", "https", "rtsp"}


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
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            errors.append({"index": index, "field": "camera", "message": "must be an object"})
            continue
        camera_id = item.get("camera_id", f"camera {index + 1}")
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
        except (OSError, ValueError) as exc:
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
                error = ConfigError(str(exc))
                error.field_errors = [
                    {"index": None, "field": "source", "message": mask_credentials(str(exc))}
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
                    if not _field_errors(previous):
                        parse_config(previous)
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
                except (OSError, ValueError, ConfigError):
                    pass  # never replace the last good backup with a corrupt active file
            os.replace(temporary, self.path)
            self.warning = None
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
