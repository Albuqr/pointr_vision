"""v0 multi-camera (D-022): the launcher with fake child processes (no camera, no weights), the
real child's stop-on-stdin path, and the device_id race."""

import _thread
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_cameras as rc
from services.edge import main as cli
from services.edge.capture.capture import Capture
from services.edge.run.stop import EXIT_INTERRUPTED
from services.edge.session.writer import mask_credentials

ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).with_name("fake_camera.py")
GROUP = str(uuid.uuid4())


def fake_command(modes: dict[str, str]):
    """child_command for the launcher that starts fake_camera.py in the mode of each camera."""

    def command(cam: rc.Camera, opts: rc.Options) -> list[str]:
        return [sys.executable, "-u", str(FAKE), modes[cam.camera_id], cam.camera_id, opts.out]

    return command


def launcher(tmp_path: Path, modes: dict[str, str], **kw) -> rc.Launcher:
    """One fake process per camera: the process mechanics (start, stop, kill) are the same for a
    group's one process, which the real end-to-end tests below cover."""
    cams = [rc.Camera(cid, f"src-{cid}", "wifi") for cid in modes]
    opts = rc.Options(str(tmp_path), GROUP)
    return rc.Launcher(cams, opts, command=fake_command(modes), group_command=None, **kw)


def run_then_ctrl_c(lau: rc.Launcher, ready, presses: int = 1) -> int:
    """lau.run() in the main thread; once `ready()` is true, press Ctrl+C `presses` times (the
    same KeyboardInterrupt the terminal's Ctrl+C causes) while the launcher is still running."""
    done = threading.Event()

    def press():
        deadline = time.monotonic() + 20
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        for _ in range(presses):
            if done.is_set():
                return
            _thread.interrupt_main()
            time.sleep(0.03)

    t = threading.Thread(target=press)
    t.start()
    try:
        return lau.run()
    finally:
        done.set()
        t.join()


def all_ticking(out: Path, cams: list[str]):
    return lambda: all((out / f"session_{c}").exists() for c in cams)


def alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


def status_of(out: Path, camera_id: str) -> str:
    [folder] = out.glob(f"{camera_id}_*")
    return json.loads((folder / "session.json").read_text())["status"]


# -- config ----------------------------------------------------------------------------------


def cam(camera_id, source, link="wifi", **kw):
    return {"camera_id": camera_id, "source": source, "link": link, **kw}


@pytest.mark.parametrize(
    "a,b",
    [
        ("0", 0),
        (" 0 ", "0"),
        ("http://10.10.8.158:4747/video", "http://10.10.8.158:4747/mjpegfeed"),
        ("http://10.10.8.158:4747/video", "HTTP://10.10.8.158:4747/video?x=1"),
        ("http://10.10.8.158/video", "http://10.10.8.158:80/video"),
        ("http://u:p@10.10.8.158:4747/video", "http://10.10.8.158:4747/video"),
    ],
)
def test_two_entries_with_the_same_source_are_refused(a, b):
    """One viewer per phone: the same host and port is the same phone, whatever the path."""
    with pytest.raises(rc.ConfigError, match="same source"):
        rc.parse_config([cam("cam1", a), cam("cam2", b)])


def test_different_sources_are_accepted():
    cams = rc.parse_config(
        [
            cam("cam1", "http://10.10.8.158:4747/video"),
            cam("cam2", "http://10.10.8.159:4747/video"),  # another phone
            cam("cam3", "http://10.10.8.158:8080/video"),  # same host, another port
            cam("laptop", 0, "builtin", det_size=320, preview=True),
            cam("cam4", "1", "usb"),
        ]
    )
    assert [c.camera_id for c in cams] == ["cam1", "cam2", "cam3", "laptop", "cam4"]
    assert cams[3] == rc.Camera("laptop", "0", "builtin", 320, True)


def test_duplicate_source_error_masks_query_credentials():
    source = "http://phone:secret@10.0.0.5:4747/video?token=token-secret"
    with pytest.raises(rc.ConfigError) as raised:
        rc.parse_config([cam("cam1", source), cam("cam2", source)])
    assert "secret" not in str(raised.value)
    assert "token-secret" not in str(raised.value)
    assert "token=***" in str(raised.value)


@pytest.mark.parametrize(
    "entries,message",
    [
        ([], "non-empty"),
        ({"camera_id": "a"}, "non-empty"),
        ([cam("cam1", "0"), cam("cam1", "1")], "used twice"),
        ([cam("../evil", "0")], "camera_id must match"),
        ([cam("a b", "0")], "camera_id must match"),
        ([cam("x" * 33, "0")], "camera_id must match"),
        ([{"camera_id": "a", "source": "0"}], "missing 'link'"),
        ([cam("a", "0", "bluetooth")], "link must be"),
        ([cam("a", "")], "source must be"),
        ([cam("a", "0", det_size=100)], "allowed size"),
        ([cam("a", "0", det_size=True)], "allowed size"),
        ([cam("a", "0", preview="yes")], "preview must be"),
        ([cam("a", "0", det_sizes=320)], "unknown keys"),
        ([cam("a", "0", track_lost_secs=0)], "track_lost_secs"),
        ([cam("a", "0", track_activation=1.1)], "track_activation"),
        ([cam("a", "0", track_min_frames=0)], "track_min_frames"),
        (["a"], "must be an object"),
    ],
)
def test_bad_config_says_why(entries, message):
    with pytest.raises(rc.ConfigError, match=message):
        rc.parse_config(entries)


