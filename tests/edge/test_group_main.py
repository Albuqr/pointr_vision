"""A group's one process (R2a 04, D-056), run in-process on synthetic clips with detection off:
its per-camera output lines, the events it adds and its exit code. No camera, weights or network."""

import json
import signal

from services.edge import contract, group_main
from services.edge.camera_pipeline import CameraPipeline
from services.edge.capture.sources import FileSource
from services.edge.main import EXIT_INTERRUPTED, EXIT_OPEN_FAILED, StopRequest
from tests.edge.fakes import EvenFrameDetector, OneTrackPerDetection
from tests.edge.test_group_runner import camera_files


def camera(camera_id, source, out, *extra):
    return json.dumps(
        [f"--source={source}", "--link=file", f"--camera-id={camera_id}", "--group-id=g1",
         f"--out={out}", "--no-detect", "--no-record", *extra]
    )  # fmt: skip


def test_a_group_records_every_camera_and_tags_each_line(clips, tmp_path, capsys):
    out = tmp_path / "out"
    code = group_main.main(
        [
            camera("cam1", clips["moving"], out, "--preview"),
            camera("cam2", clips["frozen"], out, "--calibration-problem=file is corrupt"),
        ]
    )
    assert code == 0
    files = camera_files(out)
    assert {cid: s["status"] for cid, (s, *_) in files.items()} == {
        "cam1": "ended",
        "cam2": "ended",
    }
    [problem] = [e for e in files["cam2"][0]["events"] if e["kind"] == "error"]
    assert problem["detail"] == "calibration not used: file is corrupt"
    assert not [e for e in files["cam1"][0]["events"] if e["kind"] == "error"]
    lines = capsys.readouterr().out.splitlines()
    for cid in files:  # what the launcher reads for each camera
        assert any(line.startswith(f"[{cid}] session: ") for line in lines)
        assert any(
            line.startswith(f"[{cid}] t0_wall=") and "failed_reads=" in line for line in lines
        )
    assert "warning: no preview window in a group" in "\n".join(lines)
    for s, *_ in files.values():
        folder = out / f"{s['camera_id']}_{s['session_id']}"
        assert list(folder.glob("runs/*/report.json"))


def test_a_source_that_cannot_open_is_an_error_on_that_camera(clips, tmp_path, capsys):
    out = tmp_path / "out"
    code = group_main.main(
        [camera("cam1", clips["moving"], out), camera("cam2", tmp_path / "missing.mp4", out)]
    )
    assert code == EXIT_OPEN_FAILED
    assert "[cam2] error: source_open_failed: cannot open source" in capsys.readouterr().err
    assert not out.exists() or not any(out.iterdir())


def test_one_detector_size_for_the_group():
    assert group_main.group_det_size({None}) is None  # the model's own
    assert group_main.group_det_size({640}) == 640
    assert group_main.group_det_size({320, 640}) == 640
    assert group_main.group_det_size({None, 320}) == 320  # the only size asked for


def test_the_matcher_keeps_a_group_id_as_long_as_the_longest_tracker_lost_time():
    cams = [group_main.parse_args(["--source=x", f"--track-lost-secs={s}"]) for s in (1.0, 2.5)]
    assert group_main.group_matcher(cams).record_params()["lost_s"] == 2.5


def stop_on_first_call(monkeypatch, owner, name, after, ui):
    """Deliver a real SIGINT (as the stdin watcher does) on the first call of owner.name, after
    it ran when `after` is set; ui marks it Studio's stop. Returns the group's StopRequest."""
    request = StopRequest()
    if ui:
        request.source = "ui"
    monkeypatch.setattr(group_main, "StopRequest", lambda: request)
    original, calls = getattr(owner, name), []

    def wrapper(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1 and not after:
            signal.raise_signal(signal.SIGINT)
        result = original(*args, **kwargs)
        if len(calls) == 1 and after:
            signal.raise_signal(signal.SIGINT)
        return result

    monkeypatch.setattr(owner, name, wrapper)
    return request


def fake_detection(monkeypatch):
    monkeypatch.setattr(group_main, "resolve_device", lambda requested: ("cpu", None))
    monkeypatch.setattr(
        group_main, "load_perception", lambda args, device: (EvenFrameDetector(), None)
    )
    monkeypatch.setattr(group_main, "create_tracker", lambda args: OneTrackPerDetection())


def with_detection(argv):
    return [a.replace('"--no-detect", ', "") for a in argv]


def stop_during_session_setup(clips, tmp_path, monkeypatch, ui):
    fake_detection(monkeypatch)
    stop_on_first_call(monkeypatch, CameraPipeline, "open_session", after=True, ui=ui)
    out = tmp_path / "out"
    code = group_main.main(
        with_detection([camera("cam1", clips["moving"], out), camera("cam2", clips["frozen"], out)])
    )
    return code, camera_files(out)


def test_a_studio_stop_while_the_sessions_open_ends_every_session_stopped(
    clips, tmp_path, monkeypatch
):
    code, files = stop_during_session_setup(clips, tmp_path, monkeypatch, ui=True)
    assert code == 0
    assert set(files) == {"cam1", "cam2"}
    for session, *_ in files.values():
        assert session["status"] == "ended"
        [stopped] = [e for e in session["events"] if e["kind"] == "stopped"]
        assert stopped["detail"] == contract.UI_STOP_DETAIL
        assert not [e for e in session["events"] if e["kind"] == "error"]
        assert not any("did not start" in e["detail"] for e in session["events"])


def test_a_plain_stop_while_the_sessions_open_ends_every_session_interrupted(
    clips, tmp_path, monkeypatch
):
    code, files = stop_during_session_setup(clips, tmp_path, monkeypatch, ui=False)
    assert code == EXIT_INTERRUPTED
    assert set(files) == {"cam1", "cam2"}
    for session, *_ in files.values():
        assert session["status"] == "interrupted"
        [interrupted] = [e for e in session["events"] if e["kind"] == "interrupted"]
        assert interrupted["detail"] == "Ctrl+C"
        assert not any("did not start" in e["detail"] for e in session["events"])


def test_a_studio_stop_while_the_sources_open_ends_with_no_session(
    clips, tmp_path, monkeypatch, capsys
):
    stop_on_first_call(monkeypatch, FileSource, "open", after=False, ui=True)
    out = tmp_path / "out"
    code = group_main.main(
        [camera("cam1", clips["moving"], out), camera("cam2", clips["frozen"], out)]
    )
    assert code == 0
    assert not out.exists() or not any(out.iterdir())
    assert f"stopped: {contract.UI_STOP_DETAIL}" in capsys.readouterr().out


def test_a_plain_stop_while_the_sources_open_ends_with_no_session(
    clips, tmp_path, monkeypatch, capsys
):
    stop_on_first_call(monkeypatch, FileSource, "open", after=False, ui=False)
    out = tmp_path / "out"
    code = group_main.main(
        [camera("cam1", clips["moving"], out), camera("cam2", clips["frozen"], out)]
    )
    assert code == EXIT_INTERRUPTED
    assert not out.exists() or not any(out.iterdir())
    assert "interrupted: Ctrl+C" in capsys.readouterr().out
