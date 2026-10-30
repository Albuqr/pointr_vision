# Architecture deepening: running several agents at once

Three coding agents work at the same time (Claude Code, Codex, Antigravity). They do not share
memory or chat, so this file is the only coordination they get. Every agent reads it, and
`brief.md`, before starting a ticket, and again before opening a PR.

Why it exists: on 2026-10-29 four branches that were in flight at once (R2a 05/06/07/08, B13) all
conflicted on the same files. Those files were the contract-version fan-out (`contracts/*`,
`tests/fixtures/contracts/*`, `contract.py`, the copied calibration schema), the shared docs
(`DECISIONS.md`, `BACKLOG.md`, `ARCHITECTURE.md`, `DATA_CONTRACTS.md`) and `group_runner.py` /
`main.py`. A separate CRLF churn commit (36217e3, then b471907) rewrote about 2,000 lines.

---

## 1. Rules for every agent, whatever the provider

1. **Your own worktree, never the main checkout.** From the main clone:
   `git worktree add ../pointr-<lane> -b <branch> origin/main`. Work and run tests only there. Two
   agents never share a working directory.
   - **The shared `.venv` is fine.** pytest has `pythonpath = ["."]`, so it imports the worktree's code
     first. Activate it with `source ../pointr_vision/.venv/Scripts/activate`.
   - **Never run `pip install -e .` from a worktree.** That would point the shared install at your
     worktree.
2. **Claim before you start.** Assign yourself the GitHub issue, add the label `in-progress`, and comment
   `claimed by <claude|codex|antigravity>: branch <name>, worktree <path>`. If the issue is already
   claimed, or has open blockers (`gh api repos/Albuqr/pointr_vision/issues/<n> --jq
   .issue_dependencies_summary.blocked_by` is greater than 0), pick another one.
3. **Stay in your file list.** Each ticket lists the files it **owns** and the files it may **touch only
   in named functions**. If you need any other file, stop. Comment on the issue with the file and the
   reason, and wait. Do not "just fix" something in another lane's file.
4. **Shared docs are append-only, at reserved IDs.**
   - **`DECISIONS.md`:** add only your reserved `D-0xx` (section 3), at the end of the file. When rebasing,
     keep both sides of the conflict, in ID order.
   - **`docs/BACKLOG.md`:** do not edit. Put backlog lines in your PR body under `Backlog:`. The owner
     merges them.
   - **`ARCHITECTURE.md` / `DATA_CONTRACTS.md`:** edit only the sections your ticket names.
   - **`GLOSSARY.md`:** only the ticket that says so.
5. **Contract version.**
   - **Before ticket T1 merges, nobody else bumps it.** T1 is the only ticket allowed to.
   - **After T1, a bump touches 3 files.** Take the next free version when you rebase onto `main`, just
     before merge. Do not take it when you start.
6. **Line endings.** T0 must be merged before any other branch is cut. After T0, `.gitattributes` forces
   LF. If `git diff --stat` shows a whole file changed when you edited a few lines, stop and fix your
   editor setting. Do not commit it.
7. **Rebase, don't merge `main` in.** Before opening a PR, and again before merging:
   `git fetch && git rebase origin/main`. Re-run your targeted tests after every rebase.
8. **Targeted tests only (D-062).** Run the test files for what you changed plus the modules that import
   it (find them with grep), and name each in the PR. Run ruff on changed `.py` files. The full suite
   runs only when the owner asks.
9. **Merge order is fixed (section 4).** A PR whose blockers are not merged stays a draft.
10. **Never commit sessions, recordings or footage (rule 9). Never `git add .`.**
11. **Done.** The PR is merged. Then delete the branch locally and remotely, remove the worktree
    (`git worktree remove ../pointr-<lane>`), close the issue with a comment, and remove `in-progress`.

### Models per provider (owner, 2026-10-30)

| Provider | Models allowed | How |
|---|---|---|
| **Claude Code** | **Opus as overseer, Sonnet for subagents** | The main session runs on Opus. It claims the ticket, reads the brief, splits the work, and reviews and merges what the subagents return. Implementation, test-writing and exploration go to subagents spawned with `model: sonnet`. The Opus overseer does not write the bulk of the code itself. It owns the decisions, the file-list check (section 1, rule 3), the PR checklist (section 5) and the final review of each subagent's diff. |
| **Codex** | **6.1 sol only** | Start every Codex session on that model, and use no other model for any part of the ticket. |
| **Antigravity** | **3.8 flash only** | Start every Antigravity session on that model, and use no other model for any part of the ticket. |

These model names are the ones the owner gave. Each agent checks it is running on its allowed model
before claiming a ticket, and names that model in the claim comment, for example `claimed by codex
(6.1 sol): branch …`.

