---
name: docs
description: Stage 7. Documentation and release. Diátaxis docs (tutorial, how-to, reference, explanation), README, CHANGELOG, PR description and a retro that improves the agent environment. Use at release, or when docs drift from behaviour.
---

# Documentation, release & retro

## Procedure
1. Inventory the docs and map each page to one Diátaxis quadrant (a widely used organising heuristic, not empirically validated). Split pages that mix quadrants.
2. **README** fits one screen to first success: what it is, install, run, test, where the docs live.
3. **Tutorial** (one guaranteed happy path) · **How-to guides** (tasks) · **Reference** (generated where possible) · **Explanation** (link the ADRs instead of repeating them).
4. Anything agents will read (AGENTS.md, skills, docs/agents/) follows **`writing-for-agents`**.
5. **CHANGELOG.md** uses Keep a Changelog with SemVer. Shape the PR with **`pr`**.
6. Close with **`retro`**: environment fixes ordered by severity. Put deferred ideas in `docs/expansions.md`.

## Gate (cold-start test, the suite's own acceptance check)
A fresh agent with no context, given only the README, can install, run and test the project. Record the attempt in the release notes.
