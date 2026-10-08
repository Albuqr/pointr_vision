# Pointr

Pointr collects sports training data from a live camera. A phone works as the camera, a
notebook runs person detection and tracking. See `CLAUDE.md` and `docs/` for the design and
the current phase.

## Setup (Windows, Git Bash, Python 3.11)

```bash
python -m venv .venv
source .venv/Scripts/activate
# 1. torch from the CPU index first, so pip does not pick another build
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
# 2. Pointr, its pinned runtime dependencies and the dev tools
pip install -e ".[dev]"
# check: prints "2.14.1+cpu False"
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

The RF-DETR Nano weights (`rf-detr-nano.pth`) download on the first run that loads the
model, to `~/.roboflow/models` (set `RF_HOME` to change it).

## Run

```bash
python -m services.edge.main --source 1 --link usb --preview         # detect + track
python -m services.edge.main --source 1 --link usb --benchmark 120   # 2-minute baseline
python -m services.edge.main --source 1 --link usb --preview --no-detect   # capture only
python -m services.edge.main --help
```

`--source` is a webcam index, a stream URL or an `.mp4`/`.mov` file. Press `q` in the preview
window or Ctrl+C to stop.

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