### Per provider

- **Claude Code** reads `CLAUDE.md` (which includes `AGENTS.md`) automatically.
- **Codex** reads `AGENTS.md` automatically. `AGENTS.md` points to `CLAUDE.md`, so tell it to read both.
- **Antigravity**: do not rely on it picking up repo rule files. Paste the kickoff prompt below.
- **All three: start with the same prompt:**

```
Read CLAUDE.md, AGENTS.md, .scratch/architecture-deepening/coordination.md and
.scratch/architecture-deepening/brief.md. You are the <claude|codex|antigravity> agent.
Your ticket is #<n>. Follow coordination.md section 1 exactly: create your own worktree,
claim the issue, stay inside the ticket's file list, use only your reserved D-number.
Write a failing test first for each behaviour change. Stop and comment on the issue if you
need a file outside your list or a decision the ticket does not settle.
```

---

## 2. Lanes and file ownership

A lane is a set of files that only one agent edits at a time. Tickets in the same lane run in sequence.
Tickets in different lanes can run in parallel.

| Lane | Owns |
|---|---|
| **K (contracts)** | `.gitattributes`, `.git-blame-ignore-revs`, `contracts/` → `services/edge/contracts/`, `tests/fixtures/contracts/*`, `services/edge/contract.py`, `services/edge/calibration/calibration.schema.json`, `services/edge/calibration/document.py` (the `ACCEPTED_VERSIONS` and validation part), `pyproject.toml` (package-data only), `tests/test_contracts*.py`, `tests/edge/test_contract_version.py`, `tests/edge/test_calibration_schema.py`, `.claude/agents/contract-guardian.md` |
| **S (Studio and session folder)** | `services/edge/session/folder.py` (new), `services/edge/child_protocol.py` (new), `services/app/server.py` (all functions **except** `calibration_fit`), `services/edge/launcher_impl.py`, `services/edge/replay/resolve.py`, `services/edge/reports/cli.py`, `services/edge/reports/build.py` (reading only), `services/edge/score.py`, `services/app/camera_log.py`, `tests/app/*` (except calibration tests), `tests/edge/test_launcher.py`, `tests/edge/fake_camera.py` |
| **E (edge run)** | `services/edge/main.py`, `services/edge/group_main.py`, `services/edge/group_runner.py`, `services/edge/replay/group.py`, `services/edge/camera_pipeline.py`, `services/edge/session/types.py`, `services/edge/session/writer.py`, `services/edge/run/` (new), `tests/edge/fakes.py`, `tests/edge/test_session.py`, `test_cli.py`, `test_group_*.py`, `test_camera_pipeline.py`, `test_ready_times.py`, `test_replay.py`, `test_preview_disconnect.py`, `test_calibration_size.py` |
| **C (calibration)** | `services/edge/calibration/intake.py` (new), `tests/edge/test_calibration_intake.py` (new), `services/app/server.py::calibration_fit` only, `services/app/calibrations.py`, `tests/app/test_calibration_*.py` |

Overlaps that are allowed, each in named functions only:

- **`replay/group.py`.** S's BS and T2 touch only the discovery loop in `resolve_group` (lines 104-107, B1). E owns the rest of the file, including BE's B5 fix.
- **`server.py`.** C owns only `calibration_fit`. S owns everything else.
- **`calibration/document.py`.**
  - K owns `ACCEPTED_VERSIONS` and the schema loading.
  - C removes `run_calibration` (T8, after T1 has merged).

Pattern used throughout: **build the new deep module in a new file, in parallel, then switch callers
over in the lane that owns them, in sequence.** New files cannot conflict.

---

## 3. Tickets, reservations and blockers

D-numbers are reserved now (the last used is D-062). A ticket that ends up not needing its number
leaves a gap; write `D-0xx: not used` in its PR. Contract versions after 0.22.0 are taken at merge
time (rule 5).

**Scope (owner, 2026-10-30).** The bug tickets (BK, BS, BE) are **Phase 03**: small fixes, each with a
failing test first, landing before the refactor tickets in their lane. Their tests become regression
tests the refactors must keep green. T1–T12 are the **R2a follow-up**: the PHASES.md entry and D-063
come with T0.

