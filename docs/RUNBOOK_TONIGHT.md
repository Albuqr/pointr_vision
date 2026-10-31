# Runbook: recording tonight (v0)

Goal: record sessions with several phones at once (one launcher, one process per camera) and
several people, then check that the data is there. Everything runs in **Git Bash**. Details of
the install are in `README.md` ("Install on a new PC").

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

This installs the FastAPI/Uvicorn app backend too. Node is not required to run Pointr Studio;
the built frontend is committed. Node is only needed to edit, build, or lint the UI.

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

After installation, use Pointr Studio as the main path:

```bash
python -m services.app --out C:/pointr_sessions
```

It opens a local browser at `127.0.0.1:8765`; Node is not needed to run it. Add and test
the cameras in **Cameras**, then start/stop the group in **Record**. Closing the browser tab
does not stop a recording. Ctrl+C in the app terminal stops all cameras cleanly. The CLI
commands below remain the fallback when the UI is unavailable.

Before collecting distances or speeds, calibrate each camera in **Calibration**. Mount each
phone first and do not move it afterward. Choose the camera and court size, capture a frame,
then pair floor landmarks spread across the visible area. Use at least four fit points and two
separate held-out check points; confirm a known distance with a tape measure. Check error is
reported in metres, and saving above the configured limit requires **Save anyway**. Recalibrate
if the camera moved. Positions are invalid while a player is in the air because the box
bottom-centre is not on the floor. A saved calibration is applied automatically on recording;
the session report states whether positions are in metres or pixels.

**Half-court setup (FIBA 14 × 15 m).** For a two-phone session, mount one phone high near each
sideline/baseline corner and aim both diagonally so the baseline and midcourt line stay visible.
Calibrate each camera separately after mounting. Select **Half court**; click the visible baseline
corners (x=0) and midcourt-line corners (x=14) as the four fit points. The diagram highlights
these anchors. Use two separate visible lane intersections or measured floor marks as held-out
checks. A camera that sees only part of the half may use the landmarks it sees, as long as they are
not collinear or bunched (D-070); the check points report how well they hold. If a recommended
corner is hidden, use a measured floor mark with its actual coordinates. Keep out-of-court positions in the report;
the calibration does not clamp them.

**Tape-mark check.** Before recording, place tape marks on the floor 0.5 m in from the sideline,
at x=1 m and x=4 m from the basket baseline. Add both as held-out check points at (1, 0.5) and
(4, 0.5), not as fit points. The fitted distance between them should be 3 m; record the measured
distance difference and the held-out residuals for each phone. Repeat after moving either phone.

To use the CLI instead, pass the saved JSON explicitly with `--calibration FILE`. The saved
image dimensions must match the capture resolution.

To measure HTTP-preview overhead on the same PC and source, run two matched 60-second CLI
benchmarks, one without preview and one with the off-thread preview encoder:

```bash
python -m services.edge.main --source 0 --link builtin --benchmark 60 --out C:/pointr_sessions
python -m services.edge.main --source 0 --link builtin --benchmark 60 --http-preview 0 --out C:/pointr_sessions
```

Compare the `benchmark:` processed FPS, app delay, and drops printed for each run; the second
line explicitly says `preview on`. Repeat both runs if their capture conditions differ. The
session reports preserve the resulting measured rates and units; do not claim a preview cost
without the matched measurements.

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

**Default: every phone is read by its URL. No PC client.** Checked on real hardware with the
DroidCam app over Wi-Fi: `--source http://10.10.8.158:4747/video` gave 1280x720, reported 25 fps,
about 28 fps captured, and the session ended cleanly.

For each phone:

