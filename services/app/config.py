import json
import os
import tempfile
from pathlib import Path

from services.edge.launcher import ConfigError, parse_config


def config_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    return base / "pointr" / "cameras.json"


class CameraConfig:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path()

    def read(self) -> list[dict]:
        try:
            entries = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise ConfigError(f"cannot read camera config: {exc}") from exc
        if not isinstance(entries, list):
            raise ConfigError("camera config must be a JSON list")
        if entries:
            parse_config(entries)
        return entries

    def write(self, entries: list[dict]) -> None:
        if entries:
            parse_config(entries)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix="cameras-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(entries, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
