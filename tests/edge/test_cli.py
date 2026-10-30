"""Phase 01 A5: invalid source ref -> clear message, non-zero exit, no traceback. CLI happy
path, HUD, and the phase 02 flags. Subprocess runs use --no-detect: no model, no weights."""

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from services.edge import main as cli
from services.edge.main import EXIT_CAPTURE_ERROR, EXIT_OPEN_FAILED
from services.edge.ui.preview import BANNERS, HUD_STRIP, TRACK_COLOUR, HudInfo, draw_hud

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def out_dir(tmp_path, monkeypatch) -> Path:
    """Session data goes to a temp folder, never to ./sessions."""
    out = tmp_path / "sessions"
    real = cli.parse_args
    monkeypatch.setattr(cli, "parse_args", lambda argv: real([*argv, "--out", str(out)]))
    return out


def run_cli(out: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "services.edge.main", "--no-detect", "--out", str(out), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    "name,reason",
    [
        ("missing.mp4", "file not found"),
        ("notes.txt", "unsupported file type"),
        ("corrupt.mp4", "did not open"),
        ("not-a-source", "not a camera index"),
    ],
)
def test_bad_ref_exits_cleanly(tmp_path, out_dir, name, reason):
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "corrupt.mp4").write_bytes(b"this is not a video")
    ref = name if name == "not-a-source" else str(tmp_path / name)
    result = run_cli(out_dir, "--source", ref)
    assert result.returncode == EXIT_OPEN_FAILED != 0
    assert "Traceback" not in result.stdout + result.stderr
    assert "source_open_failed" in result.stdout
    assert reason in result.stdout
    assert f"error: cannot open source {ref!r}: " in result.stderr
    assert reason in result.stderr
    assert not out_dir.exists()  # no session before the source opens (D-020)


def test_file_runs_to_end(clips, out_dir):
    result = run_cli(out_dir, "--source", str(clips["moving"]), "--link", "file")
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "link='file'" in result.stdout
    assert "captured=30 " in result.stdout
    assert "failed_reads=0 " in result.stdout
    assert "processed=" in result.stdout
    assert "events={}" in result.stdout
    assert "perception:" not in result.stdout  # --no-detect: the model was never loaded
    assert "requested 1280x720" not in result.stdout  # a file delivers its own size


def test_benchmark_prints_the_baseline_block(clips, out_dir):
    result = run_cli(
        out_dir, "--source", str(clips["moving"]), "--link", "file", "--benchmark", "60"
    )
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("benchmark:")]
    assert len(lines) == 3, result.stdout
    assert "frames 640x360" in lines[0]
    assert "det-size off" in lines[0]
    assert "preview off" in lines[0]
    assert "captured 30, processed " in lines[1]
    assert "app delay ms p50 " in lines[2] and "p95 " in lines[2] and "max " in lines[2]
    assert "unprocessed 0" in lines[1]


def test_benchmark_stops_after_its_seconds(clips, out_dir):
    """The clip plays for 2 s in real time; --benchmark 0.3 must end the run first."""
    result = run_cli(
        out_dir, "--source", str(clips["moving"]), "--link", "file", "--benchmark", "0.3"
    )
    assert result.returncode == 0, result.stderr
    captured = int(result.stdout.split("captured=")[1].split()[0])
    assert 0 < captured < 30
    assert "(0.3 s requested)" in result.stdout


HUD = HudInfo(capture_fps=29.97, dropped=3, proc_fps=4.2, app_delay_ms=180.0, people=2, tracks=1)


@pytest.mark.parametrize("state", list(BANNERS))
def test_draw_hud_every_state(state):
    image = np.full((360, 640, 3), 90, np.uint8)
    out = draw_hud(image, state, HUD)
    assert out.shape == image.shape
    assert (image == 90).all(), "input image modified"
    assert (out[:34] != 90).any(), "no banner drawn"
    assert BANNERS[state][0].startswith(state)


