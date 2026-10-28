---
name: build
description: Stage 4. Slice the spec into tracer-bullet tickets and implement them with TDD at agreed seams, traceable to requirement IDs, ending each ticket with code-review. Use during the build stage or for any feature or bugfix.
---

# Build

## Procedure
1. Run **`to-tickets`** on `spec.md`. The tickets land as GitHub issues on `Albuqr/pointr_vision` (see `docs/agents/issue-tracker.md`): vertical slices with blocking edges, refactors first. Every ticket names the FR/AC IDs it delivers.
2. Implement:
   - Small or single-session work → **`implement`** per ticket. Clear context between tickets.
   - Many unblocked tickets → **`implement-spec`**, which runs parallel sub-agents on one integration branch.
   - Either way the loop is **`tdd`**: red → green at the agreed seams. Test names carry the AC ID, e.g. `test("AC-003.1 rejects expired token")`. TDD means small, uniform, test-backed steps (Fucci et al. 2016), not a quality guarantee; test-first order alone is not shown to matter. Keep red → green as verification: the test must fail first and must not mirror the implementation.
   - Parallelize only independent tickets, each in its own git worktree. Multi-agent teams are opt-in (~7× tokens).
3. Bugs → **`diagnosing-bugs`**: build a failing feedback loop first, finish with a regression test.
4. Before each commit, run the fast local checks: `bash testkit/bin/run-all.sh node python security`. The git pre-commit hook runs the same.
5. Commit one ticket per commit, message `feat(FR-003): …`. Update the ticket `Status:`.

## Rules
- Follow the ADRs. To deviate, propose a new ADR; don't diverge silently.
- Justify any new dependency in one line in the commit body.
- Read config from env vars per `CFG-*`. Never hardcode secrets.

## Gate
Run `suite check 4`. It verifies the mechanical items below and must PASS; you and the human judge the rest. Then `suite stage 4 done --owner <provider>`.
- Unit, lint and type checks pass locally and in CI.
- Every implemented FR has ≥ 1 test referencing its ID.