def test_main_refuses_a_bad_config_before_starting_anything(tmp_path, capsys, monkeypatch):
    path = tmp_path / "cams.json"
    path.write_text(json.dumps([cam("cam1", "0"), cam("cam2", "0")]))
    monkeypatch.setattr(rc, "Launcher", lambda *a, **k: pytest.fail("a process would start"))
    assert rc.main(["--config", str(path), "--out", str(tmp_path)]) == 2
    assert "same source" in capsys.readouterr().err
    assert rc.main(["--config", str(tmp_path / "missing.json")]) == 2
    path.write_text("[{")
    assert rc.main(["--config", str(path)]) == 2


def test_example_config_is_valid():
    cams = rc.load_config(ROOT / "docs" / "cameras.example.json")
    assert len(cams) == 3 and {c.link for c in cams} == {"wifi", "usb"}


def test_tracker_config_is_preserved_and_passed_to_camera_process():
    [camera] = rc.parse_config(
        [cam("cam1", "0", track_lost_secs=4, track_activation=0.55, track_min_frames=3)]
    )
    command = rc.child_command(camera, rc.Options("C:/out", GROUP))

    assert camera.track_lost_secs == 4
    assert camera.track_activation == 0.55
    assert camera.track_min_frames == 3
    assert "--track-lost-secs=4" in command
    assert "--track-activation=0.55" in command
    assert "--track-min-frames=3" in command


def test_tracker_config_defaults_are_omitted_from_child_command():
    camera = rc.parse_config([cam("cam1", "0")])[0]
    command = rc.child_command(camera, rc.Options("C:/out", GROUP))

    assert not any(arg.startswith("--track-") for arg in command)


def test_child_command_carries_the_identity():
    c = rc.Camera("cam1", "http://10.0.0.5:4747/video", "wifi", det_size=320)
    cmd = rc.child_command(c, rc.Options("C:/out", GROUP, preview=True, device="cpu"))
    arg = lambda flag: next(c.split("=", 1)[1] for c in cmd if c.startswith(flag + "="))  # noqa: E731
    assert arg("--camera-id") == "cam1" and arg("--group-id") == GROUP
    assert arg("--det-size") == "320" and arg("--device") == "cpu" and arg("--out") == "C:/out"
    assert arg("--source") == "http://10.0.0.5:4747/video" and arg("--link") == "wifi"
    assert "--stop-on-stdin" in cmd and "--preview" in cmd
    # a value that starts with "-" must not be taken for a flag by the child's argparse
    odd = rc.child_command(rc.Camera("-cam", "-1", "usb"), rc.Options("o", GROUP))
    assert "--camera-id=-cam" in odd and "--source=-1" in odd
    off = rc.Camera("cam2", "0", "usb", preview=False)  # the entry wins over --preview
    assert "--preview" not in rc.child_command(off, rc.Options("o", GROUP, preview=True))
    assert "--preview" in rc.child_command(
        rc.Camera("c", "0", "usb", preview=True), rc.Options("o", GROUP)
    )


# -- the launcher with fake children ---------------------------------------------------------


def test_start_log_masks_url_userinfo_and_query_secrets(tmp_path, monkeypatch, capsys):
    source = "http://phone:secret@10.0.0.5:4747/video?token=token-secret"
    camera = rc.Camera("cam1", source, "wifi")
    lau = rc.Launcher([camera], rc.Options(str(tmp_path), GROUP))

    def opened(self, children, command):
        [child] = children
        child.proc = SimpleNamespace(poll=lambda: None)
        child.opened.set()

    monkeypatch.setattr(lau, "spawn", opened.__get__(lau, rc.Launcher))
    lau.start_one(camera)
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "token-secret" not in output
    assert "token=***" in output


def test_cameras_start_one_at_a_time(tmp_path):
    """Each start waits for the previous child's session line (first starts share device_id)."""
    lau = launcher(tmp_path, {"cam1": "slow", "cam2": "slow", "cam3": "ok"})
    assert run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1", "cam2", "cam3"])) == 0
    t = lambda name: float((tmp_path / name).read_text())  # noqa: E731
    assert t("start_cam2") >= t("session_cam1")
    assert t("start_cam3") >= t("session_cam2")


def test_every_output_line_is_prefixed_with_its_camera(tmp_path, capsys):
    lau = launcher(tmp_path, {"cam1": "ok", "cam2": "ok"})
    run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1", "cam2"]))
    lines = capsys.readouterr().out.splitlines()
    assert all(
        line.startswith(("[cam1] ", "[cam2] ", "[launcher] ")) for line in lines if line.strip()
    ), lines
    for c in ("cam1", "cam2"):
        mine = [x for x in lines if x.startswith(f"[{c}] ")]
        assert any(x.startswith(f"[{c}] session: ") for x in mine)
        assert any(x == f"[{c}] tick 1" for x in mine)
    assert not any(x.startswith("tick") or x.startswith("session") for x in lines)


