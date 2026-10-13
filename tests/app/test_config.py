import json

import pytest

from services.app.config import CameraConfig
from services.edge.launcher import ConfigError


def test_config_round_trip_and_duplicate_source_validation(tmp_path):
    store = CameraConfig(tmp_path / "cameras.json")
    cameras = [
        {"camera_id": "cam1", "source": "0", "link": "builtin"},
        {"camera_id": "cam2", "source": "http://phone:4747/video", "link": "wifi"},
    ]
    store.write(cameras)
    assert store.read() == cameras
    assert json.loads(store.path.read_text()) == cameras
    with pytest.raises(ConfigError, match="same source"):
        duplicate = {"camera_id": "cam3", "source": "http://PHONE:4747/other", "link": "wifi"}
        store.write([*cameras, duplicate])
