"""The camera's loopback HTTP preview, started for a pipeline (moved out of main.py, T11)."""

import time

from services.edge.camera_pipeline import CameraPipeline
from services.edge.capture.types import HealthEvent, utc_now


def start_http_preview(port: int, pipeline: CameraPipeline):
    """The camera's loopback preview server, started and fed by its processing thread."""
    from services.edge.ui.http_preview import HttpPreview

    preview = HttpPreview(
        port,
        pipeline.health_state,
        pipeline.hud,
        lambda error: pipeline.log_event(
            HealthEvent(
                "error", utc_now(), time.perf_counter(), f"preview encoding failed: {error!r}"
            )
        ),
        raw_snapshot=pipeline.raw_snapshot,
        calibration=pipeline.calibration.preview_document() if pipeline.calibration else None,
        on_first_preview=pipeline.mark_preview_ready,
    )
    pipeline.on_preview(preview.publish)
    preview.start()
    return preview
