# Phase gates

A phase is closed only when every step below passes, in order. A failed step sends the
phase back to implementation; the next phase does not start.

## Step 1: implementation complete

Every deliverable in `docs/phases/PHASE_XX.md` exists. Every acceptance criterion has an
entry in the phase's traceability table: the test that covers it, or `manual`.

## Step 2: automated checks

```bash
ruff check . && ruff format --check .
pytest -q
```

- All green. No skipped tests without a written reason in the test.
- Tests from earlier phases still pass. Each layer is an increment; nothing earlier breaks.
- Phase-specific checks listed in the phase file (e.g. the 10-minute soak in phase 03).

## Step 3: subagent reviews

Run each reviewer as a subagent with a fresh context, so the work is not graded by the
context that produced it. Definitions are in `.claude/agents/`.

| Reviewer | Runs in | Looks for |
|---|---|---|
| `code-reviewer` | every phase | correctness, interface adherence, error paths, shutdown, hidden coupling |
| `test-auditor` | every phase | each acceptance criterion actually tested; tests that pass for the wrong reason; mocks hiding the behaviour under test |
| `contract-guardian` | any phase touching files, DB or API | output matches `DATA_CONTRACTS.md`; version bumped; no silent format change |
| `reliability-reviewer` | 03, 07, 08, 09 | crash/partial-data behaviour, idempotency, retries, resume, data loss paths |
| `security-reviewer` | 07, 08, 09 | auth, secrets, entitlement bypass, path traversal, upload validation, PII exposure |

Prompt to start a review in Claude Code:

> Use the `<reviewer>` subagent to review phase XX. Scope: the diff since tag `phase-<XX-1>`,
> `docs/phases/PHASE_XX.md`, and the docs it references. Return PASS or CHANGES REQUIRED.

Each reviewer returns findings tagged **BLOCKER**, **MAJOR** or **MINOR**:
- BLOCKER and MAJOR must be fixed, then the same reviewer runs again on the fix.
- MINOR goes to `docs/BACKLOG.md` or is fixed, the developer decides.

## Step 4: manual acceptance

The developer runs the manual tests in the phase file on the real hardware (notebook +
phone) and fills `docs/phases/PHASE_XX_REPORT.md`:

```markdown
# Phase XX report
Date:
Hardware: notebook model, CPU/GPU, phone model, connection (USB/Wi-Fi), camera app + version
Package versions:
## Manual tests
| Test | Result | Notes |
## Measurements
(FPS, app delay p50/p95, drops, anything the phase asks for, with the run_id they came from)
## Reviewer outcomes
| Reviewer | Result | Findings fixed |
## Known limitations carried forward
```

## Step 5: close

- `DECISIONS.md` updated with every decision taken during the phase.
- `docs/PHASES.md` current-phase pointer moved forward.
- `git tag phase-XX`.

## Scope creep rule

If a reviewer or the developer finds something useful outside the phase scope, it goes to
`docs/BACKLOG.md`. It is not built inside the current gate.
