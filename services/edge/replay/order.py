"""The order of a group replay (R2a 08, D-060, D-072): every camera keeps its own processing
thread, but its frames reach the tracker and the matcher one at a time, in the order the live run
called the matcher.

The matcher's result depends on the order of its calls (D-055). Live, the cameras' threads reach it
in whatever order processing allowed, which is not always the order the frames were received; the
live run records that order (frames.csv `match_seq`). A replay reads at file speed, so its threads
race. Here a frame waits until no other camera has an earlier frame still to come. A recording
from before `match_seq` has only receive times, and its frames go in that order, approximately.
"""

import math
import threading
from bisect import bisect_left
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager


def _next_key(match_seq: Mapping[int, int]) -> Callable[[int], float]:
    """seq -> the `match_seq` of the camera's first frame from seq on that reached the matcher
    (increasing with seq); infinity when there is none."""
    seqs = sorted(match_seq)
    keys = [match_seq[s] for s in seqs]

    def key(seq: int) -> float:
        i = bisect_left(seqs, seq)
        return keys[i] if i < len(keys) else math.inf

    return key


class MatcherOrder:
    """`times[camera_id](seq)` is the group time of that camera's video frame `seq`: what the
    matcher is given. `match_seq[camera_id]` maps the video frames the live run gave to the matcher
    to the number of that call; with it, frames go in call order and a frame not in it is not
    processed (`takes`). Without it (a recording from before 0.27.0), frames go in group-time order,
    equal times in the order of `times`.

    A camera's processing thread enters `turn(camera_id, seq)` for each of its frames in seq order
    and calls `finish(camera_id)` when they are over. A frame enters when every other camera that
    has not finished brings its next frame later. `close()` lets every frame through without
    waiting (a stop)."""

    def __init__(
        self,
        times: Mapping[str, Callable[[int], float]],
        match_seq: Mapping[str, Mapping[int, int]] | None = None,
    ):
        self._times = dict(times)
        self._match_seq = match_seq
        self._keys = {c: _next_key(match_seq[c]) for c in self._times} if match_seq else self._times
        self._rank = {camera_id: i for i, camera_id in enumerate(self._times)}
        self._next = dict.fromkeys(self._times, 0)  # the seq each camera brings next
        self._finished: set[str] = set()
        self._closed = False
        self._cv = threading.Condition()

    @property
    def exact(self) -> bool:
        """Whether the order is the live call order (else approximated by receive time)."""
        return self._match_seq is not None

    def takes(self, camera_id: str, seq: int) -> bool:
        """Whether the frame is processed: always, unless the order is the live call order and the
        live run gave this frame to no matcher call."""
        return self._match_seq is None or seq in self._match_seq[camera_id]

    def _key(self, camera_id: str) -> tuple[float, int]:
        return self._keys[camera_id](self._next[camera_id]), self._rank[camera_id]

    def _first(self, camera_id: str) -> bool:
        mine = self._key(camera_id)
        return self._closed or all(
            mine < self._key(c) for c in self._times if c != camera_id and c not in self._finished
        )

    @contextmanager
    def turn(self, camera_id: str, seq: int) -> Iterator[float]:
        """Wait for the frame's turn; yields its group time. Frames of the camera it skipped (not
        processed) are not waited for."""
        with self._cv:
            self._next[camera_id] = seq
            self._cv.notify_all()
            self._cv.wait_for(lambda: self._first(camera_id))
        try:
            yield self._times[camera_id](seq)
        finally:
            with self._cv:
                self._next[camera_id] = seq + 1
                self._cv.notify_all()

    def finish(self, camera_id: str) -> None:
        with self._cv:
            self._finished.add(camera_id)
            self._cv.notify_all()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()
