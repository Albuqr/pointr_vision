"""OpenCV preview window: live image, source state banner, capture FPS, drops. q closes."""

import queue
from collections.abc import Callable

import cv2
import numpy as np

from services.edge.capture.capture import Capture

WINDOW = "Pointr capture (q to quit)"
FONT = cv2.FONT_HERSHEY_SIMPLEX
# state -> (banner text, BGR colour); the text tells the user what to do
BANNERS = {
    "OK": ("OK", (60, 180, 60)),
    "LOST": ("LOST: no frames, check camera connection", (40, 40, 220)),
    "FROZEN": ("FROZEN: image frozen, check camera connection", (0, 140, 255)),
    "DARK": ("DARK: image too dark, check lens and lighting", (0, 220, 220)),
}


def draw_hud(image: np.ndarray, state: str, fps: float | None, dropped: int) -> np.ndarray:
    """A copy of image with the banner and counters drawn on it."""
    out = image.copy()
    text, colour = BANNERS[state]
    cv2.rectangle(out, (0, 0), (out.shape[1], 34), colour, thickness=-1)
    cv2.putText(out, text, (10, 24), FONT, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
    rate = f"{fps:.1f}" if fps else "--"
    status = f"capture {rate} fps   dropped {dropped}"
    cv2.putText(out, status, (10, out.shape[0] - 12), FONT, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(out, status, (10, out.shape[0] - 12), FONT, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def run_preview(capture: Capture, state: Callable[[], str]) -> None:
    """Show frames until q, the window is closed, or capture stops. Main thread only.

    The last image stays on screen while no frames arrive, so LOST is still visible."""
    image = np.zeros((360, 640, 3), np.uint8)
    cv2.namedWindow(WINDOW)
    try:
        while not (capture.done.is_set() and capture.proc_queue.empty()):
            try:
                image = capture.proc_queue.get(timeout=0.03).image
            except queue.Empty:
                pass
            cv2.imshow(WINDOW, draw_hud(image, state(), capture.fps, capture.dropped))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyAllWindows()
