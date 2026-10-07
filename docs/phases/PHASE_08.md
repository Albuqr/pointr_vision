# Phase 08: Sync agent

## Goal
Everything recorded locally reaches the server eventually, exactly once, without the user
doing anything and without affecting a live session.

## Requirements
RF15 (client side), RNF08, RNF09.

## Scope
- Outbox writes: every registration change and every closed session enqueues outbox rows in
  the same SQLite transaction as the change itself.
- Session close → split frames/tracks into parts (gzip CSV, size-bounded), one outbox row
  per part, plus a `session.upsert` row.
- `services/sync_agent`: separate process. Loop: pick due rows, send batch with
  `Idempotency-Key = outbox id`, mark sent on accept, record reason on reject, exponential
  backoff with jitter on network errors, cap on attempts → `failed` status visible in UI.
- Pull: apply registration changes since the stored cursor; advance cursor only after the
  local transaction commits.
- UI: sync status (pending, sent, failed, last success).
- Local files are not deleted in this phase.

## Out of scope
Video upload, plans.

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | Agent killed after send but before marking → resend is a no-op on the server | integration |
| A2 | Server down for a period → rows stay pending, then all arrive once it returns | integration |
| A3 | Outbox survives process restart | integration |
| A4 | Pull applies remote changes; cursor not advanced if local apply fails | integration |
| A5 | A live session runs with the agent active and the network flapping; app delay unaffected beyond noise | manual, compare with phase 03 baseline |
| A6 | Unplug network, record a session, reconnect: session appears on the server | manual |

## Gate reviewers
`code-reviewer`, `test-auditor`, `contract-guardian`, `reliability-reviewer`, `security-reviewer`.