1. The phone and the PC are on the same Wi-Fi (or the PC joined the phone's hotspot).
2. Open the DroidCam app on the phone. It shows an address such as `http://192.168.1.50:4747`:
   that is the phone's IP and port. Write the IP down. Apps differ in port and path; for
   DroidCam the video is `http://<ip>:4747/video`.
3. Test it **once** in the PC browser: open `http://<ip>:4747/video`, see the live image,
   then **CLOSE THE TAB**. A phone serves **ONE viewer only**. While a browser tab (or the
   DroidCam PC client, or any other program) is reading it, Pointr's connection fails with
   `source_open_failed` ("DroidCam is Busy or Unavailable" in the browser). Closing the tab
   fixes it.
4. Put the phone in `cams.json` (section 4). Never give two entries the same phone: the launcher
   refuses to start.

**Fallback for ONE phone: the DroidCam PC client (USB or Wi-Fi).** Use it only if the URL does
not work on the day. The client holds the phone's single viewer slot, so that phone can no
longer be read by URL while the client runs.

1. Phone: open the DroidCam app (USB: enable USB debugging, plug the cable in).
2. PC client: choose USB or Wi-Fi. **Only ONE active source in the client.**
3. Press the client's **virtual camera hotkey**, again **after every client restart**. A virtual
   camera that is off still opens but shows **solid green frames** (Pointr reports FROZEN).
4. The camera index is usually `1` (`0` is the laptop webcam). In `cams.json` use
   `"source": 1, "link": "usb"` (or `wifi`).

## 4. Recording: the launcher

One process per camera, no fusion across cameras: every camera is its own session (own folder,
clock, files) and all cameras of one start share a `group_id`.

**4.1 The config.** Copy the example (the real file is not committed):

```bash
cp docs/cameras.example.json cams.json      # then edit it
```

```json
[
  {"camera_id": "cam1", "source": "http://192.168.1.50:4747/video", "link": "wifi"},
  {"camera_id": "cam2", "source": "http://192.168.1.51:4747/video", "link": "wifi", "det_size": 320},
  {"camera_id": "cam3", "source": 1, "link": "usb", "preview": false,
   "track_lost_secs": 4, "track_activation": 0.7, "track_min_frames": 2}
]
```

`camera_id`: a short label (letters, digits, `_`, `-`, up to 32), it goes into the session folder
name. `source`: a phone URL, or a camera index (`0` laptop webcam). `link`: `wifi`, `usb` or
`builtin`. Optional: `det_size` (a multiple of 32, e.g. `320`: faster, less accurate) and
`preview` (`true` or `false` for this camera only; without it the `--preview` flag decides).
Optional tracker settings are `track_lost_secs` (default 1.0), `track_activation` (default 0.7),
and `track_min_frames` (default 2); each overrides that camera's CLI default.

**4.2 Start.**

```bash
source .venv/Scripts/activate
python scripts/run_cameras.py --config cams.json --out C:/pointr_sessions --preview
```

Always `--out C:/pointr_sessions`: outside OneDrive (it locks files) and outside the repo. Drop
`--preview` for the lowest load (no windows). `--device cpu` forces the CPU.

- Cameras start **one at a time**: the launcher waits for the `session:` line of one camera
  before it starts the next (each loads its own model; the first run downloads about 370 MB).
  Allow some seconds per camera. A camera that does not get a session within 180 s is marked
  failed and the others go on.
- Every output line is prefixed with its camera: `[cam1] ...`, and `[launcher] ...` for the
  launcher itself. With `--preview` each camera has its own window, `Pointr cam1 (q to quit)`.
- A camera that cannot open its source (`[cam2] error: cannot open source ...`) does **not**
  stop the others. Fix it (section 7), then stop everything and start again: one launcher
  start is one group.
- Two entries with the same source (the same phone, the same camera index) are refused before
  anything starts.

**4.3 Stop.**

- **Ctrl+C once, in the launcher's Git Bash window.** (Checked on real hardware: it reaches
  every camera and both sessions ended `interrupted`.) The launcher asks every camera to stop
  the way Ctrl+C stops a single one, waits for each to save, then prints the result table. Wait
  for it (a few seconds). A second Ctrl+C only prints a reminder.
- **`q` in a camera's preview window stops only that camera** (its session ends `ended`); the
  others keep recording. When every camera has stopped the launcher prints the table and exits.
- **Never** PyCharm's Stop button, the console's X, or killing processes: sessions can stay at
  status `running` and the final counts are missing. The rows already written stay readable.
  (If the launcher itself is killed, the cameras notice the closed pipe and stop on their own
  with status `interrupted`, but do not rely on it; closing a mintty window was not tested.)
  If a camera does not stop within 45 s the launcher kills it and the table says `(killed)`.

