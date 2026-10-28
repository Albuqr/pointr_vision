"""A stand-in for `python -m services.edge.main` in the launcher tests: no camera, no model.

    python fake_camera.py MODE CAMERA_ID OUT

It speaks the same protocol: creates <OUT>/<CAMERA_ID>_<uuid>/ with a running session.json,
prints "session: <dir>", prints a tick line every 50 ms, and on any input on stdin (or its end)
finishes the session as "interrupted" and exits 130, like the real child after Ctrl+C. What it
read on stdin is saved as <OUT>/stdin_<CAMERA_ID>.

MODES
  ok       the above
  slow     waits 0.5 s before the session line (a model load)
  silent   never prints the session line, but still stops on request (a stuck start)
  fail     prints an error on stderr and exits 2 without a session (source_open_failed)
  deaf     prints the session line and never reacts to stop (it has to be killed)
  noisy    prints a character an ascii console cannot encode, and 120 KB, before session:
  errored  like ok, but its session.json holds an error event when it stops
"""

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

mode, camera_id, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
(out / f"start_{camera_id}").write_text(str(time.time()))  # when this process began
(out / f"pid_{camera_id}").write_text(str(os.getpid()))

if mode == "fail":
    print("error: cannot open source 'fake'", file=sys.stderr, flush=True)
    sys.exit(2)

stop = threading.Event()


def watch_stdin() -> None:
    try:
        line = os.read(0, 64)
    except OSError:
        line = b""
    (out / f"stdin_{camera_id}").write_bytes(line)  # what the launcher sent, for the tests
    stop.set()


if mode != "deaf":
    threading.Thread(target=watch_stdin, daemon=True).start()

session = out / f"{camera_id}_{uuid.uuid4()}"
run_dir = session / "runs" / str(uuid.uuid4())
run_dir.mkdir(parents=True)
doc = {"camera_id": camera_id, "status": "running", "events": []}
(session / "session.json").write_text(json.dumps(doc))
rows = ["seq,t_recv,t_proc_start,t_proc_end"] + [
    f"{i},{i * 0.1},{i * 0.1},{i * 0.1 + 0.05}" for i in range(11)
]
(run_dir / "frames.csv").write_text("\n".join(rows) + "\n")  # 11 frames over 1.05 s

if mode == "slow":
    time.sleep(0.5)
if mode == "noisy":
    for _ in range(120):
        print("█" + "x" * 1000, flush=True)
if mode != "silent":
    print(f"session: {session}", flush=True)
    (out / f"session_{camera_id}").write_text(str(time.time()))  # when the line was printed

n = 0
while not stop.wait(0.05):
    n += 1
    print(f"tick {n}", flush=True)

doc["status"] = "interrupted"
if mode == "errored":
    doc["events"] = [{"kind": "error", "detail": "capture did not stop in time"}]
(session / "session.json").write_text(json.dumps(doc))
(out / f"stopped_{camera_id}").write_text(str(time.time()))
print(f"session interrupted: {session}", flush=True)
print("t0_wall=x captured=11 dropped=0 failed_reads=0 processed=11", flush=True)
sys.exit(130)