def test_ctrl_c_stops_every_child_and_no_session_stays_running(tmp_path, capsys):
    cams = ["cam1", "cam2", "cam3"]
    lau = launcher(tmp_path, dict.fromkeys(cams, "ok"))
    # a second and third Ctrl+C while the children are saving must not matter
    assert run_then_ctrl_c(lau, all_ticking(tmp_path, cams), presses=3) == 0
    for c in cams:
        assert (tmp_path / f"stopped_{c}").exists(), "the stop request never reached the child"
        # not a UI stop (D-049); a text-mode pipe ends the line with \r\n on Windows
        assert (tmp_path / f"stdin_{c}").read_bytes().split() == [b"stop"]
        assert status_of(tmp_path, c) == "interrupted"
        assert not lau.children[cams.index(c)].killed
    out = capsys.readouterr().out
    assert "Ctrl+C: stopping every camera" in out
    table = out[out.index("result:") :]
    assert table.count("interrupted") == 3 and "running" not in table
    assert "cam1_" in table  # the session folder is in the table


def test_a_ui_stop_names_its_source_on_every_childs_stop_channel(tmp_path):
    """Studio stops from another thread while run() is in its worker (D-049)."""
    cams = ["cam1", "cam2"]
    lau = launcher(tmp_path, dict.fromkeys(cams, "ok"))
    worker = threading.Thread(target=lau.run)
    worker.start()
    ready = all_ticking(tmp_path, cams)
    deadline = time.monotonic() + 20
    while not ready() and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        lau.stop_all("[app] stop requested", source="ui")
    finally:
        lau.stop(lau.children)  # never leave the worker waiting on its children
        worker.join(30)
    assert not worker.is_alive()
    for c in cams:
        assert (tmp_path / f"stdin_{c}").read_bytes().split() == [b"stop", b"ui"]


def test_a_stop_source_the_child_does_not_know_is_refused(tmp_path):
    """The child ends only `stop ui` normally; any other source would end interrupted unseen."""
    with pytest.raises(ValueError, match="unknown stop source"):
        launcher(tmp_path, {}).stop([], source="app")


def test_a_child_that_fails_to_start_does_not_stop_the_others(tmp_path, capsys):
    lau = launcher(tmp_path, {"cam1": "ok", "bad": "fail", "cam3": "ok"})
    code = run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1", "cam3"]))
    assert code == 1  # one camera did not record
    assert status_of(tmp_path, "cam1") == "interrupted"
    assert status_of(tmp_path, "cam3") == "interrupted"
    out = capsys.readouterr().out
    assert "[bad] error: source_open_failed: cannot open source" in out  # its own message, prefixed
    rows = {r[0]: r for r in (lau.summary(c) for c in lau.children)}
    assert rows["bad"][1:3] == ("-", "cannot open source 'fake'")
    assert rows["cam1"][2] == rows["cam3"][2] == "interrupted"
    assert rows["cam1"][3] == "10.48"  # 11 frames over 1.05 s, as the benchmark computes it
    assert rows["cam1"][4] == "0"  # failed reads, from the child's last line
    result = out[out.index("result:") :].split("report (per camera")[0].splitlines()[1:-1]
    result = [line for line in result if "report failed" not in line]  # fake sessions: no files
    assert [line.split()[1] for line in result] == ["camera_id", "cam1", "bad", "cam3"]


def test_a_start_that_never_gets_a_session_is_stopped_and_marked_failed(tmp_path):
    lau = launcher(tmp_path, {"slow": "silent", "cam2": "ok"}, start_timeout=0.6)
    code = run_then_ctrl_c(lau, lambda: (tmp_path / "session_cam2").exists())
    assert code == 1
    assert (tmp_path / "stopped_slow").exists()  # asked to stop, not left behind
    rows = {r[0]: r for r in (lau.summary(c) for c in lau.children)}
    assert rows["slow"][2].startswith("failed: no session after")
    assert lau.children[0].failure_kind == "start_timeout"
    assert rows["cam2"][2] == "interrupted"


def test_a_child_that_ignores_stop_is_killed_and_the_table_says_so(tmp_path):
    lau = launcher(tmp_path, {"cam1": "ok", "stuck": "deaf"}, stop_timeout=0.8)
    code = run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1", "stuck"]))
    assert code == 1
    rows = {r[0]: r for r in (lau.summary(c) for c in lau.children)}
    assert rows["stuck"][2] == "running (killed)"
    # the real interpreter, not just the venv's python.exe stub in front of it
    assert not alive(int((tmp_path / "pid_stuck").read_text()))
    assert rows["cam1"][2] == "interrupted"


