"""One camera's pipeline, driven directly (R2a 02): capture and health, the session writer, the
recorder, the calibration checks, frame and track logging and the final status, with the source,
writer, recorder, detector and tracker passed in. The group runner (R2a) reuses it per camera;
these tests read back the session folder it leaves, as a reader of the files would."""

import dataclasses
import json
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from services.edge.camera_pipeline import CameraPipeline, LiveInput, ReplayInput
from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import FileSource
from services.edge.capture.types import Frame, HealthEvent, SourceEnded, SourceInfo, utc_now
from services.edge.contract import VIDEO_FILE
from services.edge.recording.recorder import FileRecorder
from services.edge.session.types import SessionMeta
from services.edge.session.writer import FileSessionWriter, device_id
from tests.edge.fakes import EvenFrameDetector, OneTrackPerDetection, sample_run_meta
from tests.edge.test_session import session_files


def run_pipeline(clip: Path, out: Path, *, detector=None, tracker=None, record=False):
    """Open, run to the end of the clip, stop. Returns the pipeline and the events it reported."""
    source = FileSource(str(clip), realtime=False)
    info = source.open()
    reported: list[tuple[HealthEvent, float | None]] = []
    writer = FileSessionWriter(out)
    meta = SessionMeta(
        str(uuid.uuid4()), device_id(out), utc_now(), info, record, "cam1", None, None
    )
    pipeline = CameraPipeline(
        LiveInput(source, info, meta, FileRecorder() if record else None),
        writer,
        HealthConfig(),
        detector=detector,
        tracker=tracker,
        on_event=lambda ev, t0: reported.append((ev, t0)),
    )
    pipeline.open_session(sample_run_meta("clip"))
    pipeline.start()
    pipeline.done.wait(30)
    status = pipeline.stop("ended")
    return pipeline, status, reported


def test_a_clip_run_through_the_pipeline_leaves_a_complete_session(clips, tmp_path):
    pipeline, status, _ = run_pipeline(clips["moving"], tmp_path, record=True)
    assert status == "ended"
    session, run, frames, tracks = session_files(tmp_path)
    assert session["status"] == "ended" and session["camera_id"] == "cam1"
    assert run["counts"]["processed"] == len(frames) == pipeline.stats().processed > 0
    stats = pipeline.stats()
    assert run["counts"] == {key: getattr(stats, key) for key in run["counts"]}
    # no detector: the count is absent, not zero
    assert all(f["n_detections"] == "" for f in frames)
    assert tracks == []
    folder = next(p for p in tmp_path.iterdir() if p.is_dir())
    assert (folder / VIDEO_FILE).stat().st_size > 0
    assert session["recording"]["sha256"]


def test_detections_and_tracks_are_logged_for_every_processed_frame(clips, tmp_path):
    _, status, _ = run_pipeline(
        clips["moving"], tmp_path, detector=EvenFrameDetector(), tracker=OneTrackPerDetection()
    )
    assert status == "ended"
    _, _, frames, tracks = session_files(tmp_path)
    even = [f for f in frames if int(f["seq"]) % 2 == 0]
    assert len(tracks) == len(even) > 0
    assert {f["n_detections"] for f in frames} == {"0", "1"}  # zero-detection frames get a row too


def test_a_processing_error_ends_the_session_with_status_error_and_an_event(clips, tmp_path):
    _, status, reported = run_pipeline(
        clips["moving"],
        tmp_path,
        detector=EvenFrameDetector(fail_at=3),
        tracker=OneTrackPerDetection(),
    )
    assert status == "error"
    session, run, _, _ = session_files(tmp_path)
    assert session["status"] == "error" and run["counts"] is not None
    assert any(e["kind"] == "error" for e in session["events"])
    assert any(ev.kind == "error" for ev, _ in reported)  # the caller hears it too


class CountedSource:
    def open(self):
        self.seq = -1
        return SourceInfo("file", "synthetic", 8, 8, 30, "file")

    def read(self):
        self.seq += 1
        if self.seq == 0:
            return None
        if self.seq > 20:
            raise SourceEnded
        return Frame(self.seq, time.perf_counter(), utc_now(), np.zeros((8, 8, 3)), "test")

    def close(self):
        pass


class DroppingRecorder:
    """A recorder adapter reporting known recording loss, independently of processing loss."""

    error = None
    size_dropped = 0

    def start(self, path, info):
        self.offered = 0

    def write(self, frame):
        self.offered += 1

    def t_video(self, seq):
        return None

    def stop(self):
        return SimpleNamespace(frames_dropped=self.offered, sha256=None)


