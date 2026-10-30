# Phase 00 report
Date: 2026-10-07 (automated checks and reviews). Manual sign-off: João Albuquerque
Hardware: _Latitude 3410
Intel(R) Core(TM) i7-10510U CPU @ 1.80GHz
16
Intel(R) UHD Graphics
Microsoft Windows 11 Pro_ (phase 00 has no hardware-dependent test)
Package versions (from the clean-clone venv): Python 3.11.9, numpy 2.4.6, opencv-python
5.0.0.93, jsonschema 4.26.0, pytest 9.1.1, ruff 0.16.10, setuptools 65.5.0 (build only)

## Traceability
| # | Criterion | Test | Result |
|---|---|---|---|
| A1 | `ruff check .` and `pytest` pass on a clean clone | manual: scripted clean clone (below) | Pass |
| A2 | Example `session.json`/`run.json` validate; a broken example fails | `tests/test_contracts.py` | Pass |
| A3 | Fixture script generates the three clips and OpenCV can read them | `tests/test_fixtures.py` | Pass |
| A4 | Protocols importable; a dummy satisfying each passes `isinstance` | `tests/test_interfaces.py` | Pass |

## Automated checks
In the working repo `.venv`, after the gate fixes:
- `ruff check .`: all checks passed.
- `ruff format --check .`: all files formatted.
- `pytest -q`: 114 passed.

A1, clean clone at commit `1602e71` (completion audit re-run: git clone into a temp dir, new
venv from Python 3.11.9, install exit code 0; temp dir deleted afterwards):
```bash
git clone <repo> clone && cd clone
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/ruff.exe check .            # All checks passed!
.venv/Scripts/ruff.exe format --check .   # 49 files already formatted
.venv/Scripts/pytest.exe -q               # 114 passed
.venv/Scripts/python.exe -m pytest -q     # 114 passed
```

## Manual tests
| Test                 | Result | Notes |
|----------------------|---|---|
| _none in this phase_ | | Phase 00 lists no manual hardware test; A1 above was scripted |

## Measurements
None. Phase 00 has no capture or processing, so there are no FPS, delay or drop figures.

## Reviewer outcomes
| Reviewer | Result | Findings fixed |
|---|---|---|
| `code-reviewer` | PASS after one fix round | MAJOR: `SessionWriter`/`SessionMeta` cannot carry run.json data, but the phase's decision entry had frozen them. D-008 now marks the payload types provisional, and phase 03 completes them (BACKLOG). MINOR fixed: pytest `pythonpath`; `tests/fixtures/__init__.py`; `eq=False` on ndarray dataclasses; `.gitignore` covers `*.avi`, `*.mkv`, `pointr.db*`; numpy/opencv major-version bounds; PHASE_00 pointers to D-006/D-007. MINOR to BACKLOG: `tests/` subdirs from ARCH §3; install command in CLAUDE.md |
| `test-auditor` | PASS after one fix round | MAJOR: run.json UUID/UTC/sha256/python format rules were never exercised by a failing case. Added those broken cases plus a `$defs` equality test. MINOR fixed: more broken cases (`width=0`, 3 team_ids, extra event key, `rec_dropped=-1`); a run in progress is valid; dataclass fields checked against frames.csv/tracks.csv (in order) and the schema's source and event keys; Protocol return types; moving-clip threshold headroom; A1 cell made accurate; Protocol count corrected to six plus `Frame`. MINOR to BACKLOG: nullability of dataclass fields; `RecordingInfo` field check |
| `contract-guardian` | PASS | No BLOCKER or MAJOR. MINOR fixed: frames.csv column order checked; `SourceInfo.width/height` and `SessionEvent.t_mono` made nullable to match the schema; doc sentences on when `rec_dropped`, `registration` and `ended_at` are null; `RecordingInfo` comment names `counts.rec_dropped`; "generated from" reworded. MINOR to OPEN_QUESTIONS: Q-11 (what is `t0`). MINOR to BACKLOG: drift tests do not cover types or nullability |

## Decisions taken in this phase
- D-006: contract 0.1.0 → 0.2.0. run.json gains `contract_version` and `input.kind` `stream`.
- D-007: Python 3.11.9 virtualenv; setuptools is the build backend only.
- D-008: all six §4 Protocols (plus `Frame`) in each layer's `types.py`; session/recording
  payload types provisional until phase 03.
- D-009: strict schemas with regex formats, written by hand and checked against the doc by
  tests.

## Known limitations carried forward
- `SessionMeta`/`RecordingInfo` are provisional. Phase 03 adds run metadata and counts (BACKLOG).
- `t0` is not defined in the contract (Q-11, needed by phase 03).
- `source_open_failed` (phase 01) is not yet a contract event kind (BACKLOG).
- No MOV fixture yet. Phase 04 needs one (BACKLOG).
- Setup command `pip install -e ".[dev]"` should be added to CLAUDE.md "Environment" by the
  developer.