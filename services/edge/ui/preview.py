"""OpenCV preview window: the latest processed frame with its tracks, the source state banner
and a HUD (processing FPS, app delay, people, tracks, drops). q closes."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from services.edge.perception.loop import Processed
from services.edge.perception.types import TrackObs

WINDOW = "Pointr (q to quit)"
FONT = cv2.FONT_HERSHEY_SIMPLEX
# state -> (banner text, BGR colour); the text tells the user what to do
BANNERS = {
    "OK": ("OK", (60, 180, 60)),
    "LOST": ("LOST: no frames, check camera connection", (40, 40, 220)),
    "FROZEN": ("FROZEN: image frozen, check camera connection", (0, 140, 255)),
    "DARK": ("DARK: image too dark, check lens and lighting", (0, 220, 220)),
}
TRACK_COLOUR = (255, 200, 0)
HUD_STRIP = 50  # px of dark strip at the bottom for two status lines
REFRESH_MS = 30  # window refresh; longer waits leave the CPU to detection


@dataclass(frozen=True)
class HudInfo:
    capture_fps: float | None
    dropped: int
    proc_fps: float | None
    app_delay_ms: float | None
    people: int | None  # None when detection is off
    tracks: int | None


def _num(value: float | None, fmt: str) -> str:
    return "--" if value is None else format(value, fmt)


def draw_tracks(image: np.ndarray, tracks: list[TrackObs]) -> np.ndarray:
    """A copy of image with each track's box and #id label."""
    out = image.copy()
    for t in tracks:
        x1, y1, x2, y2 = (int(round(v)) for v in t.xyxy)
        cv2.rectangle(out, (x1, y1), (x2, y2), TRACK_COLOUR, 2)
        cv2.putText(out, f"#{t.track_id}", (x1, max(y1 - 6, 14)), FONT, 0.6, TRACK_COLOUR, 2)
    return out


def draw_hud(image: np.ndarray, state: str, hud: HudInfo) -> np.ndarray:
    """A copy of image with the banner on top and the counters on a dark strip below.

    The counters are drawn once, white on a filled strip. Phase 01 drew them twice (a thick
    black outline under thin white text), which read as doubled text (phase 01 A6)."""
    out = image.copy()
    h, w = out.shape[:2]
    text, colour = BANNERS[state]
    cv2.rectangle(out, (0, 0), (w, 34), colour, thickness=-1)
    cv2.putText(out, text, (10, 24), FONT, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
    if hud.people is None:
        perception = "detection off"
    else:
        perception = (
            f"proc {_num(hud.proc_fps, '.1f')} fps  app delay {_num(hud.app_delay_ms, '.0f')} ms"
            f"  people {hud.people}  tracks {hud.tracks}"
        )
    capture = f"capture {_num(hud.capture_fps, '.1f')} fps  dropped {hud.dropped}"
    cv2.rectangle(out, (0, h - HUD_STRIP), (w, h), (0, 0, 0), thickness=-1)
    for i, line in enumerate((perception, capture)):
        y = h - HUD_STRIP + 20 + 22 * i
        cv2.putText(out, line, (10, y), FONT, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def run_preview(
    latest: Callable[[], Processed | None],
    done: threading.Event,
    hud: Callable[[], HudInfo],
    state: Callable[[], str],
    until: float | None,
) -> None:
    """Show the latest processed frame until q, the window is closed, `done` is set
    (processing stopped), or the time.perf_counter() deadline `until`. Main thread only.

    The image changes at the processing rate; the window, banner and HUD refresh every
    REFRESH_MS, so LOST is visible while no frames arrive."""
    image = np.zeros((360, 640, 3), np.uint8)
    shown = None
    cv2.namedWindow(WINDOW)
    try:
        while not done.is_set():
            if until is not None and time.perf_counter() >= until:
                break
            current = latest()
            if current is not None and current is not shown:
                image, shown = draw_tracks(current.frame.image, current.tracks), current
            cv2.imshow(WINDOW, draw_hud(image, state(), hud()))
            if cv2.waitKey(REFRESH_MS) & 0xFF == ord("q"):
                break
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyAllWindows()
