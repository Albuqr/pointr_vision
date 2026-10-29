"""Phase 03 B5 (D-052): run.json `ready` holds when the model loaded, the first frame arrived and
the first preview image was ready. A step that did not happen is null, never 0."""

import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime

from services.edge.camera_pipeline import CameraPipeline
from services.edge.capture.health import HealthConfig
from services.edge.capture.types import SourceInfo, utc_now
from services.edge.session.types import SessionMeta
from services.edge.session.writer import FileSessionWriter, device_id
from tests.edge.test_camera_pipeline import _run
from tests.edge.test_session import (
    EvenFrameDetector,
    run_main,
    session_files,
    validate,
)


def parsed(step: dict) -> datetime:
    return datetime.fromisoformat(step["t_wall"])


def test_a_live_run_records_all_three_ready_times(monkeypatch, tmp_path, clips):
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        "--http-preview", "0", detector=EvenFrameDetector(),
    )  # fmt: skip
    assert code == 0
    _, run, _, _ = session_files(out)
    validate("run", run)
    ready = run["ready"]
    assert set(ready) == {"model_loaded", "first_frame", "first_preview"}
    assert all(ready[step] is not None for step in ready)
    # the order a start goes through; t_pc is the PC clock, the base of t0_mono
    assert ready["model_loaded"]["t_pc"] <= ready["first_frame"]["t_pc"]
    assert ready["first_frame"]["t_pc"] <= ready["first_preview"]["t_pc"]
    assert parsed(ready["model_loaded"]) <= parsed(ready["first_frame"])
    assert ready["first_frame"]["t_pc"] >= run["t0_mono"]


def test_without_detection_and_preview_those_times_are_null(monkeypatch, tmp_path, clips):
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file", "--no-detect"
    )
    assert code == 0
    _, run, _, _ = session_files(out)
    validate("run", run)
    assert run["ready"]["model_loaded"] is None
    assert run["ready"]["first_preview"] is None
    assert run["ready"]["first_frame"] is not None


def test_detection_without_the_http_preview_has_no_first_preview(monkeypatch, tmp_path, clips):
    out = tmp_path / "sessions"
    run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        detector=EvenFrameDetector(),
    )  # fmt: skip
    _, run, _, _ = session_files(out)
    assert run["ready"]["model_loaded"] is not None
    assert run["ready"]["first_preview"] is None


class SilentSource:
    """Opens, then never delivers a frame."""

    kind = "stream"

    def open(self):
        return SourceInfo("stream", "silent", 640, 360, None)

    def read(self):
        time.sleep(0.01)
        return None

    def close(self):
        pass


def test_a_run_stopped_before_its_first_frame_keeps_the_times_it_reached(tmp_path):
    source = SilentSource()
    info = source.open()
    pipeline = CameraPipeline(source, info, FileSessionWriter(tmp_path), HealthConfig())
    loaded = {"t_wall": utc_now(), "t_pc": time.perf_counter()}
    meta = SessionMeta(str(uuid.uuid4()), device_id(tmp_path), utc_now(), info, False, "cam1")
    run = replace(
        _run(),
        health=asdict(HealthConfig()),
        runtime={"python": "3.11.9", "platform": "test", "device": None, "gpu": None,
                 "packages": {"opencv": None, "numpy": None, "torch": None, "supervision": None}},
        ready={"model_loaded": loaded},
    )  # fmt: skip
    pipeline.open_session(run, meta=meta)
    pipeline.start()
    time.sleep(0.1)
    pipeline.stop("interrupted")
    _, run, _, _ = session_files(tmp_path)
    validate("run", run)
    assert run["ready"] == {"model_loaded": loaded, "first_frame": None, "first_preview": None}
