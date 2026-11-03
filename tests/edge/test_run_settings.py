"""run_meta: run.json fields that are known at the start of a run."""

from types import SimpleNamespace

import pytest

from services.edge.capture.health import HealthConfig
from services.edge.capture.types import SourceInfo
from services.edge.run.meta import run_meta


def meta(requested_size, kind="camera", **kw):
    info = SourceInfo(kind, "ref", 1280, 720, 30.0, "builtin")
    return run_meta(requested_size, info, HealthConfig(), None, None, None, **kw)


@pytest.mark.parametrize("kind", ["file", "stream"])
def test_requested_size_is_recorded_for_cameras_only(kind):
    assert meta((640, 480), "camera").input["requested_width"] == 640
    assert meta((640, 480), "camera").input["requested_height"] == 480
    other = meta((640, 480), kind).input
    assert other["requested_width"] is None
    assert other["requested_height"] is None


def test_run_meta_carries_no_checks_of_its_own():
    # the calibration check comes from intake (D-057), not from run_meta
    assert meta(None).checks is None


def test_model_loaded_reaches_ready():
    loaded = {"t_wall": "2026-01-01T00:00:00Z", "t_pc": 1.5}

    assert meta(None, model_loaded=loaded).ready == {"model_loaded": loaded}


def test_replay_target_sets_mode_and_input_hash():
    target = SimpleNamespace(sha256="ab" * 32)

    run = meta(None, "file", replay=target)

    assert run.mode == "replay"
    assert run.input["sha256"] == "ab" * 32
    assert meta(None, "file").mode == "live"
