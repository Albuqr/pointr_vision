"""A group's one process (R2a 04, D-056), run in-process on synthetic clips with detection off:
its per-camera output lines, the events it adds and its exit code. No camera, weights or network."""

import json

from services.edge import group_main
from services.edge.main import EXIT_OPEN_FAILED
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
    assert "[cam2] error: cannot open source" in capsys.readouterr().out
    assert not out.exists() or not any(out.iterdir())


def test_one_detector_size_for_the_group():
    assert group_main.group_det_size({None}) is None  # the model's own
    assert group_main.group_det_size({640}) == 640
    assert group_main.group_det_size({320, 640}) == 640
    assert group_main.group_det_size({None, 320}) == 320  # the only size asked for