def test_the_launcher_ends_by_itself_when_every_camera_has_stopped(tmp_path):
    """q in every preview window: the children end, the launcher prints the table and exits."""
    lau = launcher(tmp_path, {"cam1": "ok", "cam2": "ok"})
    real = lau.spawn

    def spawn_then_stop(children, command):
        real(children, command)
        [child] = children
        child.proc.stdin.write("stop\n")  # the child ends on its own, as after q
        child.proc.stdin.flush()

    lau.spawn = spawn_then_stop
    assert lau.run() == 0
    assert not any(c.running for c in lau.children)


# -- the real child ---------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["stop line", "stdin closed"])
def test_real_child_stops_like_ctrl_c_on_stdin(tmp_path, long_clips, how):
    out = tmp_path / "out"
    p = subprocess.Popen(
        [sys.executable, "-u", "-m", "services.edge.main", "--no-detect", "--out", str(out),
         "--source", str(long_clips[0]), "--camera-id", "cam1", "--group-id", GROUP,
         "--stop-on-stdin"],  # fmt: skip
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )  # fmt: skip
    try:
        for line in p.stdout:
            if line.startswith("session: "):
                break
        time.sleep(1.0)
        if how == "stop line":
            p.stdin.write("stop\n")
            p.stdin.flush()
        else:
            p.stdin.close()  # what the launcher dying looks like to the child
        text = p.stdout.read()
        assert p.wait(30) == EXIT_INTERRUPTED, text
    finally:
        p.kill()
    assert "Traceback" not in text and "could not acquire lock" not in text
    [folder] = [d for d in out.iterdir() if d.is_dir()]
    session = json.loads((folder / "session.json").read_text())
    assert session["status"] == "interrupted" and session["ended_at"]
    assert session["camera_id"] == "cam1" and session["group_id"] == GROUP
    assert folder.name == f"cam1_{session['session_id']}"
    assert "session interrupted:" in text


def test_real_child_ends_normally_on_a_ui_stop_line(tmp_path, long_clips):
    """Studio's stop (D-049): `stop ui` takes the same shutdown path but is a normal end."""
    out = tmp_path / "out"
    p = subprocess.Popen(
        [sys.executable, "-u", "-m", "services.edge.main", "--no-detect", "--out", str(out),
         "--source", str(long_clips[0]), "--camera-id", "cam1", "--group-id", GROUP,
         "--stop-on-stdin"],  # fmt: skip
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )  # fmt: skip
    try:
        for line in p.stdout:
            if line.startswith("session: "):
                break
        time.sleep(1.0)
        p.stdin.write("stop ui\n")
        p.stdin.flush()
        text = p.stdout.read()
        assert p.wait(30) == 0, text
    finally:
        p.kill()
    assert "Traceback" not in text
    [folder] = [d for d in out.iterdir() if d.is_dir()]
    session = json.loads((folder / "session.json").read_text())
    assert session["status"] == "ended" and session["ended_at"]
    [stop] = [e for e in session["events"] if e["kind"] == "stopped"]
    assert stop["detail"].startswith("ui:") and stop["t_mono"] is not None
    assert "interrupted" not in [e["kind"] for e in session["events"]]
    assert "session ended:" in text


