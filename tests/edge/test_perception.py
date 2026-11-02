"""PHASE_02 A1-A4 and the processing loop. Stub model: no torch, no weights, no camera."""

import time
from types import SimpleNamespace

import numpy as np
import pytest
from fakes import FakeSource, image

from services.edge.capture.capture import Capture
from services.edge.capture.health import HealthConfig, HealthMonitor
from services.edge.capture.types import Frame
from services.edge.perception import tracker as tracker_module
from services.edge.perception.detector import COCO_PERSON_ID, RFDETRDetector
from services.edge.perception.loop import NO_DETECTIONS, Processor, delay_stats, rates
from services.edge.perception.tracker import DEFAULT_PARAMS, ByteTrackTracker
from services.edge.perception.types import Detections, Detector, Tracker, TrackObs
from services.edge.run.args import parse_args
from services.edge.run.perception import create_tracker

CAR = 3  # a COCO category that is not a person


class StubModel:
    """Stands in for rfdetr's model: returns fixed boxes and records what it was given."""

    def __init__(self, xyxy, confidence, class_id):
        self.out = SimpleNamespace(
            xyxy=np.array(xyxy, np.float32).reshape(-1, 4),
            confidence=np.array(confidence, np.float32),
            class_id=np.array(class_id, np.int64),
        )
        self.calls = []

    def predict(self, images, threshold, shape, include_source_image):
        self.calls.append((images.copy(), threshold, shape, include_source_image))
        return self.out


def frame_of(img: np.ndarray, seq: int = 0, t_recv: float = 0.0) -> Frame:
    return Frame(seq, t_recv, "2026-10-08T12:00:00Z", img, "test")


