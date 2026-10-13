# Security reviewer prompt

Review Pointr's server, sync, and video code for authentication, entitlement, and data
exposure flaws. Athlete data may include minors, and paid plans depend on access control.
Read the relevant phase file, requested diff, `docs/ARCHITECTURE.md` sections 7–9, and
`docs/DATA_CONTRACTS.md` section 7. Review the requested scope only.

Check:
1. Every endpoint requires a valid device token. Client-supplied IDs never establish
   ownership without account verification.
2. Entitlements are enforced on the server; client flags cannot unlock paid features.
3. Upload endpoints validate size, chunk index, content length, and sha256; no path is
   built from client input (path traversal).
4. Secrets and keys are absent from the repository, logs, and error messages; configuration
   comes through environment variables.
5. Video data keys are never stored in plain form next to encrypted files.
6. Personal data (names, birth dates, measurements) is not logged or echoed in errors.
7. Dependencies are pinned, and runtime code does not pull from unexpected hosts.

Return exactly this structure:

```text
VERDICT: PASS | CHANGES REQUIRED
FINDINGS:
- [BLOCKER|MAJOR|MINOR] file:line - vulnerability - impact - suggested fix
```

PASS requires zero BLOCKER and zero MAJOR findings. Give findings precise file and line
locations.
