"""Failure handling in a group (R2a 07, seam A, R2a-A4): one camera's stream loss or outage is
that camera's own, logged as its gap, while the others keep recording; a camera that comes back
re-links through the matcher; a failure in shared code (the detector, the matcher) ends every
camera through the one shutdown path. Synthetic clips and scripted fakes; the session folders are
read back as a reader of the files would. No camera, weights or network."""

import time
from pathlib import Path

import pytest

from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import FileSource
from services.edge.group_runner import GroupCamera, SharedCodeError, run_group
from services.edge.main import RunSettings, run_meta
from services.edge.matcher import CourtMatcher
from services.edge.perception.types import TrackObs
from services.edge.session import writer as writer_mod
from tests.edge.fakes import EvenFrameDetector, OneTrackPerDetection
from tests.edge.test_group_runner import (
    SAME_PLACE,
    TOLERANT,
    ScriptedBoxes,
    calibration_for,
    camera_files,
)
from tests.edge.test_session import validate

FAILED_READS = 40  # more than HealthConfig().lost_reads: the camera is declared lost


class Outage:
    """A source that stops answering (failed reads) after `after` frames for `reads` reads, then
    answers again; `reads=None` never comes back (the reads fail until the group stops)."""

    def __init__(self, source: FileSource, after: int, reads: int | None):
        self.source, self.after, self.reads, self.n = source, after, reads, 0
        self.kind, self.ref = source.kind, source.ref

    def open(self):
        return self.source.open()

    def read(self):
        n, self.n = self.n, self.n + 1
        if self.after <= n and (self.reads is None or n < self.after + self.reads):
            return None
        return self.source.read()

    def close(self):
        self.source.close()


class NewIdAfterGap(OneTrackPerDetection):
    """A tracker that starts a new local track after a gap in the frames, as ByteTrack does once
    its lost-track buffer is over: the camera comes back with a new local ID."""

    def __init__(self):
        self.local, self.last = 1, None

    def update(self, dets, frame):
        if self.last is not None and frame.t_recv - self.last > 0.2:
            self.local += 1
        self.last = frame.t_recv
        return [
            TrackObs(self.local, tuple(float(v) for v in box), float(c), None)
            for box, c in zip(dets.xyxy, dets.confidence, strict=True)
        ]


def run_cameras(sources, out: Path, detector, make_tracker=None, **kw) -> dict[str, str]:
    settings = RunSettings(None, None)
    config = HealthConfig()
    calibrations = kw.pop("calibrations", {})
    cameras = [
        GroupCamera(cid, source, "file", calibrations.get(cid)) for cid, source in sources.items()
    ]
    return run_group(
        "g1",
        cameras,
        detector,
        make_tracker or (lambda camera_id: OneTrackPerDetection()),
        out,
        config,
        lambda camera_id, info: run_meta(
            settings, info, config, detector, OneTrackPerDetection(), None
        ),
        record=False,
        **kw,
    )


def kinds(session: dict) -> list[str]:
    return [e["kind"] for e in session["events"]]


class StopWhen:
    """A stop event that is set once `condition()` holds (the operator stops then)."""

    def __init__(self, condition):
        self.condition = condition

    def wait(self, timeout=None):
        if not self.condition():
            time.sleep(timeout or 0)
        return self.condition()

    def is_set(self):
        return self.condition()


def test_a_camera_whose_stream_drops_leaves_the_other_recording_to_its_end(clips, tmp_path):
    """R2a-A4: cam2's stream drops after 5 frames and never returns; cam1 records its whole clip,
    the loss is cam2's own event, and the operator's stop ends both normally."""
    pipelines = {}
    stop_when_cam1_ends = StopWhen(lambda: pipelines["cam1"].done.is_set())
    statuses = run_cameras(
        {
            "cam1": FileSource(str(clips["moving"]), realtime=True),
            "cam2": Outage(FileSource(str(clips["frozen"]), realtime=False), 5, None),
        },
        tmp_path,
        EvenFrameDetector(),
        stop=stop_when_cam1_ends,
        on_session=lambda cid, p: pipelines.setdefault(cid, p),
    )
    assert statuses == {"cam1": "ended", "cam2": "ended"}
    files = camera_files(tmp_path)
    session1, run1, frames1, _ = files["cam1"]
    session2, run2, frames2, _ = files["cam2"]
    assert run1["counts"]["captured"] == 30  # the whole clip, at its own pace
    assert "source_lost" not in kinds(session1) and "error" not in kinds(session1)
    [lost] = [e for e in session2["events"] if e["kind"] == "source_lost"]
    assert lost["t_mono"] is not None and "failed reads" in lost["detail"]
    assert run2["counts"]["captured"] == 5 and len(frames2) == run2["counts"]["processed"]
    # cam1 kept recording after cam2 was lost (both runs start together, t in s since each t0)
    assert float(frames1[-1]["t_recv"]) > lost["t_mono"]
    for session, run, _, _ in files.values():
        validate("session", session)
        validate("run", run)


