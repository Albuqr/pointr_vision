import json
import os
from pathlib import Path

import pytest

from services.app.config import CameraConfig, resolve_camera_source
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


def test_camera_settings_defaults_and_per_field_validation(tmp_path):
    store = CameraConfig(tmp_path / "cameras.json")
    store.write([{"camera_id": "cam1", "source": "0", "link": "builtin"}])
    camera = store.read()[0]
    assert camera.get("name", camera["camera_id"]) == "cam1"
    assert camera.get("enabled", True) is True
    assert camera.get("fps_cap") is None
    with pytest.raises(ConfigError) as raised:
        store.write(
            [
                {"camera_id": "cam1", "name": "Court", "source": "0", "link": "builtin"},
                {
                    "camera_id": "cam2",
                    "name": "court",
                    "source": "",
                    "link": "builtin",
                    "det_size": 333,
                    "fps_cap": 0,
                },
            ]
        )
    assert {(error["index"], error["field"]) for error in raised.value.field_errors} == {
        (1, "name"),
        (1, "source"),
        (1, "det_size"),
        (1, "fps_cap"),
    }


@pytest.mark.parametrize(
    "entry,missing_field",
    [
        ({"source": "0", "link": "builtin"}, "camera_id"),
        ({"camera_id": "cam1", "source": "0"}, "link"),
    ],
)
def test_camera_settings_require_camera_id_and_link(tmp_path, entry, missing_field):
    path = tmp_path / "cameras.json"
    path.write_text(json.dumps([entry]), encoding="utf-8")
    store = CameraConfig(path)
    assert store.read() == []
    assert store.warning and "invalid" in store.warning.lower()
    with pytest.raises(ConfigError) as raised:
        store.write([entry])
    assert raised.value.field_errors[0]["field"] == missing_field


@pytest.mark.parametrize(
    "source",
    [
        "file:///etc/passwd",
        "ftp://camera.example/video",
        "http://localhost:8080/admin",
        "http://127.0.0.1:9000/admin",
        "http://169.254.169.254/latest/meta-data",
        "rtsp://[fe80::1]/stream",
    ],
)
def test_unsafe_or_unsupported_camera_urls_are_rejected(tmp_path, source):
    store = CameraConfig(tmp_path / "cameras.json")
    with pytest.raises(ConfigError):
        store.write([{"camera_id": "cam1", "source": source, "link": "wifi"}])


def test_camera_hostname_is_resolved_validated_and_pinned(monkeypatch):
    import socket

    def public_answer(host, port, **kwargs):
        assert host == "camera.example"
        assert port == 4747
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", public_answer)
    assert resolve_camera_source("rtsp://user:secret@camera.example:4747/live") == (
        "rtsp://user:secret@93.184.216.34:4747/live"
    )


@pytest.mark.parametrize("resolved", ["127.0.0.1", "169.254.169.254", "10.0.0.5"])
def test_camera_hostname_rejects_private_or_link_local_dns_answers(monkeypatch, resolved):
    import socket

    from services.edge.launcher import ConfigError

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved, port))
        ],
    )
    with pytest.raises(ConfigError, match="non-public"):
        resolve_camera_source("http://camera.example/live")


def test_camera_hostname_rejects_mixed_dns_answers(monkeypatch):
    import socket

    from services.edge.launcher import ConfigError

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ],
    )
    with pytest.raises(ConfigError, match="non-public"):
        resolve_camera_source("http://camera.example/live")


def test_camera_settings_keep_backup_and_active_file_on_replace_failure(tmp_path, monkeypatch):
    store = CameraConfig(tmp_path / "cameras.json")
    original = [{"camera_id": "cam1", "source": "0", "link": "builtin"}]
    replacement = [{"camera_id": "cam1", "source": "1", "link": "builtin"}]
    store.write(original)
    real_replace = os.replace
    calls = 0

    def fail_active_replace(source, destination):
        nonlocal calls
        calls += 1
        if Path(destination) == store.path:
            raise PermissionError("simulated crash before settings replace")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_active_replace)
    with pytest.raises(PermissionError, match="simulated crash"):
        store.write(replacement)
    assert calls == 2
    assert json.loads(store.path.read_text()) == original
    assert json.loads(store.path.with_name("cameras.json.bak").read_text()) == original


def test_backup_replace_failure_does_not_replace_the_last_good_settings(tmp_path, monkeypatch):
    store = CameraConfig(tmp_path / "cameras.json")
    original = [{"camera_id": "cam1", "source": "0", "link": "builtin"}]
    replacement = [{"camera_id": "cam1", "source": "1", "link": "builtin"}]
    store.write(original)
    real_replace = os.replace

    def fail_backup_replace(source, destination):
        if Path(destination).name == "cameras.json.bak":
            raise PermissionError("simulated backup failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_backup_replace)
    with pytest.raises(PermissionError, match="simulated backup"):
        store.write(replacement)
    assert json.loads(store.path.read_text()) == original
    assert not list(tmp_path.glob("cameras-*.tmp"))


@pytest.mark.parametrize(
    "contents", ["{broken", "[]x", "null", '[{"camera_id":"cam1","source":"0","link":[]}]']
)
def test_corrupt_camera_settings_load_empty_with_warning(tmp_path, contents):
    path = tmp_path / "cameras.json"
    path.write_text(contents, encoding="utf-8")
    store = CameraConfig(path)
    assert store.read() == []
    assert store.warning and "camera settings" in store.warning.lower()
