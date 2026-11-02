"""RunSettings and run_meta: run.json fields that come from the command line."""

from types import SimpleNamespace

import pytest

from services.edge.capture.health import HealthConfig
from services.edge.capture.sources import DEFAULT_CAPTURE_SIZE
from services.edge.capture.types import SourceInfo
from services.edge.run.args import parse_args
from services.edge.run.meta import (
    RunSettings,
    calibration_failed_event,
    failed_calibration_checks,
    run_meta,
)


def meta(settings, kind="camera", **kw):
    info = SourceInfo(kind, "ref", 1280, 720, 30.0, "builtin")
    return run_meta(settings, info, HealthConfig(), None, None, None, **kw)


def test_settings_from_args():
    args = parse_args(
        ["--source", "0", "--width", "640", "--height", "480", "--calibration-failed", "too few"]
    )

    assert RunSettings.from_args(args) == RunSettings((640, 480), "too few")


def test_settings_from_args_without_flags_use_the_defaults():
    settings = RunSettings.from_args(parse_args(["--source", "0"]))

    assert settings == RunSettings(DEFAULT_CAPTURE_SIZE, None)


@pytest.mark.parametrize("kind", ["file", "stream"])
def test_requested_size_is_recorded_for_cameras_only(kind):
    settings = RunSettings((640, 480), None)

    assert meta(settings, "camera").input["requested_width"] == 640
    assert meta(settings, "camera").input["requested_height"] == 480
    other = meta(settings, kind).input
    assert other["requested_width"] is None
    assert other["requested_height"] is None


def test_refusal_gives_a_check_and_an_event_only_when_present():
    run = meta(RunSettings(None, "points too few"))
    assert run.checks[0]["check"] == "calibration"
    assert run.checks[0]["detail"] == "points too few"
    assert calibration_failed_event("points too few").detail == "calibration: points too few"

    assert meta(RunSettings(None, None)).checks is None
    assert failed_calibration_checks(None) is None
    assert calibration_failed_event(None) is None


def test_model_loaded_reaches_ready():
    loaded = {"t_wall": "2026-01-01T00:00:00Z", "t_pc": 1.5}

    assert meta(RunSettings(None, None), model_loaded=loaded).ready == {"model_loaded": loaded}


def test_replay_target_sets_mode_and_input_hash():
    target = SimpleNamespace(sha256="ab" * 32)

    run = meta(RunSettings(None, None), "file", replay=target)

    assert run.mode == "replay"
    assert run.input["sha256"] == "ab" * 32
    assert meta(RunSettings(None, None), "file").mode == "live"
