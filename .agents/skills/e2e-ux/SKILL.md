---
name: e2e-ux
description: Stage 5. Specialized browser E2E and UI/UX testing agent built on the project testkit (Playwright smoke/auth/authorization/a11y/security/responsive/performance/crawl, Lighthouse, API contract, Maestro mobile) plus Playwright MCP exploratory testing and Nielsen heuristic review. Use after a build slice is green, before review.
---

# E2E + UI/UX testing

`testkit/` is the source of truth for automated checks; this skill adds coverage mapping, exploratory testing and UX judgement.
**Prerequisite:** the app starts from one script (`startCommand`) and writes readable logs. If not, fix that first.

## Setup (once per project)
1. Copy `testkit/env.testkit.example` to `.env.testkit` and fill it with **test accounts only** (never real ones). The file is gitignored.
2. Create `testkit.config.json` at the project root to override `testkit/defaults.json` (baseUrl, startCommand, publicPages, auth roles). Validate with `bash testkit/bin/run-all.sh --validate`.
3. `cd testkit/web && npm ci && npx playwright install`.

## Procedure
1. **Coverage map.** For every `AC-*` in `spec.md`, point to the test that proves it: a testkit spec, or a new spec in `testkit/web/tests/` titled with the AC ID. Missing coverage → write the test.
2. **Run the automated checks:** `bash testkit/bin/run-all.sh` (auto-detect), or a subset such as `web lighthouse api`. Reports land in `testkit-reports/`.
3. **Exploratory pass** through the Playwright MCP (`suite sync` configures it for every provider). Walk each main flow as a first-time user at 375, 768 and 1440 px, keyboard-only once, and save screenshots to `.scratch/<feature>/e2e/`.
4. **Usability screen** against Nielsen's 10 heuristics. This is a *single-evaluator heuristic screen*, not a full heuristic evaluation. Each finding gets: heuristic, screenshot, severity 0–4 (NN/g scale), suggested fix. Reliable severity needs ≥ 3 independent evaluators or a human (NN/g); a clean pass does not show absence of problems.
5. **Accessibility.** Testkit runs axe with WCAG 2.2 AA tags. axe finds roughly 30–57% of issues depending on method (GDS audit; Deque 2021), so the gate is necessary, not sufficient. Also check by hand: focus order, visible focus, reduced motion, meaningful alt text, a screen-reader spot check.
6. **Evidence.** Attach screenshots and logs per AC to the report.
7. Write `.scratch/<feature>/e2e-report.md` from [e2e-report.md](e2e-report.md).

## Gate
Run `suite check 5`. It verifies the mechanical items below and must PASS; you and the human judge the rest. Then `suite stage 5 done --owner <provider>`.
- 100% of ACs map to a passing test.
- `run-all.sh` exits 0, i.e. zero critical or serious axe violations under testkit defaults.
- Evidence (screenshots, logs) attached for every AC.
- No open UX finding of severity ≥ 3 from the screen; a human confirms severity.