def test_banner_colours_differ():
    image = np.full((360, 640, 3), 90, np.uint8)
    off = HudInfo(None, 0, None, None, None, None)  # detection off, nothing measured yet
    colours = {tuple(draw_hud(image, s, off)[5, 5]) for s in BANNERS}
    assert len(colours) == len(BANNERS)


def test_hud_status_is_one_text_pass_on_a_dark_strip():
    """Phase 01 A6: the status text was drawn twice (outline + text). Now: white on black."""
    out = draw_hud(np.full((360, 640, 3), 90, np.uint8), "OK", HUD)
    strip = out[-HUD_STRIP:].astype(int)
    assert (strip[..., 0] == strip[..., 1]).all() and (strip[..., 1] == strip[..., 2]).all()
    assert strip.max() > 200, "no white text"
    assert (strip[:, -10:] == 0).all(), "text runs off a 640-wide frame"
    assert (out[: -HUD_STRIP - 1, 300] == 90).any(), "strip taller than expected"


def test_draw_tracks_labels_each_track():
    from services.edge.perception.types import TrackObs
    from services.edge.ui.preview import draw_tracks

    image = np.full((360, 640, 3), 90, np.uint8)
    out = draw_tracks(image, [TrackObs(7, (100.0, 100.0, 200.0, 300.0), 0.9, None)])
    assert (image == 90).all(), "input image modified"
    assert (out[100:300, 100] != 90).any(), "no box edge drawn"
    label = out[80:97, 100:140]  # the "#7" label sits just above the box
    assert (label == TRACK_COLOUR).all(axis=-1).any(), "no #id label drawn"
    other = draw_tracks(image, [TrackObs(1, (100.0, 100.0, 200.0, 300.0), 0.9, None)])
    assert (other[80:97, 100:140] != label).any(), "label does not show the track ID"
    assert (other[100:300] == out[100:300]).all()  # same box: only the label differs


def test_model_load_failure_is_an_error_event(monkeypatch):
    class NeverOpened:
        def open(self):
            raise AssertionError("the source must not open before the model loads")

    def no_network(args, device):
        raise RuntimeError("weights download failed")

    printed = []
    monkeypatch.setattr(cli, "open_source", lambda ref, size: NeverOpened())
    monkeypatch.setattr(cli, "load_perception", no_network)
    monkeypatch.setattr(cli, "print_event", lambda ev, t0: printed.append(ev))
    assert cli.main(["--source", "0"]) == EXIT_CAPTURE_ERROR
    [ev] = printed
    assert ev.kind == "error"
    assert ev.t_mono is None  # before any run's t0 (D-014)
    assert "model load failed" in ev.detail and "weights download failed" in ev.detail


def fake_gpu(monkeypatch, available: bool) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: available)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda index: "Fake RTX 9000")


@pytest.mark.parametrize(
    "requested,available,expected",
    [
        ("auto", True, ("cuda:0", "Fake RTX 9000")),
        ("auto", False, ("cpu", None)),
        ("cpu", True, ("cpu", None)),
        ("cpu", False, ("cpu", None)),
        ("cuda", True, ("cuda:0", "Fake RTX 9000")),
    ],
)
def test_resolve_device(monkeypatch, requested, available, expected):
    fake_gpu(monkeypatch, available)
    assert cli.resolve_device(requested) == expected


def test_forced_cuda_without_a_gpu_exits_with_a_clear_error(monkeypatch, capsys):
    fake_gpu(monkeypatch, False)
    with pytest.raises(RuntimeError, match="--device cuda but torch .* cannot use a CUDA GPU"):
        cli.resolve_device("cuda")

    def never(*args):
        raise AssertionError("must stop before the model load")

    monkeypatch.setattr(cli, "load_perception", never)
    assert cli.main(["--source", "0", "--device", "cuda"]) == EXIT_CAPTURE_ERROR != 0
    err = capsys.readouterr().err
    assert "error: --device cuda" in err and "Traceback" not in err