def test_watching_stdin_does_not_stall_a_dll_load():
    """A thread blocked in a read on stdin hung `import scipy` (the model load) in the main
    thread on Windows: the watcher must poll, not read."""
    code = (
        "from services.edge.run.stop import stop_on_stdin; stop_on_stdin();"
        "import scipy.special; print('imported')"
    )
    p = subprocess.Popen(
        [sys.executable, "-c", code], cwd=ROOT, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        p.wait(60)
        assert p.stdout.read().strip() == "imported", p.stderr.read()
    finally:
        p.kill()


def test_a_stop_before_the_threads_start_still_ends_the_session(monkeypatch, tmp_path, clips):
    """The launcher's stop can land right after the session: line, before capture.start()."""

    def interrupted_start(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(Capture, "start", interrupted_start)
    out = tmp_path / "out"
    code = cli.main(["--source", str(clips["moving"]), "--no-detect", "--out", str(out)])
    assert code == EXIT_INTERRUPTED
    [folder] = [d for d in out.iterdir() if d.is_dir()]
    session = json.loads((folder / "session.json").read_text())
    assert session["status"] == "interrupted" and session["ended_at"]


def test_launcher_with_real_children_end_to_end(tmp_path, long_clips, capsys):
    """A group of two real cameras is one real process (R2a 04), stopped by one Ctrl+C: two valid
    sessions."""
    out = tmp_path / "out"
    cams = [rc.Camera(f"cam{i + 1}", str(p), "file") for i, p in enumerate(long_clips)]
    lau = rc.Launcher(cams, rc.Options(str(out), GROUP, no_detect=True))

    def ready():
        up = len(lau.children) == 2 and all(c.opened.is_set() for c in lau.children)
        if up:
            time.sleep(1.0)  # record for a moment
        return up

    assert run_then_ctrl_c(lau, ready) == 0
    [proc] = {c.proc for c in lau.children}
    assert "services.edge.group_main" in proc.args
    docs = []
    for c in ("cam1", "cam2"):
        [folder] = out.glob(f"{c}_*")
        docs.append(json.loads((folder / "session.json").read_text()))
    assert [d["status"] for d in docs] == ["interrupted", "interrupted"]
    assert {d["group_id"] for d in docs} == {GROUP}
    assert [d["camera_id"] for d in docs] == ["cam1", "cam2"]
    assert docs[0]["device_id"] == docs[1]["device_id"] == (out / "device_id").read_text().strip()
    assert docs[0]["session_id"] != docs[1]["session_id"]
    rows = [lau.summary(c) for c in lau.children]
    assert all(r[2] == "interrupted" and r[3] != "-" and r[4] == "0" for r in rows), rows
    # each child wrote its report at the end, and the launcher printed one row per camera
    for c in ("cam1", "cam2"):
        [folder] = out.glob(f"{c}_*")
        [report] = folder.glob("runs/*/report.json")
        assert json.loads(report.read_text())["camera_id"] == c
    shown = capsys.readouterr().out
    table = shown[shown.index("report (per camera") :].splitlines()
    assert [line.split()[1] for line in table[1:]] == ["camera", "cam1", "cam2"]


# -- device_id --------------------------------------------------------------------------------


def test_device_id_race_between_processes_gives_one_id(tmp_path):
    """Six processes start together on a fresh folder: one id, the one in the file."""
    start = time.time() + 2.5  # all import first, then run the same instant
    code = (
        "import sys, time\n"
        "from services.edge.session.writer import device_id\n"
        "while time.time() < float(sys.argv[2]): pass\n"
        "print(device_id(sys.argv[1]))\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path / "fresh"), str(start)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )  # fmt: skip
        for _ in range(6)
    ]
    results = [p.communicate(timeout=60) for p in procs]
    assert all(p.returncode == 0 for p in procs), results
    ids = {out.strip() for out, _ in results}
    assert len(ids) == 1, ids
    assert (tmp_path / "fresh" / "device_id").read_text().strip() == ids.pop()
    assert not any(err for _, err in results)  # nobody had to "repair" the file


def test_device_id_race_between_threads_gives_one_id(tmp_path):
    from services.edge.session.writer import device_id

    barrier, ids = threading.Barrier(16), []

    def go():
        barrier.wait()
        ids.append(device_id(tmp_path))

    threads = [threading.Thread(target=go) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ids) == 16 and len(set(ids)) == 1


def test_device_id_waits_for_a_winner_that_has_not_written_yet(tmp_path):
    """The file exists but is still empty (the winner is between create and write)."""
    from services.edge.session.writer import device_id

    (tmp_path / "device_id").write_text("")
    value = str(uuid.uuid4())
    threading.Timer(0.3, lambda: (tmp_path / "device_id").write_text(value + "\n")).start()
    assert device_id(tmp_path) == value


def test_device_id_replaces_a_corrupt_file_with_a_warning(tmp_path, capsys):
    from services.edge.session.writer import device_id

    (tmp_path / "device_id").write_text("garbage")
    value = device_id(tmp_path)
    assert uuid.UUID(value).version == 4
    assert (tmp_path / "device_id").read_text().strip() == value
    assert "not a valid device id" in capsys.readouterr().err


def test_a_stop_during_session_setup_still_ends_the_session(monkeypatch, tmp_path, clips):
    """The window between the session folder and the main try: held back, then raised inside."""
    from services.edge.session.writer import FileSessionWriter

    real = FileSessionWriter.start

    def start_then_interrupt(self, meta, run):
        real(self, meta, run)  # the folder and a "running" session.json exist now
        _thread.interrupt_main()

    monkeypatch.setattr(FileSessionWriter, "start", start_then_interrupt)
    out = tmp_path / "out"
    code = cli.main(["--source", str(clips["moving"]), "--no-detect", "--out", str(out)])
    assert code == EXIT_INTERRUPTED
    [folder] = [d for d in out.iterdir() if d.is_dir()]
    session = json.loads((folder / "session.json").read_text())
    assert session["status"] == "interrupted" and session["ended_at"]


@pytest.mark.skipif(sys.platform != "win32", reason="SIGBREAK is Windows only")
def test_a_child_ignores_ctrl_break_so_only_the_launcher_stops_it():
    """Ctrl+Break reaches a child in its own process group (Ctrl+C does not) and would kill it
    before it saves."""
    code = (
        "import signal; from services.edge.run.stop import stop_on_stdin; stop_on_stdin();"
        "print(signal.getsignal(signal.SIGBREAK) == signal.SIG_IGN)"
    )
    # stdin stays open until the child has printed, as the launcher keeps it: a closed pipe makes
    # the stdin-stop thread interrupt the main thread while it is still starting that thread
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = child.stdout.readline()
        child.stdin.close()
        child.wait(timeout=60)
        assert line.strip() == "True", child.stderr.read()
    finally:
        child.kill()
        child.wait()
        for pipe in (child.stdout, child.stderr):
            pipe.close()


def test_relative_paths_are_resolved_against_the_launchers_folder(tmp_path, monkeypatch):
    """The children run in the repo folder: a relative file source must not follow them."""
    monkeypatch.chdir(tmp_path)
    [c] = rc.parse_config([cam("a", "clips/x.mp4", "file")])
    assert Path(c.source) == tmp_path / "clips" / "x.mp4"
    cams = rc.parse_config([cam("a", "0"), cam("b", "http://h:1/v"), cam("c", "rtsp://h:2/v")])
    assert [c.source for c in cams] == ["0", "http://h:1/v", "rtsp://h:2/v"]


def test_a_line_the_console_cannot_encode_does_not_kill_the_reader(tmp_path, monkeypatch):
    import io

    lau = launcher(tmp_path, {"cam1": "ok"})
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="ascii"))
    lau.say("[cam1] café ł")  # must not raise
    sys.stdout.flush()
    assert b"[cam1] caf" in sys.stdout.buffer.getvalue()


