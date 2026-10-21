"""PHASE_02 A5: the real RF-DETR Nano counts the people in still images.

Marked slow: it loads torch, downloads the model weights once (~366 MB, rfdetr's cache) and
the two images once (tests/fixtures/downloads/, gitignored: photos of real people are never
committed, CLAUDE.md rule 9). Sources and licences: tests/fixtures/README.md.

    pytest -m slow
"""

import hashlib
import http.client
import urllib.parse
from pathlib import Path

import cv2
import pytest

from services.edge.capture.types import Frame
from services.edge.perception.detector import COCO_PERSON_ID, RFDETRDetector

DOWNLOADS = Path(__file__).resolve().parents[1] / "fixtures" / "downloads"
COMMONS = "https://upload.wikimedia.org/wikipedia/commons/"
# name -> (original file URL, Commons SHA-1 of the file, people in it)
IMAGES = {
    "apollo11_crew.jpg": (
        COMMONS + "3/3d/Apollo_11_Crew.jpg",
        "869cb2c816bdcfc960ef7cb89c2e4b2c6c5d827c",
        3,
    ),
    "breese_gym.jpg": (
        COMMONS + "8/8b/Breese_Gymnasium%2C_Western_Carolina_University%2C_Cullowhee%2C_NC_"
        "%2846640519431%29.jpg",
        "87f941d0c060a7ac057280e6bbd62ae7e7cb6a03",
        0,
    ),
}
# Tolerance: 0. Both images are easy cases (three large, unoccluded people; no people at
# all), so any miscount at the default threshold is a failure worth looking at.
TOLERANCE = 0
THRESHOLD = 0.5  # the CLI default


def fetch(name: str) -> Path:
    url, sha1, _ = IMAGES[name]
    path = DOWNLOADS / name
    if not path.exists():
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        parts = urllib.parse.urlsplit(url)
        # http.client over TLS only: no file:/ftp: schemes. Commons serves these files directly.
        conn = http.client.HTTPSConnection(parts.netloc, timeout=60)
        conn.request("GET", parts.path, headers={"User-Agent": "pointr-test-fixtures/0.1"})
        response = conn.getresponse()
        assert response.status == 200, f"{url}: HTTP {response.status}"
        path.write_bytes(response.read())
        conn.close()
    # Commons publishes SHA-1 digests; this only checks the download, nothing depends on it.
    digest = hashlib.sha1(path.read_bytes(), usedforsecurity=False).hexdigest()
    assert digest == sha1, f"{name}: sha1 {digest}, expected {sha1}; delete it and re-run"
    return path


@pytest.fixture(scope="module")
def detector() -> RFDETRDetector:
    return RFDETRDetector.load(THRESHOLD, det_size=None, device="cpu")


@pytest.mark.slow
def test_model_config_as_verified(detector):
    """D-015: the default det-size is the Nano resolution, and COCO id 1 is person."""
    from rfdetr.assets.coco_classes import COCO_CLASSES

    assert detector.det_size == 384
    assert COCO_CLASSES[COCO_PERSON_ID] == "person"
    assert detector.device == "cpu"


@pytest.mark.slow
@pytest.mark.parametrize("name", list(IMAGES))
def test_counts_people_in_a_still_image(detector, name):
    image = cv2.imread(str(fetch(name)))  # BGR, as frames from capture
    assert image is not None
    dets = detector.detect(Frame(0, 0.0, "2026-10-08T12:00:00Z", image, name))
    expected = IMAGES[name][2]
    assert abs(len(dets.xyxy) - expected) <= TOLERANCE, (name, dets.confidence.tolist())
    h, w = image.shape[:2]
    if len(dets.xyxy):  # boxes are in source-image pixels, not det-size pixels
        assert dets.xyxy[:, 2].max() <= w + 1 and dets.xyxy[:, 3].max() <= h + 1
        assert dets.xyxy[:, 2].max() > 384  # the image is 4200 px wide
