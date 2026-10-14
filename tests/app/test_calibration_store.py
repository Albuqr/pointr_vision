"""Calibration files are written durably (fsync before the rename), the rename survives a brief
Windows lock, and the Studio's frame cache is only touched under its lock."""

import copy
import json
import os
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from services.app import calibrations
from services.app.calibrations import CalibrationStore
from services.app.config import CameraConfig
from services.app.server import create_app
from tests.app.test_api import FakeLauncher
from tests.fixtures.make_clips import make_clips

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = json.loads(
    (ROOT / "tests/fixtures/contracts/calibration.example.json").read_text(encoding="utf-8")
)


def document():
    doc = copy.deepcopy(EXAMPLE)
    doc.update(camera_id="cam1", calibration_id=str(uuid.uuid4()))
    return doc


def test_every_file_is_fsynced_before_it_is_renamed(tmp_path, monkeypatch):
    events = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(
        calibrations.os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd))
    )
    monkeypatch.setattr(
        calibrations.os, "replace", lambda a, b: (events.append("replace"), real_replace(a, b))
    )
    CalibrationStore(tmp_path).save(document(), b"jpeg")
    # frame.jpg, calibration.json and the active.json pointer: each synced, then renamed
    assert events == ["fsync", "replace"] * 3


def test_a_brief_windows_lock_on_the_target_is_retried(tmp_path, monkeypatch):
    real_replace, refusals = os.replace, []

    def locked_twice(source, target):
        if Path(target).name == "active.json" and len(refusals) < 2:
            refusals.append(target)
            raise PermissionError(13, "held by another process")
        real_replace(source, target)

    monkeypatch.setattr(calibrations.os, "replace", locked_twice)
    monkeypatch.setattr(calibrations, "REPLACE_DELAY_S", 0)
    doc = document()
    store = CalibrationStore(tmp_path)
    store.save(doc, b"jpeg")
    assert len(refusals) == 2
    assert store.load("cam1")["calibration_id"] == doc["calibration_id"]


def test_a_lock_that_never_clears_fails_cleanly_and_keeps_the_old_calibration(
    tmp_path, monkeypatch
):
    store = CalibrationStore(tmp_path)
    first = document()
    store.save(first, b"jpeg")

    real_replace = os.replace

    def locked_pointer(source, target):
        if Path(target).name == "active.json":
            raise PermissionError(13, "held by another process")
        real_replace(source, target)

    monkeypatch.setattr(calibrations.os, "replace", locked_pointer)
    monkeypatch.setattr(calibrations, "REPLACE_DELAY_S", 0)
    with pytest.raises(PermissionError):
        store.save(document(), b"jpeg")
    assert store.load("cam1")["calibration_id"] == first["calibration_id"]
    assert not list((tmp_path / "calibrations" / "cam1").glob("active-*.tmp"))


class LockedDict(dict):
    """A dict that fails if it is touched while the Studio lock is not held by this thread."""

    def __init__(self, studio):
        super().__init__()
        self.studio = studio

    def _held(self):
        assert self.studio.lock._is_owned(), "calibration_frames used without the Studio lock"

    def get(self, *args):
        self._held()
        return super().get(*args)

    def __setitem__(self, key, value):
        self._held()
        super().__setitem__(key, value)


def test_the_frame_cache_is_only_used_under_the_studio_lock(tmp_path):
    clip = make_clips(tmp_path)["moving"]
    config = CameraConfig(tmp_path / "config.json")
    config.write([{"camera_id": "clip", "source": str(clip), "link": "file"}])
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        studio = client.app.state.studio
        studio.calibration_frames = LockedDict(studio)
        token = client.get("/api/cameras/clip/calibration/frame").headers["x-frame-token"]
        stale = client.post(
            "/api/cameras/clip/calibration/fit", json={"frame_token": "x", "points": []}
        )
        assert stale.status_code == 409 and token
