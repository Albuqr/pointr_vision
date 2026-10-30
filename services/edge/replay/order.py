"""The order of a group replay (R2a 08, D-059): every camera keeps its own processing thread, but
its frames reach the tracker and the matcher one at a time, in the live run's group time.

The matcher's result depends on the order of its calls (D-055). Live, a frame reached it when its
camera's thread got there, which is group-time order as long as processing kept up; a replay reads
at file speed, so its threads race. Here a frame waits until no other camera has an earlier frame
still to come.
"""

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager


class GroupTimeOrder:
    """`times[camera_id](seq)` is the group time of that camera's video frame `seq`, increasing
    with seq. A camera's processing thread enters `turn(camera_id, seq)` for each of its frames in
    seq order and calls `finish(camera_id)` when they are over. A frame enters when every other
    camera that has not finished brings its next frame later (equal times: in the order of
    `times`). `close()` lets every frame through without waiting (a stop)."""

    def __init__(self, times: Mapping[str, Callable[[int], float]]):
        self._times = dict(times)
        self._rank = {camera_id: i for i, camera_id in enumerate(self._times)}
        self._next = dict.fromkeys(self._times, 0)  # the seq each camera brings next
        self._finished: set[str] = set()
        self._closed = False
        self._cv = threading.Condition()

    def _key(self, camera_id: str) -> tuple[float, int]:
        return self._times[camera_id](self._next[camera_id]), self._rank[camera_id]

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
