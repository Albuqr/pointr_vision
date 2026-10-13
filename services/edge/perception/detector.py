"""RF-DETR Nano person detector (PHASE_02, D-015).

rfdetr is imported only by RFDETRDetector.load(), so code that never loads the model (tests,
--no-detect) does not import torch. Library objects never leave this module.
"""

import logging
import warnings

import numpy as np

from services.edge.capture.types import Frame
from services.edge.perception.types import Detections

COCO_PERSON_ID = 1  # pretrained COCO checkpoints return raw COCO category IDs (D-015)
# Nano patch_size 16 * num_windows 2 (D-015). Lets the CLI reject a bad --det-size before the
# slow model load; load() checks it again against the real config.
DET_SIZE_MULTIPLE = 32

# Known start-up noise (BACKLOG): matched by message, so any other warning still shows.
_NOISE = (
    "not loading DINOv2 backbone weights",  # rfdetr: expected for the COCO checkpoint
    "Model is not optimized for inference",  # rfdetr: speed hint, tracked in BACKLOG
)


class _DropNoise(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not any(text in record.getMessage() for text in _NOISE)


class RFDETRDetector:
    """Detector over any model with rfdetr's predict(rgb, threshold=, shape=) signature."""

    def __init__(self, model, threshold: float, det_size: int):
        self.model = model
        self.threshold = threshold
        self.det_size = det_size  # square side the image is resized to before inference

    @classmethod
    def load(cls, threshold: float, det_size: int | None, device: str) -> "RFDETRDetector":
        """Build RF-DETR Nano with the COCO weights (downloaded once). device: cpu or cuda:N.

        det_size None means the model's own resolution. Raises ValueError when det_size is
        not a multiple of the model's patch_size * num_windows (32 for Nano)."""
        with warnings.catch_warnings():  # torch.jit.script deprecation, raised inside rfdetr
            warnings.filterwarnings("ignore", message=".*torch.jit.script.*deprecated")
            warnings.filterwarnings("ignore", message=".*requires the 'plus' extras")
            from rfdetr import RFDETRNano

            logging.getLogger("rf-detr").addFilter(_DropNoise())
            model = RFDETRNano(device=device)
        cfg = model.model_config
        block = cfg.patch_size * cfg.num_windows
        if block != DET_SIZE_MULTIPLE:
            raise ValueError(f"model block {block} != DET_SIZE_MULTIPLE {DET_SIZE_MULTIPLE}")
        size = det_size or cfg.resolution
        if size % block:
            raise ValueError(f"det-size must be a multiple of {block}, got {size}")
        return cls(model, threshold, size)

    @property
    def device(self) -> str:
        return str(self.model.model.device)

    def detect(self, frame: Frame) -> Detections:
        rgb = frame.image[:, :, ::-1]  # frames are BGR; rfdetr expects RGB
        out = self.model.predict(
            rgb,
            threshold=self.threshold,
            shape=(self.det_size, self.det_size),
            include_source_image=False,
        )
        conf = np.asarray(out.confidence, dtype=np.float32).reshape(-1)
        class_id = np.asarray(out.class_id, dtype=np.int64).reshape(-1)
        keep = (class_id == COCO_PERSON_ID) & (conf > self.threshold)  # "above", as rfdetr
        return Detections(
            xyxy=np.asarray(out.xyxy, dtype=np.float32).reshape(-1, 4)[keep],
            confidence=conf[keep],
            class_id=class_id[keep],
        )