def test_credentials_in_a_source_are_not_printed_by_the_launcher(tmp_path, capsys):
    with pytest.raises(rc.ConfigError) as e:
        rc.parse_config(
            [cam("a", "http://u:secret@10.0.0.5:4747/video"), cam("b", "http://10.0.0.5:4747/x")]
        )
    assert "secret" not in str(e.value)
    lau = rc.Launcher(
        [rc.Camera("a", "http://u:secret@10.0.0.5:4747/video", "wifi")],
        rc.Options(str(tmp_path), GROUP),
        command=fake_command({"a": "ok"}),
    )
    run_then_ctrl_c(lau, all_ticking(tmp_path, ["a"]))
    assert "secret" not in capsys.readouterr().out


def test_print_event_survives_a_closed_pipe(monkeypatch):
    """The launcher died: the event line has nowhere to go, the session file still gets it."""
    from services.edge.capture.types import HealthEvent

    def broken(*a, **k):
        raise OSError(22, "pipe closed")

    monkeypatch.setattr("builtins.print", broken)
    cli.print_event(HealthEvent("source_lost", "2026-10-13T12:00:00Z", 1.0, "x"), 0.0)


def test_a_console_that_cannot_encode_a_line_does_not_stall_the_child(tmp_path, monkeypatch):
    """A cp1252/ascii pipe (Git Bash without ConPTY, `| tee`): the reader keeps draining, so the
    child never blocks on a full pipe and still stops in time."""
    import io

    out = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict", write_through=True)
    monkeypatch.setattr(sys, "stdout", out)
    lau = launcher(tmp_path, {"cam1": "noisy"}, stop_timeout=15)
    run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1"]))
    assert not lau.children[0].killed
    assert status_of(tmp_path, "cam1") == "interrupted"


def test_cameras_not_started_yet_are_in_the_table(tmp_path, capsys):
    """Ctrl+C during the staggered start: the cameras that never started still get a row."""
    lau = launcher(tmp_path, {"cam1": "ok", "cam2": "slow", "cam3": "ok"})
    code = run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1"]))
    out = capsys.readouterr().out
    assert code == 1
    table = out[out.index("result:") :]
    assert "cam3" in table and "not started" in table
    assert status_of(tmp_path, "cam1") == "interrupted"


def test_error_events_are_counted_and_fail_the_exit_code(tmp_path, capsys):
    """interrupted with a thread that did not stop is still lost data: the table says so."""
    lau = launcher(tmp_path, {"cam1": "ok", "cam2": "errored"})
    code = run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1", "cam2"]))
    rows = {r[0]: r for r in (lau.summary(c) for c in lau.children)}
    assert rows["cam1"][5] == "0" and rows["cam2"][5] == "1"
    assert rows["cam2"][2] == "interrupted"
    assert code == 1


@pytest.mark.parametrize(
    "mode,expected_status",
    [("null-status", "unknown"), ("null-status-deaf", "unknown (killed)")],
)
def test_b7_launcher_summarises_null_status(tmp_path, capsys, mode, expected_status):
    lau = launcher(tmp_path, {"cam1": mode}, stop_timeout=0.8)
    code = run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1"]))
    output = capsys.readouterr().out
    table = output[output.index("result:") :].split("report (per camera")[0]
    assert "cam1" in table
    assert expected_status in table
    assert code == 1


def test_b7_launcher_skips_and_notes_non_object_events(tmp_path, capsys):
    lau = launcher(tmp_path, {"cam1": "damaged-events"})
    code = run_then_ctrl_c(lau, all_ticking(tmp_path, ["cam1"]))
    output = capsys.readouterr().out
    table = output[output.index("result:") :].split("report (per camera")[0]
    assert "cam1" in table and "interrupted" in table
    assert "1 (skipped 4 non-object events)" in table
    assert code == 1


