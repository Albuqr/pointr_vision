# Repository guidance

`CLAUDE.md` is the source of truth for repository rules and workflow. Read it before
working, along with the phase and contract documents it identifies. This file makes the
essential rules available to every coding agent; it does not replace `CLAUDE.md`.

## Essential rules

- Work on one phase or part at a time. Build only its scope; put out-of-scope ideas in
  `docs/BACKLOG.md`.
- Contracts first: any format change requires a `docs/DATA_CONTRACTS.md` update, contract
  version bump, and `DECISIONS.md` entry before implementation.
- Verify third-party APIs against the installed versions and package source, not memory.
- Make no unmeasured speed, latency, or accuracy claims.
- Absence is data: log zero-detection frames, count dropped frames, and log failures as
  events. Do not silently drop data.
- Add tests with every change. Default tests must not require a camera, model weights, or
  network access; mark any exceptional requirements explicitly.
- Ask before adding dependencies not listed in the phase file.
- Privacy: never commit sessions, recordings, calibration images, or real footage.
- Git: use explicit `git add <file>` commands, never `git add .`; make separate commits
  per concern and check `git status` before committing.

## Environment

- Windows 11, Git Bash, Python 3.11 virtual environment at `.venv`.
- Activate it with `source .venv/Scripts/activate`.
- Write sessions to `C:/pointr_sessions`, outside the repository and OneDrive.


## Agent skills

### Issue tracker
Local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels
Default five roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs
Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
