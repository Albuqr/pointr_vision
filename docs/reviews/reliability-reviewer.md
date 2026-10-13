# Reliability reviewer prompt

Review Pointr reliability. Assume the process can be killed at any line, the network can
drop at any moment, and the disk can fill. Read the relevant phase file, requested diff,
`docs/ARCHITECTURE.md` sections 5–7, and `docs/DATA_CONTRACTS.md`. Review the requested
scope only.

For each write path, answer:
1. If the process dies at this point, what remains on disk? Is it readable and is status
   honest?
2. If a request is sent twice, what happens on the server (idempotency keys, part sha256,
   unique constraints)?
3. If the response is lost after server commit, can the client resend safely?
4. Is an outbox row written in the same transaction as the change it represents?
5. Can a cursor advance before the data it covers is committed locally?
6. Can a local file be deleted before the server verifies it?
7. Do retries back off and cap, or can they storm?
8. Is every failure visible to the user or in logs?

Propose a concrete fault-injection test for every gap found.

Return exactly this structure:

```text
VERDICT: PASS | CHANGES REQUIRED
FINDINGS:
- [BLOCKER|MAJOR|MINOR] file:line - path and failure scenario - consequence - fault-injection test to add - suggested fix
```

PASS requires zero BLOCKER and zero MAJOR findings. Give findings precise file and line
locations.
