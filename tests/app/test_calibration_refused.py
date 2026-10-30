"""B13: a calibration refused at fit time offers retry or start uncalibrated; the uncalibrated
start is recorded as a failed calibration check (FR-003, D-057)."""

from services.edge import group_main
from services.edge.launcher import Options, child_command
from services.edge.launcher_impl import Camera
from tests.edge.fakes import EvenFrameDetector
from tests.edge.test_group_main import camera
from tests.edge.test_group_runner import camera_files
from tests.edge.test_session import run_main, session_files
from tests.edge.test_session import validate as validate_file

REASON = "mean check error 0.900 m exceeds 0.500 m"


def test_the_launcher_passes_the_failed_calibration_to_the_recorder():
    command = child_command(
        Camera("cam1", "0", "usb", calibration_failed=REASON), Options("o", "g")
    )
    assert f"--calibration-failed={REASON}" in command
    plain = child_command(Camera("cam1", "0", "usb"), Options("o", "g"))
    assert not any(part.startswith("--calibration-failed") for part in plain)


def test_the_recorder_writes_a_failed_calibration_check_and_event(monkeypatch, tmp_path, clips):
    out = tmp_path / "sessions"
    code = run_main(
        monkeypatch, out, "--source", str(clips["moving"]), "--link", "file",
        "--camera-id", "cam1", f"--calibration-failed={REASON}",
        detector=EvenFrameDetector(),
    )  # fmt: skip
    assert code == 0
    session, run, _, tracks = session_files(out)
    [check] = run["checks"]
    assert (check["check"], check["result"], check["detail"]) == ("calibration", "failed", REASON)
    [event] = [e for e in session["events"] if e["kind"] == "startup_check_failed"]
    assert event["detail"] == f"calibration: {REASON}"
    validate_file("run", run)
    validate_file("session", session)
    assert session["calibration"] is None and run["calibration"] is None
    assert tracks and all(
        t["x_m"] == t["y_m"] == t["in_court"] == "" and t["x1"] != "" for t in tracks
    )


def test_a_group_starts_the_refused_camera_uncalibrated_and_leaves_the_other_alone(clips, tmp_path):
    out = tmp_path / "out"
    code = group_main.main(
        [
            camera("cam1", clips["moving"], out),
            camera("cam2", clips["frozen"], out, f"--calibration-failed={REASON}"),
        ]
    )
    assert code == 0
    files = camera_files(out)
    assert files["cam1"][1]["checks"] is None
    assert not [e for e in files["cam1"][0]["events"] if e["kind"] == "startup_check_failed"]
    [check] = files["cam2"][1]["checks"]
    assert (check["check"], check["result"], check["detail"]) == ("calibration", "failed", REASON)
    [event] = [e for e in files["cam2"][0]["events"] if e["kind"] == "startup_check_failed"]
    assert event["detail"] == f"calibration: {REASON}"
    for session, run, *_ in files.values():
        validate_file("session", session)
        validate_file("run", run)
