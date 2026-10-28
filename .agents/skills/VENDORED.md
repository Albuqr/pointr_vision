# Vendored skills

From [mattpocock/skills](https://github.com/mattpocock/skills) at commit `59db609` (MIT, see `LICENSE.mattpocock-skills`).
All 27 skills the upstream plugin publishes (`.claude-plugin/plugin.json`), copied unmodified.

The suite's stage skills call: code-review, codebase-design, diagnosing-bugs, domain-modeling, grill-me,
grill-with-docs, grilling, handoff, implement, implement-spec, pr, prototype, research (used by wayfinder), retro, tdd,
to-spec, to-tickets, wayfinder, writing-for-agents.

Also vendored for direct use (restored 2026-10-28): ask-matt, improve-codebase-architecture, setup-matt-pocock-skills,
teach, to-questionnaire, triage, wait-what, wizard. Note: the suite pre-configures `docs/agents/`, which
setup-matt-pocock-skills also writes; review its diff before keeping it.

Upstream's `in-progress/` and `misc/` skills are not published by the plugin and are not vendored.

## Exposing them to Claude Code

Claude Code loads skills from `.claude/skills/` (gitignored). Link each skill there as a directory junction, from
PowerShell at the repo root:

```powershell
Get-ChildItem .agents\skills -Directory | ForEach-Object {
  $link = ".claude\skills\$($_.Name)"
  if (-not (Test-Path $link)) { New-Item -ItemType Junction -Path $link -Target $_.FullName | Out-Null }
}
```

This links every directory in `.agents/skills/`, including the suite stage skills.
