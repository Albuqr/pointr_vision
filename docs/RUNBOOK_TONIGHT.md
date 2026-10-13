# Runbook: recording tonight (v0)

Goal: record sessions with one or more phones and several people, then check that the data
is there. Everything runs in **Git Bash**. Details of the install are in `README.md`
("Install on a new PC").

## 1. Setup (once per PC)

This code must be merged to `main` first (the clone below fetches `main`).

```bash
py -3.11 --version          # Python 3.11.x; missing: winget install Python.Python.3.11
git clone https://github.com/Albuqr/pointr_vision.git && cd pointr_vision
#   already cloned:  cd pointr_vision && git pull
py -3.11 -m venv .venv
source .venv/Scripts/activate                        # prompt shows (.venv); REQUIRED, every new terminal
nvidia-smi                                           # GPU? note "CUDA Version: xx.x" (top right)
```

Install torch **first**, exactly one of the three (README has the table):

```bash
# NVIDIA, CUDA Version 13.0 or higher
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu130
# NVIDIA, CUDA Version 12.x (12.6-12.9 is the safe range; older 12.x: try it, run the check)
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu126
# no NVIDIA GPU, or nvidia-smi not found
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
```

Then:

```bash
pip install -e ".[dev]"
python -c "import torch; print(torch.__version__, torch.cuda.is_available()); torch.cuda.is_available() and print(torch.cuda.get_device_name(0), (torch.ones(1, device='cuda') + 1).item())"
```

Expect `2.14.1+cu130 True` / `2.14.1+cu126 True`, then the GPU name and `2.0` (a real GPU
calculation), on a GPU PC; `2.14.1+cpu False` on the CPU build. `False` on a GPU PC, or an
error such as "no kernel image is available", is a wrong install or an unsupported GPU:
see the symptom table (section 7).

**Old GPUs (GTX 9xx/10xx, Volta):** the CUDA 13 builds may not support them even when
`nvidia-smi` shows 13.x. Use the `cu126` command, or the CPU build. If the check above fails
on `cu130`, reinstall with `cu126` (uninstall first, see below).

If torch was already installed (for example a plain `pip install -e ".[dev]"` ran before
this step), run `pip uninstall -y torch torchvision` first, otherwise pip says "already
satisfied" and keeps the wrong build.
If Git Bash says `command not found` for `git`, `ls`, `grep` (PyCharm terminal):
`export PATH="/usr/bin:/bin:/mingw64/bin:/cmd:$PATH"`.

## 2. Smoke test (10 seconds, one camera)

Use the laptop webcam first if no phone is connected yet (`--source 0 --link builtin`).

```bash
source .venv/Scripts/activate
python -m services.edge.main --source 1 --link usb --preview --benchmark 10 --out C:/pointr_sessions
```

The **first run downloads the model (about 370 MB, needs internet)** and loads it for several
seconds before the window opens. Check the console:

- `device: cuda:0 (NVIDIA ...)` on a GPU PC, `device: cpu (...)` otherwise.
- `camera delivers 1280x720` (or similar), not an error.
- A window with boxes and `#id` labels on people; banner `OK`.
- After 10 s: `session ended: C:\pointr_sessions\<id>` and a `benchmark:` block.

Not working? Section 7.

## 3. Connecting phones

**DroidCam through the PC client (USB or Wi-Fi), first phone**

1. Phone: open the DroidCam app. For USB, enable USB debugging and plug the cable in.
2. PC client: choose USB or Wi-Fi (phone IP shown in the phone app). **Only ONE active source
   in the client**: remove or hide the other, otherwise one can hide the other's failure.
3. Press the client's **virtual camera hotkey**. Do it again **after every client restart**:
   the virtual camera is off after a restart.
4. A virtual camera that is off still opens but shows **solid green frames** (Pointr reports
   FROZEN). Green = press the hotkey.
5. The camera index is usually `1` (`0` is the laptop webcam). Try `--source 0`, `1`, `2`.

**Second phone (and more): phone URL source.** The DroidCam client serves one phone, so the
other phones are read directly from their stream URL, no client:

1. Phone app on the same network as the PC, showing an address such as `http://192.168.1.50:4747`.
2. Optional: open `http://<ip>:<port>/video` in the PC browser to see that the address
   works, then **close that tab**: a phone app usually serves one viewer at a time, and an
   open tab can make Pointr's connection fail. Apps differ in port and path.
3. **This path (a phone URL read by Pointr) has not been tested on real hardware.** Smoke
   test it for 10 seconds before relying on it (the image must appear in the window):

```bash
python -m services.edge.main --source http://<ip>:<port>/video --link wifi --preview --benchmark 10 --out C:/pointr_sessions
```

4. Then record, as its own process in its own Git Bash window:

```bash
source .venv/Scripts/activate
python -m services.edge.main --source http://<ip>:<port>/video --link wifi --preview --out C:/pointr_sessions
```

Start the processes **one at a time**: wait for the first `session:` line before starting the
second (the first start creates `C:/pointr_sessions/device_id`; two simultaneous first starts
can race on it).

## 4. Recording

