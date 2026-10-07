# Phase 07: Cloud API

## Goal
A server that accepts sync batches idempotently and assigns a global order to changes.

## Requirements
RF15 (server side), RNF08.

## Scope
- `services/api`: FastAPI + PostgreSQL, Docker Compose (api, db). Migrations with Alembic.
- Accounts and devices: register/login, device token issue, `device_id` per device.
- `POST /v1/sync/batches` with `Idempotency-Key`: stores processed keys with the response;
  a repeat returns the stored response.
- Registrations: LWW by `updated_at`, tie by `device_id`; every accepted change gets
  `server_seq` (Postgres sequence).
- Session data parts: append-only by `(session_id, run_id, part_no)`; same sha256 = no-op,
  different sha256 = rejected.
- `GET /v1/sync/changes?since=` paginated.
- `GET /v1/entitlements` returning a fixed `basic` plan for now.
- Deployed to the VPS behind HTTPS.

## Out of scope
Video endpoints, real plans, payment, analytics.

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | Same batch sent twice → identical response, no duplicate rows | integration (testcontainers or compose) |
| A2 | Two devices edit the same player; newer `updated_at` wins regardless of arrival order | integration |
| A3 | `changes?since=n` returns exactly the changes after n, in order | integration |
| A4 | Part with same key and different sha256 rejected | integration |
| A5 | Requests without a valid token rejected; a device cannot read another account's data | integration |
| A6 | Deployed instance reachable over HTTPS, health endpoint OK | manual |

## Gate reviewers
`code-reviewer`, `test-auditor`, `contract-guardian`, `reliability-reviewer`, `security-reviewer`.
