# Repository guidance

`CLAUDE.md` is the source of truth for repository rules and workflow. Read it before
working, along with the phase and contract documents it identifies. This file makes the
essential rules available to every coding agent; it does not replace `CLAUDE.md`.

## Essential rules

- Work on one phase or part at a time. Build only its scope; put out-of-scope ideas in
  `docs/BACKLOG.md`.
- Contracts first: any format change requires a `docs/DATA_CONTRACTS.md` update, contract
  version bump, and `DECISIONS.md` entry before implementation.
- Verify third-party APIs against the installed versions and package source, not memory.
- Make no unmeasured speed, latency, or accuracy claims.
- Absence is data: log zero-detection frames, count dropped frames, and log failures as
  events. Do not silently drop data.
- Add tests with every change. Default tests must not require a camera, model weights, or
  network access; mark any exceptional requirements explicitly.
- Ask before adding dependencies not listed in the phase file.
- Privacy: never commit sessions, recordings, calibration images, or real footage.
- Git: use explicit `git add <file>` commands, never `git add .`; make separate commits
  per concern and check `git status` before committing.

## Environment

- Windows 11, Git Bash, Python 3.11 virtual environment at `.venv`.
- Activate it with `source .venv/Scripts/activate`.
- Write sessions to `C:/pointr_sessions`, outside the repository and OneDrive.


## AI Production Suite

Canonical instructions for **every** agent (Claude Code, Codex/GPT, Gemini CLI, Kimi CLI, or any other).
Provider-specific files (`CLAUDE.md`, `.gemini/settings.json`) only point here.

## Prime directive: simplify, then add lightness
- The simplest thing that satisfies the requirement wins almost every time.
- Before adding anything (dependency, abstraction, agent, step), name the requirement it serves. No requirement → don't add it.
- Prefer deleting over adding. Prefer boring, well-documented technology.

## How work flows
Stages, gates and artifacts are in `docs/pipeline.md`. Each stage skill orchestrates Matt Pocock's skills (vendored in `.agents/skills/`, MIT) and adds a gate.
Never skip a gate. If a gate fails, go back one stage. Gates are process controls, not proof of quality; humans are mandatory at the gates of stages 0, 1, 2, 3 and 6.


| Stage | Suite skill | Chains | Artifact |
|---|---|---|---|
| 0 Assess (existing code only) | `assess` | `suite assess`, `grilling` | `.suite/assess/assessment.md` |
| 1 Define — new product | `deliberate` | (self-contained protocol) | `.scratch/<feature>/decision-record.md` |
| 1 Define — feature in an existing product | `ideation` | `grill-me` / `grilling`, `prototype` | `.scratch/<feature>/brief.md` |
| 2 Requirements & config | `requirements` | `grill-with-docs`, `to-spec` | `.scratch/<feature>/spec.md` |
| 3 Development model | `dev-model` | `domain-modeling`, `codebase-design`, `research-sources` | `docs/adr/*.md`, `GLOSSARY.md` |
| 4 Build | `build` | `to-tickets`, `implement` / `implement-spec`, `tdd`, `diagnosing-bugs` | code + tests |
| 5 E2E / UI-UX | `e2e-ux` | `testkit/`, Playwright MCP | `.scratch/<feature>/e2e-report.md` |
| 6 Review | `review` | `code-review` + security/simplicity passes | `.scratch/<feature>/review.md` |
| 7 Docs & release | `docs` | `writing-for-agents`, `pr`, `retro` | `docs/`, `CHANGELOG.md` |
| Media (optional) | `media-kit` | HyperFrames / Remotion | `.suite/media/` |
| Coordination | `orchestrator` | `handoff`, `wayfinder` | `.suite/stage.md` |

## Rules every agent follows (same behaviour on every provider)
1. **Read before you write.** Load the stage `SKILL.md` and the previous stage's artifact first.
2. **Cite or flag.** Any factual claim used for a decision needs a tier A–B source (`docs/research/sources.md`) or is marked `[UNVERIFIED]`.
3. **Facts are yours, decisions are the human's.** Look facts up instead of asking; ask about decisions, with a recommended answer.
4. **Use the CLI for state, not prose.** `suite feature`, `suite stage`, `suite check` own the stage board and the mechanical gate checks; never hand-edit the status table. Write next action and open questions in `.suite/stage.md` before ending a session.
9. **Code before AI.** If a step is deterministic (counting, parsing, checking, formatting, running tools), use or add a `suite` command instead of doing it with the model.
5. **Stay in your lane.** One agent = one stage at a time. Don't rewrite another stage's artifact; add a "Change request" section.
6. **Report honestly.** Failing tests, skipped steps, unverified claims are stated plainly.
7. **No secrets in artifacts.** Keys live in env vars or `.env` / `.env.testkit` (gitignored).
8. **Contested evidence is stated as contested.** Never present a heuristic as established fact; say when evidence is contested, weak or unmeasured.

## Output contract
Every run ends with this block, so the runner, dashboard and humans can parse it uniformly:

```
## RESULT
status: done | blocked | needs-human
artifact: <path>
next: <stage or action>
open_questions: <n>
```

## Agent skills

### Issue tracker
Local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels
Default five roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs
Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
