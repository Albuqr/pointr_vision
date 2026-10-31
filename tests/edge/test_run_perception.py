"""T9 (#71): device and model load, written once (services/edge/run/perception.py). The entry
points' reporting on every path is pinned end to end in test_run_characterisation.py."""

import argparse

from services.edge.run.perception import Perception, start_perception

ARGS = argparse.Namespace(no_detect=False, device="auto")


def start(args=ARGS, *, resolve=lambda requested: ("cpu", None), load=lambda a, d: ("det", "trk")):
    events = []
    result = start_perception(
        args,
        resolve_device=resolve,
        load_perception=load,
        emit=lambda ev, t0: events.append((ev, t0)),
    )
    return result, events


def test_a_loaded_model_is_returned_with_its_load_time(capsys):
    result, events = start(resolve=lambda requested: ("cuda:0", "Fake GPU"))
    assert (result.detector, result.tracker, result.gpu) == ("det", "trk", "Fake GPU")
    assert set(result.model_loaded) == {"t_wall", "t_pc"}
    assert events == []
    assert "device: cuda:0 (Fake GPU)" in capsys.readouterr().out


def test_no_detect_loads_nothing():
    def never(*args):
        raise AssertionError("no-detect must not touch the device or the model")

    result, _ = start(argparse.Namespace(no_detect=True), resolve=never, load=never)
    assert result == Perception()


def test_a_model_load_failure_is_an_event_and_an_error_line(capsys):
    def no_network(args, device):
        raise RuntimeError("weights download failed")

    result, [(event, t0)] = start(load=no_network)
    assert result is None
    assert (event.kind, event.t_mono, t0) == ("error", None, None)  # before any run (D-014)
    assert "model load failed" in event.detail and "weights download failed" in event.detail
    err = capsys.readouterr().err
    assert "error: model_load_failed: model load failed" in err and "weights download failed" in err


def test_a_device_failure_is_an_error_line_only(capsys):
    def broken(requested):
        raise OSError("DLL load failed")

    def forced(requested):
        raise RuntimeError("--device cuda but no GPU")

    result, events = start(resolve=broken)
    assert result is None and events == []
    assert (
        "error: model_load_failed: device check failed: DLL load failed" in capsys.readouterr().err
    )
    assert start(resolve=forced)[0] is None
    assert "error: config_conflict: --device cuda but no GPU" in capsys.readouterr().err