def bgr_frame() -> Frame:
    img = np.zeros((48, 64, 3), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = 10, 20, 30  # B, G, R
    return frame_of(img)


def box(i: int) -> list[float]:
    return [10.0 * i, 5.0 * i, 10.0 * i + 40, 5.0 * i + 80]


# A1 -------------------------------------------------------------------------------------


def test_detector_keeps_only_persons_above_threshold():
    model = StubModel(
        [box(1), box(2), box(3), box(4), box(5), box(6)],
        [0.9, 0.95, 0.5, 0.49, 0.7, 0.51],
        [COCO_PERSON_ID, CAR, COCO_PERSON_ID, COCO_PERSON_ID, 0, COCO_PERSON_ID],
    )
    dets = RFDETRDetector(model, threshold=0.5, det_size=384).detect(bgr_frame())
    assert dets.class_id.tolist() == [COCO_PERSON_ID, COCO_PERSON_ID]
    assert dets.confidence.tolist() == pytest.approx([0.9, 0.51])  # 0.5 is not above 0.5
    assert (dets.confidence > 0.5).all()
    assert dets.xyxy.tolist() == [box(1), box(6)]


def test_detector_feeds_the_model_rgb_at_det_size():
    model = StubModel([], [], [])
    RFDETRDetector(model, threshold=0.4, det_size=320).detect(bgr_frame())
    [(img, threshold, shape, include_source)] = model.calls
    assert img[0, 0].tolist() == [30, 20, 10]  # R, G, B
    assert (threshold, shape, include_source) == (0.4, (320, 320), False)


def test_detector_satisfies_protocol():
    assert isinstance(RFDETRDetector(StubModel([], [], []), 0.5, 384), Detector)
    assert isinstance(ByteTrackTracker(), Tracker)


# A2 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 7])
def test_detections_shapes(n):
    model = StubModel([box(i) for i in range(n)], [0.8] * n, [COCO_PERSON_ID] * n)
    dets = RFDETRDetector(model, 0.5, 384).detect(bgr_frame())
    assert isinstance(dets, Detections)
    assert dets.xyxy.shape == (n, 4)
    assert dets.confidence.shape == (n,)
    assert dets.class_id.shape == (n,)
    assert dets.xyxy.dtype.kind == "f" and dets.confidence.dtype.kind == "f"
    assert dets.class_id.dtype.kind == "i"


# A3 / A4 --------------------------------------------------------------------------------


def dets_of(boxes: list[list[float]], conf: float = 0.9) -> Detections:
    n = len(boxes)
    return Detections(
        np.array(boxes, np.float32).reshape(-1, 4),
        np.full(n, conf, np.float32),
        np.full(n, COCO_PERSON_ID, np.int64),
    )


def run_tracker(tracker, per_frame: list[list[list[float]]], fps: float = 10.0):
    blank = np.zeros((8, 8, 3), np.uint8)
    return [
        tracker.update(dets_of(boxes), frame_of(blank, i, i / fps))
        for i, boxes in enumerate(per_frame)
    ]


def test_tracker_keeps_one_id_for_a_smoothly_moving_box():
    frames = [[[100 + 5 * i, 50, 160 + 5 * i, 200]] for i in range(30)]
    out = run_tracker(ByteTrackTracker(), frames)
    ids = {t.track_id for obs in out for t in obs}
    assert len(ids) == 1
    # confirmed after minimum_consecutive_frames, then reported on every frame
    assert all(len(obs) == 1 for obs in out[DEFAULT_PARAMS["minimum_consecutive_frames"] :])
    last = out[-1][0]
    assert isinstance(last, TrackObs)
    assert last.xyxy == pytest.approx((245.0, 50.0, 305.0, 200.0))
    assert last.confidence == pytest.approx(0.9)
    assert last.state is None  # not exposed by the library (D-016)


def test_each_person_keeps_their_own_id():
    """Two people walking toward each other; the detector lists them in a different order on
    odd frames, so an ID taken from the list position (not the tracker) would swap."""

    def a(i):
        return [50 + 3 * i, 50, 110 + 3 * i, 200]  # walks right

    def b(i):
        return [400 - 3 * i, 60, 460 - 3 * i, 210]  # walks left

    frames = [[a(i), b(i)] if i % 2 == 0 else [b(i), a(i)] for i in range(20)]
    frames += [[b(i)] for i in range(20, 30)]  # A leaves; B must not take A's ID or slot
    out = run_tracker(ByteTrackTracker(), frames)
    ids_a, ids_b = set(), set()
    for i, obs in enumerate(out[DEFAULT_PARAMS["minimum_consecutive_frames"] :], start=2):
        assert len(obs) == (2 if i < 20 else 1)
        for t in obs:  # which person is this box? the nearest left edge
            near_a = abs(t.xyxy[0] - a(i)[0]) < abs(t.xyxy[0] - b(i)[0])
            (ids_b if i >= 20 or not near_a else ids_a).add(t.track_id)
    assert len(ids_a) == 1 and len(ids_b) == 1
    assert ids_a != ids_b


def test_empty_frames_give_no_tracks():
    tracker = ByteTrackTracker()
    assert run_tracker(tracker, [[] for _ in range(5)]) == [[]] * 5


def test_empty_frames_after_tracks_give_no_tracks():
    frames = [[[100 + 5 * i, 50, 160 + 5 * i, 200]] for i in range(10)] + [[] for _ in range(5)]
    out = run_tracker(ByteTrackTracker(), frames)
    assert len(out[9]) == 1
    assert out[10:] == [[]] * 5


def test_tracker_cli_settings_map_to_effective_tracker_parameters(monkeypatch):
    captured = {}

    class FakeByteTrackTracker:
        def __init__(self, **params):
            captured.update(params)

    monkeypatch.setattr(tracker_module.trackers, "ByteTrackTracker", FakeByteTrackTracker)
    args = parse_args(
        [
            "--source",
            "0",
            "--track-lost-secs",
            "4",
            "--track-activation",
            "0.55",
            "--track-min-frames",
            "3",
        ]
    )
    tracker = create_tracker(args)

    assert captured == {
        **DEFAULT_PARAMS,
        "lost_track_buffer": 120,
        "track_activation_threshold": 0.55,
        "minimum_consecutive_frames": 3,
    }
    assert tracker.params == captured


def test_tracker_defaults_preserve_one_second_and_activation_defaults(monkeypatch):
    captured = {}

    class FakeByteTrackTracker:
        def __init__(self, **params):
            captured.update(params)

    monkeypatch.setattr(tracker_module.trackers, "ByteTrackTracker", FakeByteTrackTracker)
    tracker = ByteTrackTracker()

    assert tracker.params == DEFAULT_PARAMS
    assert captured["lost_track_buffer"] == 30
    assert captured["track_activation_threshold"] == 0.7
    assert captured["minimum_consecutive_frames"] == 2


# Processing loop ------------------------------------------------------------------------


class SleepyDetector:
    """A detector slower than capture, like RF-DETR on this CPU."""

    def __init__(self, secs: float):
        self.secs = secs

    def detect(self, frame: Frame) -> Detections:
        time.sleep(self.secs)
        return NO_DETECTIONS


class RecordingTracker:
    def __init__(self):
        self.seqs = []

    def update(self, dets: Detections, frame: Frame) -> list[TrackObs]:
        self.seqs.append(frame.seq)
        return []


def run_pipeline(n_frames: int, frame_secs: float, detector, tracker):
    events = []
    source = FakeSource((image(i) for i in range(n_frames)), delay=frame_secs)
    capture = Capture(source, HealthMonitor(HealthConfig()), events.append)
    processor = Processor(capture.proc_queue, capture.done, detector, tracker, events.append)
    capture.start()
    processor.start()
    assert processor.done.wait(30), "processing never finished"
    assert capture.stop() and processor.stop()
    return capture, processor, events


def test_slow_processing_drops_frames_and_keeps_app_delay_bounded():
    detect_secs = 0.05  # capture runs about 3x faster than processing
    tracker = RecordingTracker()
    capture, processor, events = run_pipeline(90, 1 / 60, SleepyDetector(detect_secs), tracker)
    assert events == []
    assert capture.dropped > 0
    assert capture.captured == processor.processed + capture.dropped  # nothing lost unseen
    assert tracker.seqs == sorted(set(tracker.seqs))  # tracker sees frames in seq order
    assert len(processor.delays_ms) == processor.processed
    # a frame waits at most about one detection in the queue, then one detection to finish
    assert max(processor.delays_ms) < 4 * detect_secs * 1000
    quarter = len(processor.delays_ms) // 4
    early = np.median(processor.delays_ms[:quarter])
    late = np.median(processor.delays_ms[-quarter:])
    assert late < early + detect_secs * 1000, "app delay grows: a backlog is building"


def test_processed_timings_are_ordered():
    capture, processor, _ = run_pipeline(10, 0.01, SleepyDetector(0.001), RecordingTracker())
    p = processor.latest
    assert p.frame.t_recv <= p.t_proc_start <= p.t_proc_end
    assert p.app_delay_ms == pytest.approx((p.t_proc_end - p.frame.t_recv) * 1000)


def test_capture_only_mode_counts_every_frame():
    capture, processor, events = run_pipeline(20, 0.005, None, None)
    assert events == []
    assert capture.captured == processor.processed + capture.dropped == 20
    assert processor.latest.dets.xyxy.shape == (0, 4) and processor.latest.tracks == []


def test_detector_failure_is_an_error_event():
    class Broken:
        def detect(self, frame):
            raise RuntimeError("inference exploded")

    capture, processor, events = run_pipeline(5, 0.005, Broken(), RecordingTracker())
    assert [e.kind for e in events] == ["error"]
    assert "inference exploded" in events[0].detail
    assert isinstance(processor.error, RuntimeError)
    # the failed frame and any left in the queue are counted, not lost
    assert processor.unprocessed >= 1
    assert capture.captured == processor.processed + capture.dropped + processor.unprocessed


def test_stop_mid_stream_accounts_for_every_frame():
    """q, Ctrl+C or the end of --benchmark stop capture while frames still arrive. Shutdown
    drains: the frame waiting in proc_queue is processed, so the counts add up (rule 6)."""
    events = []
    source = FakeSource((image(i) for i in range(10_000)), delay=1 / 60)
    capture = Capture(source, HealthMonitor(HealthConfig()), events.append)
    processor = Processor(
        capture.proc_queue, capture.done, SleepyDetector(0.05), RecordingTracker(), events.append
    )
    capture.start()
    processor.start()
    time.sleep(0.5)
    assert capture.stop()  # mid-stream, while a detection is running
    assert processor.stop()
    assert events == []
    assert capture.captured < 10_000 and capture.dropped > 0
    assert processor.unprocessed == 0
    assert capture.proc_queue.empty()
    assert capture.captured == processor.processed + capture.dropped


def test_rates():
    assert rates(100, 75, 25, 10.0, 15.0) == (5.0, 0.75)
    assert rates(0, 0, 0, None, None) == (None, None)
    assert rates(10, 0, 1, 2.0, 2.0) == (None, 0.0)  # one frame: no span, no rate


def test_delay_stats():
    assert delay_stats([]) is None
    stats = delay_stats([float(v) for v in range(1, 101)])
    assert stats["p50"] == pytest.approx(50.5)
    assert stats["p95"] == pytest.approx(95.05)
    assert stats["max"] == 100.0
