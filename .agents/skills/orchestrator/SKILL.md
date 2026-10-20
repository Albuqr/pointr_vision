---
name: orchestrator
description: Coordinate multiple agents across providers (Claude, GPT/Codex, Gemini, Kimi) through the pipeline. Assigns stages, enforces gates, routes review to a different provider, watches subscription usage and keeps .suite/stage.md current. Use when running a project end-to-end, resuming work, or splitting work among agents.
---

# Orchestrator

## Procedure
1. Run `suite stage` (creates nothing; `suite init` / `suite feature` create the board). Also read `suite.config.json`.
2. The current stage is the first one whose gate has not passed (`docs/pipeline.md`). Run `suite check <n>` for the mechanical part, then open the artifact and judge the rest. Don't trust a status line.
3. See who can take work with `suite route <skill>` (installed, below `switchAt` % of the 5-hour and weekly windows, rotating by least recently used). No provider is the default: build, review and tests may go to any of them.
4. Dispatch with the uniform runner, which gives every provider the identical envelope:
   `suite run <skill> "<task>"` (the pool picks and falls through on failure), `--provider <name>` to pin, `--provider all` to run on every eligible provider in parallel (cross-review, tests, second opinion), `--not <name>` to exclude
   - The builder and the reviewer must be different providers.
   - Parallelize independent work only (disjoint files, no blocking edge), each task in its own git worktree; never two writers in one checkout. Multi-agent teams are opt-in (~7× tokens).
   - Set a token budget or cap per task; check `suite usage` against it before dispatch and after the run. Over cap → stop and ask the human.
5. Read the run's `## RESULT` block.
   - `blocked` or `needs-human` → bring the exact question to the human.
   - `done` → run `suite check <n>`; only then record it.
6. Big, foggy efforts → **`wayfinder`**. When passing work between sessions or providers → **`handoff`**.
7. Record the result with `suite stage <n> <status> --owner <provider>`; write next action and open questions in `.suite/stage.md`.

## Never
- Skip a gate to save time.
- Let one agent edit another stage's artifact directly. Use "Change request" sections.
