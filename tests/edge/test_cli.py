"""A5: invalid source ref -> clear message, non-zero exit, no traceback. CLI happy path."""

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from services.edge import main as cli
from services.edge.main import EXIT_OPEN_FAILED
from services.edge.ui.preview import BANNERS, draw_hud

ROOT = Path(__file__).resolve().parents[2]


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "services.edge.main", *args],
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
def test_bad_ref_exits_cleanly(tmp_path, name, reason):
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "corrupt.mp4").write_bytes(b"this is not a video")
    ref = name if name == "not-a-source" else str(tmp_path / name)
    result = run_cli("--source", ref)
    assert result.returncode == EXIT_OPEN_FAILED != 0
    assert "Traceback" not in result.stdout + result.stderr
    assert "source_open_failed" in result.stdout
    assert reason in result.stdout
    assert f"error: cannot open source {ref!r}: " in result.stderr
    assert reason in result.stderr


def test_file_runs_to_end(clips):
    result = run_cli("--source", str(clips["moving"]), "--link", "file")
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "link='file'" in result.stdout
    assert "captured=30 " in result.stdout
    assert "failed_reads=0 " in result.stdout
    assert "events={}" in result.stdout


@pytest.mark.parametrize("state", list(BANNERS))
def test_draw_hud_every_state(state):
    image = np.full((360, 640, 3), 90, np.uint8)
    out = draw_hud(image, state, 29.97, 3)
    assert out.shape == image.shape
    assert (image == 90).all(), "input image modified"
    assert (out[:34] != 90).any(), "no banner drawn"
    assert BANNERS[state][0].startswith(state)


def test_banner_colours_differ():
    image = np.full((360, 640, 3), 90, np.uint8)
    colours = {tuple(draw_hud(image, s, None, 0)[5, 5]) for s in BANNERS}
    assert len(colours) == len(BANNERS)


def test_cv2_error_on_open_exits_cleanly(monkeypatch, capsys):
    class Broken:
        def open(self):
            raise cv2.error("backend exploded")

    printed = []
    monkeypatch.setattr(cli, "open_source", lambda ref, api: Broken())
    monkeypatch.setattr(cli, "print_event", lambda ev, t0: printed.append(ev))
    assert cli.main(["--source", "0"]) == EXIT_OPEN_FAILED
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
