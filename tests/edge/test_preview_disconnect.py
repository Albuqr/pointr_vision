"""Phase 03 B3 end to end: preview clients that leave mid-run write no traceback and the
session still ends normally with every frame accounted for."""

import socket
import struct
import threading
import time

import pytest

from services.edge import main as cli
from tests.edge.fakes import EvenFrameDetector
from tests.edge.test_session import run_main, session_files, validate


class SlowDetector(EvenFrameDetector):
    def detect(self, frame):
        time.sleep(0.03)  # the run lasts long enough for clients to come and go
        return super().detect(frame)


def leave_mid_stream(port: int, abrupt: bool, done: threading.Event, ports: list[int]):
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    ports.append(client.getsockname()[1])
    client.sendall(b"GET /mjpeg HTTP/1.0\r\n\r\n")
    data = b""
    while b"--frame" not in data:
        chunk = client.recv(65536)
        assert chunk, "the server closed the stream"
        data += chunk
    if abrupt:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    client.close()
    done.set()


@pytest.mark.parametrize("abrupt", [False, True], ids=["closed", "dropped-socket"])
def test_b3_a_preview_client_leaving_does_not_stop_the_session(
    monkeypatch, tmp_path, clips, capfd, abrupt
):
    out = tmp_path / "sessions"
    left = threading.Event()
    ports: list[int] = []
    start = cli.start_http_preview

    def start_and_connect(port, pipeline):
        preview = start(port, pipeline)
        threading.Thread(
            target=leave_mid_stream, args=(preview.port, abrupt, left, ports), daemon=True
        ).start()
        return preview

    monkeypatch.setattr(cli, "start_http_preview", start_and_connect)
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        "--http-preview", "0", detector=SlowDetector(),
    )  # fmt: skip
    assert code == 0
    assert left.is_set(), "the client must have connected and left during the run"
    session, run, frames, _ = session_files(out)
    validate("run", run)
    assert session["status"] == "ended"
    counts = run["counts"]  # contract: captured = processed + dropped + unprocessed on a clean stop
    assert counts["captured"] == counts["processed"] + counts["dropped"] + counts["unprocessed"]
    assert len(frames) == counts["processed"]
    output = capfd.readouterr()
    text = output.out + output.err
    assert "Traceback" not in text
    # the server did see the client go: one plain line for it (absence is data)
    mine = f"preview client 127.0.0.1:{ports[0]} left"
    assert sum(mine in line for line in text.splitlines()) == 1