def test_broken_torch_install_exits_cleanly(monkeypatch, capsys):
    def broken(requested):
        raise OSError("[WinError 126] DLL load failed")

    monkeypatch.setattr(cli, "resolve_device", broken)
    assert cli.main(["--source", "0"]) == EXIT_CAPTURE_ERROR
    err = capsys.readouterr().err
    assert "error: device check failed: " in err and "Traceback" not in err


def test_no_detect_ignores_an_unusable_device(monkeypatch, clips, capsys):
    fake_gpu(monkeypatch, False)
    code = cli.main(["--source", str(clips["moving"]), "--device", "cuda", "--no-detect"])
    assert code == 0
    assert "device:" not in capsys.readouterr().out


def test_cli_prints_the_size_the_camera_delivers(monkeypatch, capsys):
    class Webcam:
        """Accepts a 1280x720 request but delivers 640x480; no frames."""

        def __init__(self, index, api):
            pass

        def isOpened(self):  # noqa: N802 - cv2 name
            return True

        def set(self, prop, value):
            return True

        def get(self, prop):
            sizes = {cv2.CAP_PROP_FRAME_WIDTH: 640.0, cv2.CAP_PROP_FRAME_HEIGHT: 480.0}
            return sizes.get(prop, 0.0)

        def read(self):
            return False, None

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", Webcam)
    cli.main(["--source", "1", "--no-detect", "--benchmark", "0.2"])
    assert "requested 1280x720, camera delivers 640x480" in capsys.readouterr().out


def test_cv2_error_on_open_exits_cleanly(monkeypatch, capsys):
    class Broken:
        def open(self):
            raise cv2.error("backend exploded")

    printed = []
    monkeypatch.setattr(cli, "open_source", lambda ref, size: Broken())
    monkeypatch.setattr(cli, "print_event", lambda ev, t0: printed.append(ev))
    assert cli.main(["--source", "0", "--no-detect"]) == EXIT_OPEN_FAILED
    [ev] = printed
    assert ev.kind == "source_open_failed"
    assert ev.t_mono is None  # no run, so no t0 (D-014)
    assert "backend exploded" in ev.detail
    assert "backend exploded" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--lost-reads", "--lost-secs", "--frozen-secs", "--dark-level"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_thresholds_must_be_positive(flag, value, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["--source", "0", flag, value])
    assert exc.value.code == 2
    assert "must be > 0" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args,message",
    [
        (["--det-size", "100"], "multiple of 32"),
        (["--det-size", "0"], "multiple of 32"),
        (["--threshold", "0"], "must be in (0, 1]"),
        (["--threshold", "1.5"], "must be in (0, 1]"),
        (["--width", "0"], "must be > 0"),
        (["--benchmark", "-5"], "must be > 0"),
        (["--benchmark", "nan"], "must be > 0"),
        (["--benchmark", "inf"], "must be > 0"),
        (["--threshold", "nan"], "must be in (0, 1]"),
        (["--camera-api", "dshow"], "unrecognized arguments: --camera-api"),
    ],
)
def test_bad_phase02_flags_are_rejected(args, message, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["--source", "0", *args])
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_defaults():
    args = cli.parse_args(["--source", "0"])
    assert (args.width, args.height) == (1280, 720)
    assert (args.threshold, args.device, args.det_size) == (0.5, "auto", None)
    assert (args.benchmark, args.no_detect) == (None, False)
    assert (args.track_lost_secs, args.track_activation, args.track_min_frames) == (1.0, 0.7, 2)


def test_valid_phase02_flags_are_accepted():
    args = cli.parse_args(
        ["--source", "0", "--det-size", "320", "--threshold", "1", "--benchmark", "0.5"]
    )
    assert (args.det_size, args.threshold, args.benchmark) == (320, 1.0, 0.5)


def test_tracker_flags_are_accepted():
    args = cli.parse_args(
        [
            "--source",
            "0",
            "--track-lost-secs",
            "4",
            "--track-activation",
            "0.55",
            "--track-min-frames",
            "3",
        ]
    )
    assert (args.track_lost_secs, args.track_activation, args.track_min_frames) == (4.0, 0.55, 3)