@pytest.mark.parametrize("replay", [False, True])
def test_t7_all_final_counters_match_files_for_live_and_replay(tmp_path, replay):
    source = CountedSource()
    info = source.open()
    meta = SessionMeta(str(uuid.uuid4()), device_id(tmp_path), utc_now(), info, not replay)
    input = (
        ReplayInput(source, info, meta=meta)
        if replay
        else LiveInput(source, info, meta, DroppingRecorder())
    )
    pipeline = CameraPipeline(input, FileSessionWriter(tmp_path), HealthConfig(lost_reads=1))
    seen = []
    pipeline.on_preview(lambda frame: seen.append(frame.frame.seq))
    pipeline.open_session(
        dataclasses.replace(sample_run_meta("clip"), mode="replay" if replay else "live")
    )
    pipeline.start()
    with pytest.raises(RuntimeError, match="before start"):
        pipeline.on_preview(lambda frame: None)
    assert pipeline.done.wait(5)
    assert pipeline.stop("ended") == "ended"
    stats = pipeline.stats()
    run = json.loads((pipeline.run_dir / "run.json").read_text())
    assert run["counts"] == {key: getattr(stats, key) for key in run["counts"]}
    assert stats.captured == 20 and stats.failed_reads == 1
    assert stats.processed == len(seen) and len(set(seen)) == len(seen)
    assert stats.captured == stats.processed + stats.dropped + stats.unprocessed
    assert stats.rec_dropped == (None if replay else 20)
    if replay:
        assert stats.processed == 20 and stats.dropped == 0
    events = json.loads((pipeline.session_dir / "session.json").read_text())["events"]
    assert "source_lost" in {event["kind"] for event in events}
    assert pipeline.health_state() is not None
    assert pipeline.latest() is not None and pipeline.raw_snapshot().shape == (8, 8, 3)
    with pytest.raises(dataclasses.FrozenInstanceError):
        stats.captured = 0


def test_t7_replay_adds_a_run_without_recording(clips, tmp_path):
    live, _, _ = run_pipeline(clips["moving"], tmp_path, record=True)
    video = live.session_dir / VIDEO_FILE
    original_video = video.read_bytes()
    source = FileSource(str(video), realtime=False)
    pipeline = CameraPipeline(
        ReplayInput(source, source.open(), live.session_dir),
        FileSessionWriter(tmp_path),
        HealthConfig(),
    )
    pipeline.open_session(dataclasses.replace(sample_run_meta("clip"), mode="replay"))
    pipeline.start()
    assert pipeline.done.wait(5)
    assert pipeline.stop("ended") == "ended"
    session = json.loads((live.session_dir / "session.json").read_text())
    assert len(session["runs"]) == 2 and video.read_bytes() == original_video
    assert not (pipeline.run_dir / VIDEO_FILE).exists()
    run = json.loads((pipeline.run_dir / "run.json").read_text())
    assert run["counts"] == {key: getattr(pipeline.stats(), key) for key in run["counts"]}
    assert pipeline.stats().rec_dropped is None


def test_t7_shared_code_error_is_exposed_and_unprocessed_count_is_saved(tmp_path):
    from services.edge.group_runner import SharedCodeError

    failure = SharedCodeError("synthetic shared failure")
    third_read = threading.Event()

    class BufferedSource(CountedSource):
        def read(self):
            frame = super().read()
            if frame is not None and frame.seq == 3:
                third_read.set()
            return frame

    class FailingDetector:
        def detect(self, frame):
            assert third_read.wait(2)  # queue full before the failing frame finishes
            raise failure

    source = BufferedSource()
    info = source.open()
    meta = SessionMeta(str(uuid.uuid4()), device_id(tmp_path), utc_now(), info, False)
    pipeline = CameraPipeline(
        ReplayInput(source, info, meta=meta),
        FileSessionWriter(tmp_path),
        HealthConfig(),
        detector=FailingDetector(),
        tracker=OneTrackPerDetection(),
    )
    pipeline.open_session(sample_run_meta("clip"))
    pipeline.start()
    assert pipeline.done.wait(5)
    assert pipeline.error is failure
    assert pipeline.stop("ended") == "error"
    stats = pipeline.stats()
    assert stats.unprocessed > 0 and stats.dropped > 0
    run = json.loads((pipeline.run_dir / "run.json").read_text())
    assert run["counts"] == {key: getattr(stats, key) for key in run["counts"]}


def test_t7_benchmark_uses_a_handmade_stats_snapshot(capsys):
    from services.edge.camera_pipeline import CameraStats
    from services.edge.main import print_benchmark

    print_benchmark(
        10,
        "file",
        "off",
        "-",
        CameraStats(
            captured=10,
            processed=6,
            dropped=3,
            unprocessed=1,
            failed_reads=2,
            first_start=1,
            last_end=3,
            delays_ms=(10, 20),
            frame_size=(640, 480),
        ),
    )
    text = capsys.readouterr().out
    assert "frames 640x480" in text
    assert "captured 10, processed 6 (3.00 fps), dropped 3 (30.0%" in text
    assert "failed reads 2, unprocessed 1" in text
    assert "p50 15.0, p95 19.5, max 20.0" in text
    assert "over 2 frames" in text
