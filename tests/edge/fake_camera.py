"""A stand-in for `python -m services.edge.group_main` in the launcher tests: no camera, no model.

    python fake_camera.py OUT MODE:CAMERA_ID [MODE:CAMERA_ID ...]

One process for the whole group, as the launcher always starts it. Each camera creates
<OUT>/<CAMERA_ID>_<uuid>/ with a running session.json, prints "session: <dir>", prints a tick line
every 50 ms, and on any input on stdin (or its end) finishes its session as "interrupted"; the
process then exits 130, like the real one after Ctrl+C. Lines carry a "[camera_id] " tag only when
the group has more than one camera. What the process read on stdin is saved as
<OUT>/stdin_<CAMERA_ID> for each camera.

MODES (per camera)
  ok       the above
  slow     waits 0.5 s before the session line (a model load)
  silent   never prints the session line, but still stops on request (a stuck start)
  fail     prints an error and gives that camera up without a session (source_open_failed); the
           others go on, and a process whose cameras all failed exits 2
  deaf     prints the session line and never reacts to stop (the process has to be killed)
  noisy    prints a character an ascii console cannot encode, and 120 KB, before session:
  errored  like ok, but its session.json holds an error event when it stops
  null-status  like ok, but ends with a null status
  null-status-deaf  like deaf, but leaves a null status
  damaged-events  like errored, with non-object entries mixed into the events
"""

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.edge.child_protocol import (  # noqa: E402
    SessionOpened,
    StartFailed,
    Summary,
    emit,
)

out = Path(sys.argv[1])
specs = [a.split(":", 1) for a in sys.argv[2:]]
tagged = len(specs) > 1
out.mkdir(parents=True, exist_ok=True)
stop = threading.Event()
lock = threading.Lock()  # the cameras' threads must not interleave their lines


def say(text: str) -> None:
    with lock:
        print(text, flush=True)


def watch_stdin() -> None:
    try:
        line = os.read(0, 64)
    except OSError:
        line = b""
    for _, camera_id in specs:  # what the launcher sent, for the tests
        (out / f"stdin_{camera_id}").write_bytes(line)
    stop.set()


if any(mode not in ("deaf", "null-status-deaf") for mode, _ in specs):
    threading.Thread(target=watch_stdin, daemon=True).start()


def run_camera(mode: str, camera_id: str) -> bool:
    """One camera of the group; False when it never recorded."""
    tag = camera_id if tagged else None
    prefix = f"[{tag}] " if tag else ""
    (out / f"start_{camera_id}").write_text(str(time.time()))  # when this process began
    (out / f"pid_{camera_id}").write_text(str(os.getpid()))
    if mode == "fail":
        with lock:
            emit(StartFailed("source_open_failed", "cannot open source 'fake'"), tag)
        return False
    session = out / f"{camera_id}_{uuid.uuid4()}"
    run_dir = session / "runs" / str(uuid.uuid4())
    run_dir.mkdir(parents=True)
    doc = {"camera_id": camera_id, "status": "running", "events": [], "runs": [run_dir.name]}
    if mode == "null-status-deaf":
        doc["status"] = None
    (session / "session.json").write_text(json.dumps(doc))
    rows = ["seq,t_recv,t_proc_start,t_proc_end"] + [
        f"{i},{i * 0.1},{i * 0.1},{i * 0.1 + 0.05}" for i in range(11)
    ]
    (run_dir / "frames.csv").write_text("\n".join(rows) + "\n")  # 11 frames over 1.05 s

    if mode == "slow":
        time.sleep(0.5)
    if mode == "noisy":
        for _ in range(120):
            say("█" + "x" * 1000)
    if mode != "silent":
        with lock:
            emit(SessionOpened(str(session)), tag)
        (out / f"session_{camera_id}").write_text(str(time.time()))  # when the line was printed

    n = 0
    deaf = mode in ("deaf", "null-status-deaf")
    while True:
        if deaf:
            time.sleep(0.05)
        elif stop.wait(0.05):
            break
        n += 1
        say(f"{prefix}tick {n}")

    doc["status"] = "interrupted"
    if mode == "null-status":
        doc["status"] = None
    if mode == "errored":
        doc["events"] = [{"kind": "error", "detail": "capture did not stop in time"}]
    if mode == "damaged-events":
        doc["events"] = [
            None,
            "damaged",
            7,
            [],
            {"kind": "error", "detail": "capture did not stop in time"},
            {"kind": "stopped", "detail": "stop requested"},
        ]
    (session / "session.json").write_text(json.dumps(doc))
    (out / f"stopped_{camera_id}").write_text(str(time.time()))
    say(f"{prefix}session interrupted: {session}")
    with lock:
        emit(Summary("t0_wall=x captured=11 dropped=0 failed_reads=0 processed=11"), tag)
    return True


results: list[bool] = []
threads = [
    threading.Thread(target=lambda m=m, c=c: results.append(run_camera(m, c))) for m, c in specs
]
for t in threads:
    t.start()
for t in threads:
    t.join()
sys.exit(130 if any(results) else 2)
