# Pointr

Pointr collects sports training data from a live camera. A phone works as the camera, a
notebook runs person detection and tracking. See `CLAUDE.md` and `docs/` for the design and
the current phase.

## Install on a new PC (Windows, Git Bash, Python 3.11)

Run everything in **Git Bash**, step by step.

```bash
# 1. Python 3.11 must exist (3.12+ has not been tested with the pinned wheels)
py -3.11 --version    # expect: Python 3.11.x (missing: winget install Python.Python.3.11)

# 2. Get the code (first time: clone; afterwards: pull)
git clone https://github.com/Albuqr/pointr_vision.git && cd pointr_vision
#   already cloned:  cd pointr_vision && git pull

# 3. Create the virtualenv and ACTIVATE it. Without the activation `python` is not found
#    (or is another Python), and every command below fails.
py -3.11 -m venv .venv
source .venv/Scripts/activate            # the prompt now starts with (.venv)
#   Git Bash inside PyCharm sometimes loses PATH ("command not found: git/ls/grep"):
#   export PATH="/usr/bin:/bin:/mingw64/bin:/cmd:$PATH"
```

**4. Is there an NVIDIA GPU?** Run `nvidia-smi`. If it prints a table, read `CUDA Version`
in its top-right corner: it is the newest CUDA the *driver* supports. If the command is not
found, there is no NVIDIA driver: use the CPU install.

**5. Install torch and torchvision first** (exactly one of these; the versions are the ones
pinned in `pyproject.toml`, and wheels for Windows + Python 3.11 exist on every index below,
checked 2026-10-13):

| `nvidia-smi` shows | Use |
|---|---|
| `CUDA Version: 13.0` or higher | (a1) CUDA 13.0 |
| `CUDA Version: 12.6` to `12.9` | (a2) CUDA 12.6 (older 12.x: try it, run the check below) |
| GTX 9xx/10xx or Volta GPU, any version | (a2): the CUDA 13 build may not support them |
| lower than 12.6, or no NVIDIA GPU | (b) CPU (for the lower case, updating the driver also works) |

```bash
# (a1) NVIDIA, CUDA 13.0
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu130
# (a2) NVIDIA, CUDA 12.6
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu126
# (b) CPU only
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
```

The pins do not change: the `+cu130`, `+cu126` and `+cpu` builds are all `2.14.1` /
`0.29.1`, so the next step accepts them. Do not run `pip install torch` without
`--index-url`: pip may pick another build.

```bash
# 6. Pointr, its pinned runtime dependencies and the dev tools (about 1 GB in total)
pip install -e ".[dev]"

# 7. One-line check
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
#   CPU build:  2.14.1+cpu False        CUDA build:  2.14.1+cu126 True  (or +cu130)
# on a GPU also run a real GPU calculation (prints the GPU name and 2.0):
python -c "import torch; print(torch.cuda.get_device_name(0), (torch.ones(1, device='cuda') + 1).item())"
```

If a CUDA install prints `False`, see the symptom table in `docs/RUNBOOK_TONIGHT.md`.

The editable install also installs the local app's FastAPI/Uvicorn backend. Node is not
needed to run Pointr Studio; its built frontend is included. Node is only needed to develop
the UI under `services/app/ui`.

The RF-DETR Nano weights (`rf-detr-nano.pth`, 366 MB) download on the first run
that loads the model, to `~/.roboflow/models` (set `RF_HOME` to change it), and are checked
against an md5. **The first run needs internet.** Loading the model takes several seconds
before capture starts.

`--device auto` (the default) uses CUDA when torch sees a CUDA GPU and the CPU otherwise;
`--device cpu` and `--device cuda` force one (`cuda` exits with an error if torch sees no
CUDA GPU). The chosen device and GPU name are printed at start and written to `run.json`.

## Run

Start Pointr Studio (the local recording UI):

```bash
python -m services.app --out C:/pointr_sessions
```

The app binds to `127.0.0.1:8765` and opens the browser. The command-line camera modes
remain available as a fallback:

Calibrate each fixed camera in Studio before using metre-based positions and speeds. For the
CLI fallback, pass its saved calibration JSON with `--calibration FILE`; the capture resolution
must match the saved image size. See `docs/RUNBOOK_TONIGHT.md` for point roles and measurement
guidance.

To develop the frontend, install Node 22.12+ and run `npm ci`, `npm run build`, and
`npm run lint` from `services/app/ui`. Node is not a runtime prerequisite.

```bash
python -m services.edge.main --source 1 --link usb --preview         # detect + track
python -m services.edge.main --source 1 --link usb --benchmark 120   # 2-minute baseline
python -m services.edge.main --source 1 --link usb --preview --no-detect   # capture only
python -m services.edge.main --source 1 --link usb --calibration C:/path/camera.json
python -m services.edge.main --help
```

`--source` is a webcam index, a stream URL or an `.mp4`/`.mov` file. Press `q` in the preview
window or Ctrl+C to stop.

## Recording, replay and scoring

A live run keeps the raw video as `video.mp4` in its session folder (`--no-record` to skip it);
`frames.csv` `t_video` is each frame's time in that video. Process a recorded video again, as a
new run that leaves the original untouched, with a session id, a session folder or a `.mp4`/`.mov`
file (every frame is processed, at file speed):

```bash
python -m services.edge.main --replay <session id | session folder | video file> --out C:/pointr_sessions
```

To score a session, write `labels.csv` in its folder (columns `time_s,event,player_number,note`;
`time_s` is the time in `video.mp4`; events `attempt`, `make`, `miss`, `leave`, `return`), then:

```bash
python -m services.edge.score C:/pointr_sessions/<session folder>
```

It prints H1 and H3b next to their thresholds; H3 and H4 are "not scorable" with this label
format (DECISIONS D-043), and H1 needs the shot layer (slice R3).

## DroidCam setup

The phone runs the DroidCam app; the notebook runs the DroidCam Client, which exposes the
phone as a virtual webcam (usually index `1`).

- **One active source only.** The client can stack a Wi-Fi and a USB source. When one drops,
  the other can show through and hide the failure. Keep only the source you are testing,
  and hide or remove the other in the client.
- **Enable the virtual camera after every client restart.** In the free client the virtual
  camera has no menu button: it is turned on with the hotkey you configured, and it is off
  again after the client restarts. While it is off, index `1` still opens but delivers solid
  green frames, which Pointr reports as FROZEN.
- USB: choose the device in the client's source properties (refresh the device list) with USB
  debugging on. Wi-Fi: phone and notebook on the same network.

## Tests

```bash
ruff check . && ruff format --check .
pytest -q            # no camera, no network, no model weights
pytest -q -m slow    # real model; downloads the weights and test images on first run
```