def test_a_dead_launcher_stops_every_real_child_cleanly(tmp_path, long_clips):
    """The launcher is killed hard (the console closed, taskkill): its pipes close, and each
    child ends its session as interrupted by itself instead of staying 'running'."""
    out = tmp_path / "out"
    cfg = tmp_path / "cams.json"
    cfg.write_text(json.dumps([cam(f"c{i + 1}", str(p), "file") for i, p in enumerate(long_clips)]))
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    p = subprocess.Popen(
        [sys.executable, "-u", "scripts/run_cameras.py", "--config", str(cfg), "--out", str(out),
         "--no-detect"],  # fmt: skip
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags,
    )  # fmt: skip
    sessions = 0
    for line in p.stdout:
        sessions += "] session: " in line
        if sessions == 2:
            break
    time.sleep(1.0)
    p.kill()  # no table, no stop request: only the closed pipes
    deadline = time.monotonic() + 30
    statuses: list[str] = []
    while time.monotonic() < deadline:
        statuses = [json.loads(f.read_text())["status"] for f in out.glob("c*/session.json")]
        if statuses == ["interrupted", "interrupted"]:
            break
        time.sleep(0.3)
    assert statuses == ["interrupted", "interrupted"], statuses
    for f in out.glob("c*/session.json"):
        assert json.loads(f.read_text())["ended_at"]


def test_a_child_whose_launcher_vanished_still_saves_the_interrupt(tmp_path, long_clips):
    """Both of the child's pipes broken: the interrupted event reaches session.json (rule 6)."""
    out = tmp_path / "out"
    p = subprocess.Popen(
        [sys.executable, "-u", "-m", "services.edge.main", "--no-detect", "--out", str(out),
         "--source", str(long_clips[0]), "--stop-on-stdin"],  # fmt: skip
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )  # fmt: skip
    try:
        for line in p.stdout:
            if line.startswith("session: "):
                break
        time.sleep(1.0)
        p.stdout.close()
        p.stdin.close()
        assert p.wait(30) == EXIT_INTERRUPTED
    finally:
        p.kill()
    [folder] = [d for d in out.iterdir() if d.is_dir()]
    session = json.loads((folder / "session.json").read_text())
    assert session["status"] == "interrupted"
    assert [e["kind"] for e in session["events"]] == ["interrupted"]


