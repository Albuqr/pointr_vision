"""The Studio must not point the browser at a camera preview before its server is listening
listening (testone.md, issue 2): the stream request was made once, got an empty 200, and the
<img> never asked again, so the panes stayed black while the counters ran."""

import http.server
import socket
import threading

import pytest
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from services.edge.launcher import Options
from services.edge.launcher_impl import Child, Launcher
from tests.app.test_api import Camera, FakeLauncher


@pytest.fixture
def client(tmp_path):
    FakeLauncher.instances.clear()
    config = CameraConfig(tmp_path / "config.json")
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as test_client:
        yield test_client


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_recording(client):
    client.post("/api/cameras", json={"camera_id": "cam1", "source": "0", "link": "builtin"})
    assert client.post("/api/recording/start").status_code == 200
    return FakeLauncher.instances[-1].children[0]


def test_preview_port_is_not_reported_before_the_camera_confirms_it(client):
    child = start_recording(client)
    assert child.cam.http_preview_port, "Studio picks a port for the camera"
    child.preview_ready = False  # the camera is still loading its model
    camera = client.get("/api/status").json()["cameras"][0]
    assert camera["preview_port"] is None  # so the UI shows its placeholder, not a dead <img>
    child.preview_ready = True
    camera = client.get("/api/status").json()["cameras"][0]
    assert camera["preview_port"] == child.preview_port


@pytest.mark.parametrize("kind", ["mjpeg", "snapshot.jpg"])
def test_proxy_says_503_not_an_empty_200_when_nothing_listens(client, kind):
    child = start_recording(client)
    child.preview_ready = True
    child.preview_port = free_port()  # reported, but not listening (yet, or any more)
    response = client.get(f"/api/cameras/cam1/preview/{kind}")
    assert response.status_code == 503


@pytest.mark.parametrize("kind", ["mjpeg", "snapshot.jpg"])
def test_proxy_says_503_while_the_camera_has_not_confirmed_its_port(client, kind):
    child = start_recording(client)
    child.preview_ready = False
    assert client.get(f"/api/cameras/cam1/preview/{kind}").status_code == 503


def test_proxy_passes_the_stream_through_when_the_camera_listens(client):
    body = b"--frame\r\nContent-Type: image/jpeg\r\n\r\nJPEGDATA\r\n"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        child = start_recording(client)
        child.preview_ready = True
        child.preview_port = server.server_address[1]
        response = client.get("/api/cameras/cam1/preview/mjpeg")
        assert response.status_code == 200 and response.content == body
    finally:
        server.shutdown()


def test_the_launcher_confirms_the_port_only_when_the_camera_prints_it():
    """Child.preview_port starts as the port Studio chose; only the camera's own line (it may pick
    another when that one is busy) makes it known to be listening."""

    class Proc:
        stdout = ["session: x\n", "preview_port: 51234\n"]

    cam = Camera("cam1", "0", "builtin", http_preview_port=45678)
    child = Child(cam)
    assert child.preview_port == 45678 and child.preview_ready is False
    child.proc = Proc()
    Launcher([cam], Options(out="unused", group_id="g")).read(child)
    assert child.preview_port == 51234 and child.preview_ready is True
