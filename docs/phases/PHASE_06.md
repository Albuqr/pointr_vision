# Phase 06: Local store and registrations

## Goal
Register players, teams and sessions locally, and link each session folder to its
registration, through a local web UI.

## Requirements
RF12, RF13, RF14, RN06, RN07.

## Scope
- `store/`: SQLite schema from `DATA_CONTRACTS.md` section 6, with migrations (a numbered
  SQL file list is enough). UUIDs generated on the device. `updated_at` and `device_id` on
  every write.
- Repositories: `TeamRepo`, `PlayerRepo`, `SessionRepo` with create / update / get / list /
  soft delete.
- Rules: shirt number unique per team (RN06); a session has one or two teams (RN07);
  duration computed, never stored; session date set automatically at start.
- Local web UI: FastAPI on localhost serving a small frontend. Screens: players (RF12),
  teams (RF13), sessions list and detail with report (RF14, RF10), start/stop session.
- Existing session folders from phases 03-05 can be imported into the index.

## Out of scope
Sync, outbox, accounts, plans.

## Open before starting
Q-03 (frontend stack) and Q-07 (which personal fields are kept).

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | CRUD for teams and players works through the repositories | unit |
| A2 | Duplicate shirt number in the same team is rejected; same number in another team accepted | unit |
| A3 | Session with 0 or 3 teams rejected; 1 and 2 accepted | unit |
| A4 | Duration equals end minus start; no duration column exists | unit |
| A5 | API endpoints return the right status codes for valid and invalid input | integration |
| A6 | Register a team and two players in the UI, run a session, see it in the list with its report | manual |

## Gate reviewers
`code-reviewer`, `test-auditor`, `contract-guardian`.