def test_a_locked_device_id_is_never_overwritten(tmp_path, monkeypatch):
    """OneDrive or an antivirus holding the file is not a reason to give the device a new id."""
    from services.edge.session import writer as writer_mod

    first = writer_mod.device_id(tmp_path)

    def locked(self, *a, **k):
        raise PermissionError(13, "held by another process")

    monkeypatch.setattr(Path, "read_text", locked)
    monkeypatch.setattr(writer_mod.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        writer_mod.device_id(tmp_path)
    monkeypatch.undo()
    assert (tmp_path / "device_id").read_text().strip() == first


# -- a group's one process (R2a 04) -----------------------------------------------------------


def test_a_groups_lines_reach_the_camera_they_name(tmp_path):
    class Proc:
        stdout = [
            "device: cpu\n",
            "[cam2] session: C:/out/cam2_x\n",
            "[cam1] session: C:/out/cam1_y\n",
            "[cam1] preview_port: 51234\n",
            "[cam2] t0_wall=1 captured=3 dropped=0 failed_reads=7 processed=3\n",
            "error: the group did not run: boom\n",
        ]

    cams = [rc.Camera("cam1", "0", "usb"), rc.Camera("cam2", "1", "usb")]
    lau = rc.Launcher(cams, rc.Options(str(tmp_path), GROUP))
    one, two = (rc.Child(c) for c in cams)
    one.proc = two.proc = Proc()
    lau.read(one, two)
    assert one.loading_model and two.loading_model  # a line about the group reaches every camera
    assert (one.session_dir, two.session_dir) == (Path("C:/out/cam1_y"), Path("C:/out/cam2_x"))
    assert (one.preview_ready, one.preview_port, two.preview_ready) == (True, 51234, False)
    assert (one.failed_reads, two.failed_reads) == ("-", "7")
    assert one.failure is None and two.failure is None  # a run-time error is not a start failure
    assert one.run_errors == two.run_errors == ["the group did not run: boom"]
    assert list(two.tail)[:2] == ["device: cpu", "session: C:/out/cam2_x"]  # for the error panel


def fake_proc(*lines: str):
    return SimpleNamespace(stdout=[line + "\n" for line in lines], poll=lambda: None)


def group_children(tmp_path, *lines: str):
    cams = [rc.Camera("cam1", "0", "usb"), rc.Camera("cam2", "1", "usb")]
    lau = rc.Launcher(cams, rc.Options(str(tmp_path), GROUP))
    one, two = (rc.Child(c) for c in cams)
    one.proc = two.proc = fake_proc(*lines)
    lau.read(one, two)
    return one, two


def test_b2_a_run_error_after_the_session_lines_is_not_a_start_failure(tmp_path):
    one, two = group_children(
        tmp_path,
        "[cam1] session: C:/out/cam1_y",
        "[cam2] session: C:/out/cam2_x",
        "error: final session files could not be written: boom",
    )
    expected = ["final session files could not be written: boom"]
    assert one.failure is None and two.failure is None
    assert one.run_errors == two.run_errors == expected


def test_b2_an_error_before_a_cameras_session_line_is_still_its_start_failure(tmp_path):
    secret = "rtsp://admin:hunter2@10.0.0.9/x"
    one, two = group_children(
        tmp_path,
        "[cam1] session: C:/out/cam1_y",
        f"error: cannot open source {secret}",
        "[cam2] session: C:/out/cam2_x",
    )
    expected = mask_credentials(f"cannot open source {secret}")
    assert "hunter2" not in expected
    assert two.failure == expected and two.run_errors == []
    assert one.failure is None and one.run_errors == [expected]


def test_b2_a_single_cameras_run_error_after_its_session_line(tmp_path):
    cam = rc.Camera("cam1", "0", "usb")
    lau = rc.Launcher([cam], rc.Options(str(tmp_path), GROUP))
    child = rc.Child(cam)
    child.proc = fake_proc("session: C:/out/cam1_y", "error: camera did not stop cleanly")
    lau.read(child)
    assert child.failure is None
    assert child.run_errors == ["camera did not stop cleanly"]


def test_b2_a_single_cameras_error_before_its_session_line_is_a_start_failure(tmp_path):
    cam = rc.Camera("cam1", "0", "usb")
    lau = rc.Launcher([cam], rc.Options(str(tmp_path), GROUP))
    child = rc.Child(cam)
    child.proc = fake_proc("error: cannot open source")
    lau.read(child)
    assert child.failure == "cannot open source"


def test_a_camera_without_a_group_runs_in_its_own_process(tmp_path):
    """One camera runs services.edge.main as before; two cameras run one group process."""
    calls = []

    def command(cam, opts):
        calls.append(("camera", cam.camera_id))
        return fake_command({cam.camera_id: "ok"})(cam, opts)

    def group(cams, opts):
        calls.append(("group", tuple(c.camera_id for c in cams)))
        return [sys.executable, "-c", "pass"]

    def lau(*ids):
        cams = [rc.Camera(cid, f"src-{cid}", "wifi") for cid in ids]
        opts = rc.Options(str(tmp_path), GROUP)
        return rc.Launcher(cams, opts, command=command, group_command=group)

    run_then_ctrl_c(lau("cam1"), all_ticking(tmp_path, ["cam1"]))
    two = lau("cam1", "cam2")
    two.run()  # the stand-in exits at once, with no session
    assert len({c.proc for c in two.children}) == 1
    assert [c.failure for c in two.children] == ["failed to start (exit 0)"] * 2
    assert [c.failure_kind for c in two.children] == ["exited"] * 2
    assert calls == [("camera", "cam1"), ("group", ("cam1", "cam2"))]


def test_the_group_process_gets_each_cameras_own_arguments():
    cams = [
        rc.Camera("cam1", "0", "usb", det_size=640, calibration_path="c1.json"),
        rc.Camera("cam2", "http://10.0.0.5:4747/video", "wifi", http_preview_port=5000),
    ]
    opts = rc.Options("C:/out", GROUP, device="cpu")
    cmd = rc.group_command(cams, opts)
    assert cmd[:4] == [sys.executable, "-u", "-m", "services.edge.group_main"]
    assert [json.loads(a) for a in cmd[4:]] == [rc.camera_args(c, opts) for c in cams]
    assert rc.child_command(cams[0], opts)[4:] == rc.camera_args(cams[0], opts)


@pytest.mark.parametrize(
    "kind",
    [
        "source_open_failed",
        "model_load_failed",
        "calibration_refused",
        "config_conflict",
        "start_timeout",
        "spawn_failed",
        "exited",
    ],
)
def test_t6_typed_failure_keeps_kind_and_detail_before_session(tmp_path, kind):
    one, two = group_children(tmp_path, f"[cam2] error: {kind}: a: [reason]")
    assert one.failure is None
    assert two.failure == "a: [reason]"
    assert two.failure_kind == kind


def test_t6_typed_failure_after_session_is_only_a_run_error(tmp_path):
    one, two = group_children(
        tmp_path, "[cam2] session: x", "[cam2] error: model_load_failed: cannot open weights"
    )
    assert one.failure is None and one.run_errors == []
    assert two.failure is None and two.failure_kind is None
    assert two.run_errors == ["cannot open weights"]


def test_t6_single_camera_tag_is_parsed_and_unknown_tag_is_not_broadcast(tmp_path):
    cam = rc.Camera("cam1", "0", "usb")
    child = rc.Child(cam)
    child.proc = fake_proc("[other] session: wrong", "[cam1] session: right")
    rc.Launcher([cam], rc.Options(str(tmp_path), GROUP)).read(child)
    assert child.session_dir == Path("right")


def test_t6_spawn_failure_is_typed_without_a_child_process(tmp_path):
    cam = rc.Camera("cam1", "0", "usb")
    lau = rc.Launcher(
        [cam],
        rc.Options(str(tmp_path), GROUP),
        command=lambda cam, opts: [str(tmp_path / "missing-executable")],
    )
    assert lau.run() == 1
    assert lau.children[0].failure_kind == "spawn_failed"
    assert lau.children[0].session_dir is None


def test_t6_nested_tag_is_free_text_not_another_status_envelope(tmp_path):
    one, two = group_children(tmp_path, "[cam1] [other] session: wrong")
    assert one.session_dir is None and two.session_dir is None
    assert list(one.tail) == ["[other] session: wrong"]
