"""One camera's pipeline, driven directly (R2a 02): capture and health, the session writer, the
recorder, the calibration checks, frame and track logging and the final status, with the source,
writer, recorder, detector and tracker passed in. The group runner (R2a) reuses it per camera;
these tests read back the session folder it leaves, as a reader of the files would."""

import uuid
from pathlib import Path

from services.edge.camera_pipeline import CameraPipeline
from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import FileSource
from services.edge.capture.types import HealthEvent, utc_now
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
    pipeline = CameraPipeline(
        source,
        info,
        writer,
        HealthConfig(),
        detector=detector,
        tracker=tracker,
        recorder=FileRecorder() if record else None,
        on_event=lambda ev, t0: reported.append((ev, t0)),
    )
    meta = SessionMeta(
        str(uuid.uuid4()), device_id(out), utc_now(), info, record, "cam1", None, None
    )
    pipeline.open_session(sample_run_meta("clip"), meta=meta)
    pipeline.start()
    pipeline.done.wait(30)
    status = pipeline.stop("ended")
    return pipeline, status, reported


def test_a_clip_run_through_the_pipeline_leaves_a_complete_session(clips, tmp_path):
    pipeline, status, _ = run_pipeline(clips["moving"], tmp_path, record=True)
    assert status == "ended"
    session, run, frames, tracks = session_files(tmp_path)
    assert session["status"] == "ended" and session["camera_id"] == "cam1"
    assert run["counts"]["processed"] == len(frames) == pipeline.processor.processed > 0
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
