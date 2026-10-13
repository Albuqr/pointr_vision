"""Private per-camera calibration persistence in the local app data directory."""

import json
import os
import tempfile
import uuid
from pathlib import Path

from services.edge.calibration.document import validate_calibration
from services.edge.session.types import CAMERA_ID_RE


class CalibrationStore:
    def __init__(self, root: Path):
        self.root = Path(root) / "calibrations"

    def camera_dir(self, camera_id: str) -> Path:
        if not CAMERA_ID_RE.fullmatch(camera_id):
            raise ValueError("invalid camera id")
        return self.root / camera_id

    def save(self, document: dict, jpeg: bytes) -> Path:
        validate_calibration(document)
        directory = self.camera_dir(document["camera_id"]) / document["calibration_id"]
        directory.mkdir(parents=True, exist_ok=False)
        json_path = directory / "calibration.json"
        jpeg_path = directory / "frame.jpg"
        json_temp = directory / "calibration.json.tmp"
        jpeg_temp = directory / "frame.jpg.tmp"
        try:
            json_temp.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            jpeg_temp.write_bytes(jpeg)
            os.replace(jpeg_temp, jpeg_path)
            os.replace(json_temp, json_path)
            active = self.camera_dir(document["camera_id"]) / "active.json"
            fd, temporary = tempfile.mkstemp(dir=active.parent, prefix="active-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump({"calibration_id": document["calibration_id"]}, stream)
                os.replace(temporary, active)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except Exception:
            json_temp.unlink(missing_ok=True)
            jpeg_temp.unlink(missing_ok=True)
            raise
        return json_path

    def load(self, camera_id: str) -> dict | None:
        directory = self.camera_dir(camera_id)
        active = directory / "active.json"
        try:
            calibration_id = json.loads(active.read_text(encoding="utf-8"))["calibration_id"]
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"cannot read active calibration for {camera_id}: {exc}") from exc
        try:
            parsed_id = uuid.UUID(calibration_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("invalid active calibration id") from exc
        if parsed_id.version != 4 or str(parsed_id) != calibration_id:
            raise ValueError("invalid active calibration id")
        path = directory / calibration_id / "calibration.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read saved calibration for {camera_id}: {exc}") from exc
        document = validate_calibration(document)
        if document["camera_id"] != camera_id:
            raise ValueError("saved calibration belongs to another camera")
        return document

    def audit_frame(self, document: dict) -> bytes:
        path = (
            self.camera_dir(document["camera_id"])
            / document["calibration_id"]
            / document["audit_frame"]
        )
        return path.read_bytes()
