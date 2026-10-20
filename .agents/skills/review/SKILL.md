---
name: review
description: Stage 6. Full review with re-passes until clean. Runs code-review (Standards + Spec axes) and adds security (OWASP ASVS + testkit security), simplicity and test-quality passes. Prefer a different provider than the builder. Use before merging and before release.
---

# Full review & re-passes

**Purpose:** defects, knowledge transfer and maintainability (Bacchelli & Bird 2013; Sadowski et al. 2018). Zero blockers does not prove zero bugs.

**Independent reviewer (preferred):** use a different model or a fresh context, e.g. `suite run review --provider codex`. Rationale: fewer correlated errors and less LLM self-preference bias (arXiv:2410.21819). The gain in defect detection is unmeasured for code review.
**Anti-anchoring:** read the diff and spec first; read the builder's summary only after your first pass.
**Humans:** the AI never approves alone. A human signs off, and is mandatory on high-risk changes (auth, payments, data, security, migrations).

## Passes
1. **`code-review`** against the spec: two parallel axes, **Standards** (repo rules plus Fowler smells) and **Spec** (missing, partial, scope creep). Keep its output as-is.
2. **Security.** Check OWASP ASVS L1: authn/authz, input validation, secrets, injection. Include the output of `bash testkit/bin/run-all.sh security` (dependency audit, SAST, headers).
3. **Simplicity.** *Simplify, then add lightness*: dead code, needless abstraction, dependencies that could be 10 lines. Apply the deletion test.
4. **Tests.** Do they assert behaviour through public interfaces? Would they catch a regression? Look for tautologies and flaky waits.
5. **Traceability.** Every FR has code and a test; no code exists without a requirement.

Every finding needs a concrete failure scenario (input → wrong result) and a severity. **Verify before reporting:** re-check each finding in a second pass or sub-agent, drop what does not reproduce, and rank by severity.
- **blocker**: wrong behaviour, security hole, data loss.
- **major**: likely bug or real maintenance debt.
- **minor**: optional.

## Re-pass loop
Fix, then re-run only the passes that touch changed code. Repeat until there are zero blockers. After 3 loops, escalate to the human.
Write `.scratch/<feature>/review.md` from [review.md](review.md).

## Gate
Run `suite check 6`. It verifies the mechanical items below and must PASS; you and the human judge the rest. Then `suite stage 6 done --owner <provider>`.
Zero blockers; every major fixed or accepted in writing by the human; human sign-off recorded.
