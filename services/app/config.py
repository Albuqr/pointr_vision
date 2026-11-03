import ipaddress
import json
import os
import shutil
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from services.edge.launcher import DEFAULT_PORTS, ConfigError, check_config, url_problem
from services.edge.session.writer import mask_credentials


def resolve_camera_source(source: str) -> str:
    """Resolve and pin network camera URLs so validation and connection use one address."""
    if not isinstance(source, str) or "://" not in source:
        return source
    problem = url_problem(source)
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
    port = parts.port or DEFAULT_PORTS[parts.scheme.lower()]
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
        try:
            check_config(entries)
        except ConfigError as exc:
            self.warning = mask_credentials(
                f"Camera settings are invalid; no cameras were loaded: {exc}"
            )
            return []
        self.warning = None
        return entries

    def write(self, entries: list[dict]) -> None:
        check_config(entries)
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
                try:
                    check_config(previous)
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
