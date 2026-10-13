"""ByteTrack from the `trackers` package (PHASE_02, D-016). Library objects never leave it."""

import numpy as np
import supervision as sv
import trackers

from services.edge.capture.types import Frame
from services.edge.perception.types import Detections, TrackObs

# The library defaults in trackers 2.6.1 (D-016), passed explicitly so the values in use are
# the values recorded.
DEFAULT_PARAMS = {
    "lost_track_buffer": 30,  # with timestamps: a lost track is kept 30 / 30 = 1.0 s
    "frame_rate": 30.0,
    "track_activation_threshold": 0.7,
    "minimum_consecutive_frames": 2,
    "minimum_iou_threshold": 0.1,
    "high_conf_det_threshold": 0.6,
}


class ByteTrackTracker:
    """Tracker over trackers.ByteTrackTracker, fed Frame.t_recv as the timestamp, so a lost
    track is kept lost_track_buffer / 30 seconds whatever the processing rate (D-016)."""

    def __init__(
        self,
        params: dict | None = None,
        *,
        track_lost_secs: float = 1.0,
        track_activation: float = 0.7,
        track_min_frames: int = 2,
    ):
        self.params = dict(DEFAULT_PARAMS if params is None else params)
        if params is None:
            self.params["lost_track_buffer"] = max(1, round(track_lost_secs * 30))
            self.params["track_activation_threshold"] = track_activation
            self.params["minimum_consecutive_frames"] = track_min_frames
        self._bt = trackers.ByteTrackTracker(**self.params)

    def update(self, dets: Detections, frame: Frame) -> list[TrackObs]:
        sv_dets = sv.Detections(
            xyxy=dets.xyxy.astype(np.float32).reshape(-1, 4),
            confidence=dets.confidence.astype(np.float32),
            class_id=dets.class_id.astype(int),
        )
        out = self._bt.update(sv_dets, timestamp=frame.t_recv)
        return [
            TrackObs(
                track_id=int(tid),
                xyxy=tuple(float(v) for v in box),
                confidence=float(conf),
                state=None,  # the library exposes no observed/predicted state (D-016)
            )
            for box, conf, tid in zip(out.xyxy, out.confidence, out.tracker_id, strict=True)
            if tid != -1  # -1: immature or unmatched, not a track yet
        ]