| Ticket | Lane | Candidate | Reserved | Blocked by | Size |
|---|---|---|---|---|---|
| **T0** LF normalisation (`.gitattributes`, one renormalise commit, `.git-blame-ignore-revs`) + the PHASES.md "R2a follow-up" entry and **D-063** (scope) | K | brief C3 | **D-063** | none | XS |
| **BK** *(Phase 03)* B6: add 0.14.0–0.18.0 to `ACCEPTED_VERSIONS`, with a regression test | K | bug | none | T0 | XS |
| **BS** *(Phase 03)* B1, B7, B8, B9 in their own readers; B2 and B10 on the Studio side only: an `error:` after `session:` is not a start failure; match failure-kind words exactly | S | bugs | none | T0 | S |
| **BE** *(Phase 03)* B3 (single-camera model-load failure also prints `error:`), B4 (hold Ctrl+C during group setup), B5 (`check_homography` on the replay block → event) | E | bugs | none | T0 | S |
| **T1** `contract.py` owns the version; schemas packaged as one copy, no version inside them (decision 2); calibration format table | K | C3 | **0.22.0, D-064** | BK | M |
| **T2** Session-folder reader; the BS readers switch to it | S | C4a | D-065 | BS | M |
| **T3** `RunSettings`, `run_meta(model_loaded)`, test fakes moved to `fakes.py` | E | C6 | none | BE | S |
| **T4** Run characterisation table test (new test file only; drift marked xfail) | E* | C2 step 1 | none | BE | S |
| **T5** `calibration/intake.py`: `take_calibration`, `Calibration`, `build_document` + tests (new files; no callers switched yet) | C | C1 | none | T1 | M |
| **T6** `child_protocol.py` + launcher parser + `server.py` typed failure kinds; DATA_CONTRACTS §16 (decisions 14+15); GLOSSARY terms | S | C4b | D-066, next version | T1, T2 | M |
| **T7** Narrow camera pipeline interface, `LiveInput`/`ReplayInput`, explicit writer Protocol | E | C5 | D-067 | T3, T4 | M |
| **T8** Switch callers to intake (main, group_runner, replay/group, pipeline, Studio `calibration_fit`); single-camera refusal non-fatal (decision 6); refusal recorded as a failed check (decision 8); single replay uses the live run's calibration (decision 9); delete the converters | E | C1 | D-068, next version | T5, T7 | M |
| **T9** `run/perception.py` + `run/stop.py` (moves the BE fixes into one place) | E | C2 steps 2–4 | D-069 | T8 | M |
| **T10** Emitters switched to `child_protocol.emit` (main, group_main, replay, pipeline, group_runner) | E | C4b | none | T6, T9 | S |
| **T11** Group-of-one mode, `ReplayNewSession`, `execute(plan)`; route replay and group_main through it; benchmark before and after | E | C2 steps 5–6 | D-070 | T10 | L |
| **T12** Route `main` through `execute`; delete `main.run` and the re-exports | E | C2 step 7 | none | T11 | M |

\* T4 adds only a new test file, so it can run beside T3 even though both are lane E. Use a different
agent from T3's if you like.

---

## 4. Waves: who does what, in which order

The owner assigns providers per wave. Suggested assignment below.

| Wave | Claude | Codex | Antigravity |
|---|---|---|---|
| 0 | **T0** (minutes; merge before anything else is branched) | n/a | n/a |
| 1a *(Phase 03 bugs)* | **BK** then start **T1** | **BS** | **BE** |
| 1b | **T1** contracts | **T2** session reader | **T3** then **T4** |
| 2 | **T5** intake module | **T6** protocol (after T1, T2) | **T7** pipeline |
| 3 | **T8** switch to intake | n/a (or review T8) | n/a (or review) |
| 4 | **T9** | **T10** (after T9) | n/a |
| 5 | **T11** then **T12** (one agent; this is the most delicate part) | review | review |

Merge order within a wave:
- **Wave 1a:** BK, BS, BE in any order (their files don't overlap).
- **Wave 1b:** T1 first, then T2, then T3 and T4.
- **Wave 2:** T5, then T7, then T6.

Lane E from wave 3 on is a single chain. Keeping it on one agent removes the worst conflict surface
(`main.py`, `group_runner.py`). The other two agents review, or take bug and backlog tickets outside
lanes K, S, E and C.

Spare lane for idle agents: anything that touches none of the files in section 2, such as Studio UI
work in `services/app/ui/src/*`. Rebuilding `ui/dist` conflicts, so only one agent at a time builds `dist`.

---

## 5. Before each PR

- [ ] Rebased on `origin/main`; targeted tests re-run after the rebase, listed in the PR body.
- [ ] `git diff --stat origin/main` shows only files from the ticket's list.
- [ ] No whole-file line-ending churn.
- [ ] Only my reserved D-number is in `DECISIONS.md`; backlog lines are in the PR body.
- [ ] Contract version: none, or the next free one taken at this rebase (after T1 only).
- [ ] Ruff clean on the changed `.py` files.
- [ ] The PR body links the issue and `.scratch/architecture-deepening/brief.md#<candidate>`.
