# Pointr: instructions for Claude Code

Pointr collects sports training data from a live camera. A phone works as the camera, a
notebook runs detection and tracking, every session is logged locally first, and data is
synced to a server when one is reachable. Basketball first. This is a TCC project.

## Read before doing anything

| File | What it holds |
|---|---|
| `docs/ARCHITECTURE.md` | Components, process boundaries, interfaces, concurrency, storage, sync |
| `docs/DATA_CONTRACTS.md` | File formats, DB tables, API payloads. **Source of truth for every format** |
| `docs/REQUIREMENTS.md` | Functional and non-functional requirements, with the phase that delivers each |
| `docs/PHASES.md` | Phase index and the current phase |
| `docs/phases/PHASE_XX.md` | Scope, out-of-scope, deliverables and acceptance tests of one phase |
| `docs/GATES.md` | How a phase is closed: tests, subagent reviews, manual acceptance |
| `docs/OPEN_QUESTIONS.md` | Decisions not made yet. Do not decide them silently |
| `DECISIONS.md` | Decisions made, including wrong ones and how they were found |

**Current phase:** see `docs/PHASES.md`. Work on that phase only.

## Working rules

1. **One phase at a time.** Implement only what the current phase file lists. Anything else
   goes into `docs/BACKLOG.md` with one line on why it came up.
2. **Contracts first.** If a change needs a new field or format, update
   `docs/DATA_CONTRACTS.md`, bump the contract version, and add a `DECISIONS.md` entry
   before writing the code.
3. **Verify third-party APIs.** Check every `rfdetr`, `supervision` and `opencv` call against
   the installed version (read the source or `help()`), not against memory or blog posts.
   Record versions in `run.json` (DATA_CONTRACTS section 3).
4. **Layers behind interfaces.** Each layer implements a Protocol from
   `docs/ARCHITECTURE.md`. Layers receive data as arguments; they do not reach into each
   other's internals or global state.
5. **No unmeasured claims.** Never write FPS, latency or accuracy figures in docs or code
   comments unless they come from a recorded run. "App delay" (frame received to processing
   done) is not camera-to-screen latency; never call it that.
6. **Absence is data.** Frames with zero detections are logged. Failures are logged as
   events. Nothing is silently dropped, including dropped frames, which are counted.
7. **Tests with every change.** Every acceptance criterion in the phase file maps to at least
   one automated test, or is explicitly marked manual.
8. **Ask before adding a dependency** not listed in the phase file.
9. **Privacy.** `sessions/`, recordings and any real footage are gitignored. Never commit
   video of real people. Test fixtures are synthetic or of the developer only.

## Environment

- Windows 11, PyCharm, Git Bash. Python 3.11+. Virtualenv at `.venv`
  (`source .venv/Scripts/activate`).
- Install (runtime + dev tools), in this order, so torch is the CPU build:
  `pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu`,
  then `pip install -e ".[dev]"`. Check: `python -c "import torch; print(torch.__version__,
  torch.cuda.is_available())"` prints `2.14.1+cpu False`.
- GPU PC (R2-A3, H2): has a CUDA build of torch, newer than the pin above, installed and tested
  by the owner. Read its exact version there with the same check (it prints `True`); `run.json`
  records it on every run.
- If Git Bash loses PATH: `export PATH="/usr/bin:/bin:/mingw64/bin:/cmd:$PATH"`.
- Docker Desktop must be running before any `docker build` (server phases).
- Tooling: `ruff` (lint + format), `pytest`. Run ruff before declaring anything done.
- Testing is targeted (D-062): run only the test files for what changed and for the modules that
  import it (find them with grep), and name each file and why. No Python changed, no tests. The
  full suite runs only when the developer asks for it, once at the end of a run, sprint or session.
- Pre-commit hook: enable once per clone with `git config core.hooksPath .githooks`. It refuses
  `.env` files and runs ruff on the staged `.py` files; CI runs the full suite on push.
- Setup: `source .venv/Scripts/activate`, then the two install commands above.
- `pytest` skips tests marked `slow` (real model weights, downloaded once). Run them with
  `pytest -m slow`.

## Git

- `git add <file>` explicitly. Never `git add .`.
- Separate concerns, separate commits. Check `git status` before committing.
- Each closed phase is tagged `phase-XX` after its gate passes.

## Definition of done for a phase

See `docs/GATES.md`. Code that runs is not done. Done means tests green, subagent reviews
passed, manual acceptance recorded in `docs/phases/PHASE_XX_REPORT.md`, `DECISIONS.md`
updated, tag created.

@AGENTS.md