Always `--out C:/pointr_sessions`: outside OneDrive (it locks files) and outside the repo.

```bash
source .venv/Scripts/activate
python -m services.edge.main --source 1 --link usb --preview --out C:/pointr_sessions
```

Add `--device cpu` to force the CPU, `--det-size 320` for more speed, drop `--preview` for
the lowest load (headless).

**Stop ONLY with `q` or Ctrl+C.**

- `q` works in the preview window while that window has focus.
- Ctrl+C works in the Git Bash window (press it once and wait for the `session ...:` line).
- Without `--preview` there is no window: stop with Ctrl+C only.
- **Never** PyCharm's Stop button, the console's X or Ctrl+Break: the files stay at status
  `running` and the final counts are missing. The rows already written are still readable.

One run = one session folder `C:/pointr_sessions/<session_id>/`. Wait for the line
`session ended:` (after `q`), `session interrupted:` (after Ctrl+C) or `session error:` before unplugging a phone or closing the window.

## 5. Check a session afterwards

```bash
ls -t C:/pointr_sessions | head -4            # newest first; copy a session id (`device_id` is not one)
S=C:/pointr_sessions/<session_id>
grep -E '"status"|"started_at"|"ended_at"' $S/session.json
wc -l $S/runs/*/frames.csv; head -5 $S/runs/*/tracks.csv
```

Good: `"status": "ended"`, `ended_at` filled, `frames.csv` has many lines (one header + one per
processed frame), `tracks.csv` has rows when people were in view. Also look at
`$S/runs/*/run.json`: `runtime.device` and `runtime.gpu` say what ran the detector.

`"status": "running"` after you stopped = it was stopped the wrong way (section 4).
`"interrupted"` = Ctrl+C, normal. `"error"` = read `events` in `session.json`.

## 6. Reading the data

- `frames.csv` has one row per **processed** frame, including frames with 0 detections.
  `seq` is the capture sequence number: **gaps in `seq` = frames that were dropped**
  (processing slower than the camera) or not processed. The totals are in `run.json` `counts`.
- A person needs **2 consecutive detections** before they get a `track_id`, and a person
  detected with a score between 0.5 and 0.7 never starts a track (tracker threshold 0.7,
  detector threshold 0.5). So `n_detections` can be higher than `n_tracks`; that is expected.
- **Track IDs are temporary.** They are valid only inside one run. A person who leaves the
  frame and returns gets a **new ID**; IDs do not identify people.
- `tracks.csv` has only tracked people, one row per person per frame (box in pixels).
- `session.json` `events` lists problems: `frozen_frames`, `dark_frames`, `source_lost`,
  `writer_backlog`, errors.

## 7. Symptom, then check

| Symptom | Check |
|---|---|
| `python: command not found` (or `pip` not found) | The venv is not active. `source .venv/Scripts/activate` in this terminal; the prompt must show `(.venv)` |
| `git`, `ls`, `grep` not found | `export PATH="/usr/bin:/bin:/mingw64/bin:/cmd:$PATH"` |
| `cannot open source`, or the wrong camera | Wrong index. Try `--source 0`, `1`, `2`. Close other programs using the camera (Zoom, Teams) |
| Solid green image, `FROZEN` banner | DroidCam virtual camera is off: press the client hotkey (again after every client restart). Only one active source in the client |
| Phone URL does not open | Open `http://<ip>:<port>/video` in the PC browser first. PC and phone on the same Wi-Fi? Some networks (campus, guest Wi-Fi, some routers) isolate devices: use a **phone hotspot** (turn it on on one phone; connect the PC and the other phones to it) |
| Low fps, laggy | Run with `--det-size 320`. Read the `device:` line: it must say `cuda:0 (...)` on a GPU PC; `cpu` means the CPU is detecting. Close the preview (`--preview` off) and other heavy programs |
| `torch.cuda.is_available()` is `False` after a CUDA install | Wrong torch wheel: `python -c "import torch; print(torch.__version__)"` says `+cpu` or has no `+cu...` suffix. Reinstall: `pip uninstall -y torch torchvision`, then the CUDA command from section 1, then `pip install -e ".[dev]"` again. Still `False` with `+cu...`: update the NVIDIA driver; `nvidia-smi` must work |
| `error: --device cuda but torch ... cannot use a CUDA GPU` | Same as the row above; or drop `--device cuda` (auto falls back to CPU) |
| `model load failed: ...` | Read the rest of the line. A network or download error: the first run needs internet (about 370 MB); connect and run again (cached afterwards in `~/.roboflow/models`). Mentions CUDA, a kernel image or out of memory: run again with `--device cpu`, and see the CUDA rows above |
| `error: device check failed` | torch does not import (often a missing Visual C++ runtime, or a broken install): reinstall torch as in section 1 |
| `session.json` stays `running` | The program was killed (Stop button, X, power). Next time stop with `q` or Ctrl+C |

## 8. Privacy

- **Tell everyone in view that they are being recorded**, before you start.
- `C:/pointr_sessions` holds data about real people. **Never commit it, never upload or
  share it** (no git, no cloud drive, no chat). Keep it on this PC.
- Do not copy session data into the repo folder.
