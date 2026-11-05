"""The Studio's live stats tail frames.csv by its own header, so added columns do not break it."""

import time

from services.edge.session.folder import FrameTail
from services.edge.session.types import FrameRecord
from services.edge.session.writer import FileSessionWriter
from tests.edge.fakes import meta, sample_run_meta
from tests.edge.test_session import COUNTS


def test_recent_frames_survive_the_columns_added_in_0_11_0(tmp_path):
    w = FileSessionWriter(tmp_path)
    run = sample_run_meta()
    w.start(meta(), run)
    w.set_t0(time.perf_counter(), "2026-10-13T12:00:01Z")
    for seq in range(3):
        w.frame(FrameRecord(seq, 0.1 * seq, 0.1 * seq, 0.1 * seq + 0.05, 1, 1, 0, t_video=seq / 30))
    w.close("ended", COUNTS)
    rows = FrameTail(w.dir / "runs" / run.run_id).poll()
    assert [r["seq"] for r in rows] == ["0", "1", "2"]
    assert rows[0]["n_tracks"] == "1"