def test_a_camera_that_comes_back_relinks_to_the_groups_track(clips, tmp_path):
    """cam2's stream is lost for a while; it comes back with a new local track, which takes the
    group's track again by court position."""
    out = tmp_path / "out"
    run_cameras(
        {
            # paced, so cam1 is still recording when cam2 comes back
            "cam1": FileSource(str(clips["moving"]), realtime=True),
            "cam2": Outage(FileSource(str(clips["frozen"]), realtime=False), 10, FAILED_READS),
        },
        out,
        ScriptedBoxes(SAME_PLACE),
        make_tracker=lambda camera_id: NewIdAfterGap(),
        matcher=CourtMatcher(TOLERANT),
        calibrations={c: calibration_for(tmp_path, c) for c in ("cam1", "cam2")},
    )
    files = camera_files(out)
    session2 = files["cam2"][0]
    assert "source_lost" in kinds(session2) and "source_recovered" in kinds(session2)
    recovered = next(e for e in session2["events"] if e["kind"] == "source_recovered")
    ids1 = {t["track_id"] for t in files["cam1"][3]}
    _, _, frames2, tracks2 = files["cam2"]
    t_recv = {f["seq"]: float(f["t_recv"]) for f in frames2}
    after = [t for t in tracks2 if t_recv[t["seq"]] >= recovered["t_mono"]]
    assert after  # cam2 saw the person again after it came back
    assert {t["track_id"] for t in after} <= ids1 and len(ids1) == 1
    assert {t["link"] for t in after} == {"position"}


class FailsOn(EvenFrameDetector):
    """The shared detector fails on one camera's frame `seq`."""

    def __init__(self, clip: str, seq: int):
        super().__init__()
        self.clip, self.at = clip, seq
        self.on_fail = lambda: None  # what the test looks at when the failure comes

    def detect(self, frame):
        if Path(frame.source_id).name == self.clip and frame.seq == self.at:
            self.on_fail()
            raise RuntimeError("inference exploded")
        return super().detect(frame)


class FailingMatcher(CourtMatcher):
    """The shared matcher fails on its `n`-th update."""

    def __init__(self, n: int):
        super().__init__()
        self.n = n

    def update(self, camera_id, t_recv, tracks):
        self.n -= 1
        if self.n == 0:
            raise RuntimeError("matcher exploded")
        return super().update(camera_id, t_recv, tracks)


@pytest.mark.parametrize(
    ("failing", "on_long_camera", "at_seq"),
    [
        ("detector", False, 8),  # the long camera is still running when the failure comes
        ("detector", True, 40),  # the failing long camera is the last one running
        ("matcher", None, None),  # the 12th update fails, whichever camera makes it
    ],
)
def test_a_failure_in_shared_code_ends_every_camera_with_an_error_and_readable_files(
    clips, long_clips, tmp_path, failing, on_long_camera, at_seq
):
    """R2a-A4, NFR-004: every session.json has a final status and an error event, and every CSV
    reads back with its header."""
    long_camera = FileSource(str(long_clips[0]), realtime=True)  # 30 s at its own pace
    # paced too when the long camera fails, so it has ended (2 s) before the failure (2.7 s)
    short_camera = FileSource(str(clips["frozen"]), realtime=bool(on_long_camera))
    failing_clip = Path((long_camera if on_long_camera else short_camera).ref).name
    detector = FailsOn(failing_clip, at_seq) if failing == "detector" else EvenFrameDetector()
    matcher = FailingMatcher(12) if failing == "matcher" else None
    pipelines, done_at_failure = {}, {}
    if failing == "detector":
        detector.on_fail = lambda: done_at_failure.update(
            {cid: p.done.is_set() for cid, p in pipelines.items()}
        )
    with pytest.raises(SharedCodeError, match="exploded"):
        run_cameras(
            {"cam1": long_camera, "cam2": short_camera}, tmp_path, detector, matcher=matcher,
            on_session=lambda cid, p: pipelines.setdefault(cid, p),
        )  # fmt: skip
    if failing == "detector":  # the case this run tests did happen
        assert done_at_failure == {"cam1": False, "cam2": bool(on_long_camera)}
    files = camera_files(tmp_path)
    assert set(files) == {"cam1", "cam2"}
    for session, run, frames, tracks in files.values():
        validate("session", session)
        validate("run", run)
        assert session["status"] == "error" and run["counts"] is not None
        [group_error] = [e for e in session["events"] if e["detail"].startswith("group: ")]
        assert group_error["kind"] == "error" and "exploded" in group_error["detail"]
        assert len(frames) == run["counts"]["processed"]
        assert list(frames[0]) == writer_mod.FRAMES_COLUMNS
        assert list(tracks[0]) == writer_mod.TRACKS_COLUMNS
    assert files["cam1"][1]["counts"]["captured"] < 30 * 15  # ended by the failure, not its end


def test_a_failure_in_one_cameras_own_tracker_ends_only_that_camera(clips, tmp_path):
    class Fails(OneTrackPerDetection):
        def update(self, dets, frame):
            if frame.seq == 4:
                raise RuntimeError("tracker exploded")
            return super().update(dets, frame)

    statuses = run_cameras(
        {
            "cam1": FileSource(str(clips["moving"]), realtime=True),
            "cam2": FileSource(str(clips["frozen"]), realtime=False),
        },
        tmp_path,
        EvenFrameDetector(),
        make_tracker=lambda camera_id: Fails() if camera_id == "cam2" else OneTrackPerDetection(),
    )
    assert statuses == {"cam1": "ended", "cam2": "error"}
    files = camera_files(tmp_path)
    assert files["cam1"][1]["counts"]["captured"] == 30  # cam1 recorded its whole clip
    assert "error" not in kinds(files["cam1"][0])
    assert any("tracker exploded" in e["detail"] for e in files["cam2"][0]["events"])