**4.4 The result table.**

```
camera_id  session folder                              final status              processed fps  failed reads  errors
cam1       cam1_3f1c2a8e-5b7d-4e9a-8c21-6d4f0b9e7a13   interrupted               2.10           0             0
cam2       -                                           failed to start (exit 2)  -              -             -
cam3       -                                           not started               -              -             -
```

`final status` comes from each `session.json`: `ended` (q, or the source ended), `interrupted`
(Ctrl+C), `error` (read `events` in its `session.json`), or `running (killed)`. `failed reads` is
the capture's failed read count; the phone should show 0. `errors` counts the `error` events in
`session.json` (for example a thread that did not stop in time: the counts may be short).
`not started`: Ctrl+C came before that camera's turn. `processed fps` is processed frames over
the time from the first processing start to the last end, from `frames.csv`. The launcher exits
0 only if every camera ended or was interrupted with no error event.

**4.5 Memory and CPU: measure on the PC you record with.** Every camera is a process with its
own copy of the model. Measured on the dev notebook (CPU build, two processes, a 640x360 file
source, 12 s into detection): about **610 MB resident per process (peak 862 MB), about 1.2 GB
committed**, and the launcher itself about 4 MB. The two cameras shared one CPU: 2.10 and 1.56
processed fps, against 2.84 for one camera alone on the same clip (one short run each, not a
benchmark). A GPU PC was not measured; CUDA adds its own host memory. With N cameras expect
about N GB of RAM and watch Task Manager during the first run.

**CPU contention, measured on real hardware (laptop webcam + phone URL, i7-10510U, CPU
build):** the laptop camera processed 1.5-1.7 fps and the phone URL camera 0.35-0.57 fps, against
about 2-2.4 fps for one camera alone; the second camera's model load took 27-30 s. So: **on a
CPU-only PC use at most 2 cameras, both with `"det_size": 320`**. **On a GPU PC, check that each
camera's `[camN] device:` line says `cuda:0 (...)`**: a camera that says `cpu` is slowing the
others. If the PC is short of RAM or slow, record fewer cameras per PC or drop `--preview`.

**4.6 One camera, without the launcher (fallback).**

```bash
source .venv/Scripts/activate
python -m services.edge.main --source http://<ip>:4747/video --link wifi --camera-id cam1 --preview --out C:/pointr_sessions
python -m services.edge.main --source 1 --link usb --preview --out C:/pointr_sessions
```

One command per Git Bash window; `--camera-id` and `--group-id` are optional (a session
without a camera id is a folder named `<session_id>`). `--det-size 320` for more speed.
Stop with `q` (window focused) or Ctrl+C (once, wait for the `session ...:` line). Without
`--preview` there is no window: Ctrl+C only.

## 5. After recording: check the files, then read the report

```bash
ls -t C:/pointr_sessions | head -6            # newest first: <camera_id>_<session_id> (`device_id` is not a session)
S=C:/pointr_sessions/<folder>                 # one camera's folder
grep -E '"camera_id"|"group_id"|"status"|"started_at"|"ended_at"' $S/session.json
wc -l $S/runs/*/frames.csv; head -5 $S/runs/*/tracks.csv
```

Good: `"status": "ended"`, `ended_at` filled, `frames.csv` has many lines (one header + one per
processed frame), `tracks.csv` has rows when people were in view. Also look at
`$S/runs/*/run.json`: `runtime.device` and `runtime.gpu` say what ran the detector.

`"status": "running"` after you stopped = it was stopped the wrong way (section 4).
`"interrupted"` = Ctrl+C, normal. The cameras recorded together have the same `group_id` and
different `camera_id`s; each has its own clock (`t0_wall` in its `run.json`), nothing aligns them
for you. `"error"` = read `events` in `session.json`.

**The report.** When a session ends, Pointr writes `runs/<run_id>/report.json` next to
`run.json` and prints its summary. With the launcher every camera prints its own, and the
launcher ends with one row per camera (duration, processed fps, coverage, tracks). A report
failure is only a warning: the session is saved anyway. Run it again at any time, with other
settings if you like, for one camera or for the whole recording:

```bash
source .venv/Scripts/activate
python -m services.edge.report C:/pointr_sessions/<folder>                      # one camera
python -m services.edge.report --group <group_id> --out C:/pointr_sessions      # one section per camera
```

The `group_id` is on the `[launcher] group ...` line at the start of a launcher run, and in each
`session.json`. Options: `--max-gap 1.0` (seconds; longer gaps between samples are left out of
speed), `--smooth 3` (moving-median window, in samples), `--stationary-below` and
`--walking-below` (px/s thresholds), `--short-track 1.0`, `--run <run_id>`. The cameras are
reported **separately**: nothing is fused or aligned across cameras.

How to read it (the numbers come from this run's own files; the `caveats:` block says what they
do not mean):

- **Top lines.** `processed ... fps` and `frame interval` tell how dense the data is: at
  about 0.5 s between samples a track is a rough sketch of the movement, at 2 s or more it
  hardly is. `coverage` is the share of *processed* frames with at least one person; frames the
  processor skipped (`dropped`) are not in it. `events` are the problems from `session.json`
  (`source_lost`, `dark_frames`, ...) with the time since the start of that camera's run.
- **One row per track** (a track is an ID, not a person: the same person who leaves and returns
  gets a new one). `seen` is first to last sample, `n` the samples, `med dt` the median time
  between them. `path` is the distance between consecutive samples, in **pixels**, and
  `mean`/`max` are speeds in **px/s**, from the bottom-centre of the person's box. Pixels
  are not metres: the same walk looks longer close to the camera.
- **Gaps are left out.** Only intervals of at most `--max-gap` seconds between samples count.
  `n_gaps_excluded` and `gap_time` in `report.json` say how much was left out; the path and the
  speeds describe only the rest, so a track that is mostly gaps says little.
- **`n/a` is not zero.** A track with one sample, or fewer than 2 usable intervals, has no
  speed; the line below the table says why.
- **`stat/walk/run %`** is the share of the usable time spent below 40 px/s, between 40 and
  400, above 400. These limits are placeholders: they depend on how far the camera is, so
  compare cameras and sessions only when the camera stayed where it was.
- **`short`** tracks (under 1 s, `report.json` `short`) are often fragments or false positives.
  Many of them in a session means the tracker is losing people.
- If IDs fragment a lot (many short tracks in the report), raise `--track-lost-secs` to 3–5;
  the trade-off is that two players crossing may swap IDs.
- `report.json` has the same numbers with units (`{"value": ..., "unit": ...}`), and a null
  value always has a `reason`.

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
| `cannot open source`, or the wrong camera | Wrong index. Try `0`, `1`, `2`. Close other programs using the camera (Zoom, Teams) |
| `source_open_failed` on a phone URL that works in the browser | The phone serves ONE viewer and another one is on it: **close the browser tab** (or the DroidCam PC client, or another Pointr using the same phone), wait a few seconds, start again |
| Launcher: `use the same source` and nothing starts | Two entries in `cams.json` point at the same phone or index. One entry per phone |
| Launcher: `[cam2] ... failed to start (exit 2)` in the table | That camera's source did not open (see its `[cam2]` lines above); the other cameras recorded normally. Fix it, then stop and start the launcher again |
| Launcher: `failed: no session after 180 s` | The model load or the source open is stuck. Look at that camera's `[camN]` lines; try `--device cpu`, or fewer cameras |
| Table says `running (killed)` | A camera did not stop within 45 s and was killed: its files are readable up to the last second, the counts are missing |
| One camera shows `source_lost` and the others do not | That phone lost its Wi-Fi or went to sleep (phone screen off, app in the background). Checked on real hardware: `source_lost` about 2 s after the Wi-Fi went off (the stream read times out after 2.1 s), `source_recovered` when it came back, the other camera unaffected |
| Solid green image, `FROZEN` banner | DroidCam virtual camera is off: press the client hotkey (again after every client restart). Only one active source in the client |
| Phone URL does not open | Open `http://<ip>:4747/video` in the PC browser first (then close the tab). PC and phone on the same Wi-Fi? Some networks (campus, guest Wi-Fi, some routers) isolate devices: use a **phone hotspot** (turn it on on one phone; connect the PC and the other phones to it) |
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
