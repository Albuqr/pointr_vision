"""SourceHealth monitor: lost, recovered, frozen and dark (PHASE_01, D-013).

Each episode emits one event when it starts. Frozen and dark clear silently (the contract
has no "cleared" kinds); the state goes back to OK.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from services.edge.capture.types import Frame, HealthEvent, utc_now

OK, LOST, FROZEN, DARK = "OK", "LOST", "FROZEN", "DARK"


@dataclass(frozen=True)
class HealthConfig:
    """Initial values, not yet tuned on real footage (D-013)."""

    lost_reads: int = 30  # consecutive failed reads before source_lost, or
    lost_secs: float = 2.0  # failing for this long, whichever comes first (D-014)
    frozen_diff: float = 0.5  # mean abs diff of consecutive frames (0-255) below this = frozen
    frozen_secs: float = 2.0  # frozen for this long before frozen_frames
    dark_level: float = 20.0  # mean brightness (0-255) below this = dark
    dark_secs: float = 1.0  # dark for this long before dark_frames


def _mean(image: np.ndarray) -> float:
    return float(np.mean(cv2.mean(image)[:3]))


class HealthMonitor:
    """Implements SourceHealth. Frame timing uses frame.t_recv; failed reads have no frame,
    so they are timed with clock() (time.monotonic, the same clock)."""

    def __init__(
        self, config: HealthConfig | None = None, clock: Callable[[], float] = time.monotonic
    ):
        self.config = config or HealthConfig()
        self._clock = clock
        self._fails = 0
        self._fail_since: float | None = None
        self._lost = False
        self._prev: Frame | None = None
        self._dark_since: float | None = None
        self._frozen_since: float | None = None
        self._dark_fired = False
        self._frozen_fired = False

    @property
    def state(self) -> str:
        """Banner state, priority LOST > DARK > FROZEN > OK."""
        if self._lost:
            return LOST
        if self._dark_fired:
            return DARK
        return FROZEN if self._frozen_fired else OK

    def assess(self, frame: Frame | None) -> list[HealthEvent]:
        cfg = self.config
        if frame is None:
            now = self._clock()
            self._fails += 1
            if self._fail_since is None:
                self._fail_since = now
            failing = now - self._fail_since
            # time bound too: a blocking stream read can take seconds per attempt (D-014)
            if not self._lost and (self._fails >= cfg.lost_reads or failing >= cfg.lost_secs):
                self._lost = True
                detail = f"{self._fails} consecutive failed reads over {failing:.1f} s"
                return [HealthEvent("source_lost", utc_now(), now, detail)]
            return []

        events = []
        if self._lost:
            self._lost = False
            self._prev = None  # do not compare across the gap
            detail = f"after {self._fails} failed reads"
            events.append(HealthEvent("source_recovered", frame.t_wall, frame.t_recv, detail))
        self._fails = 0
        self._fail_since = None

        t = frame.t_recv
        brightness = _mean(frame.image)
        if brightness < cfg.dark_level:
            # a dark image is uninformative: it resets the frozen streak (D-013)
            self._frozen_since, self._frozen_fired = None, False
            if self._dark_since is None:
                self._dark_since = t
            if not self._dark_fired and t - self._dark_since >= cfg.dark_secs:
                self._dark_fired = True
                detail = (
                    f"mean brightness {brightness:.1f} < {cfg.dark_level} for {cfg.dark_secs} s"
                )
                events.append(HealthEvent("dark_frames", frame.t_wall, t, detail))
        else:
            self._dark_since, self._dark_fired = None, False
            prev = self._prev
            diff = None
            if prev is not None and prev.image.shape == frame.image.shape:
                diff = _mean(cv2.absdiff(frame.image, prev.image))
            if diff is not None and diff < cfg.frozen_diff:
                if self._frozen_since is None:
                    self._frozen_since = prev.t_recv
                if not self._frozen_fired and t - self._frozen_since >= cfg.frozen_secs:
                    self._frozen_fired = True
                    detail = f"mean abs diff {diff:.2f} < {cfg.frozen_diff} for {cfg.frozen_secs} s"
                    events.append(HealthEvent("frozen_frames", frame.t_wall, t, detail))
            else:
                self._frozen_since, self._frozen_fired = None, False
        self._prev = frame
        return events
