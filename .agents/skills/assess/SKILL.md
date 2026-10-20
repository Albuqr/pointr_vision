---
name: assess
description: Stage 0 for an existing codebase. Analyses a repository to recover its current requirements, configuration and development model as evidence-tiered facts, ranked review lists and hypotheses for human confirmation, then hands confirmed results to requirements and dev-model. Use when the suite is applied to a project that already has code.
---

# Assess an existing project

Code shows what the system *does*, not what it *should* do or *why* (Maalej et al. 2014; LaToza et al. 2006). LLM extraction of requirements from code is not reliable without supervision (Korn et al. 2026, preprint). So: separate facts from inferences, and never promote an inference without a human.

## Procedure
1. **Facts first.** Run `suite assess`. It writes `.suite/assess/facts.md`, which is deterministic and involves no LLM. It covers the inventory, CI, docs, ADRs, config read sites, hotspots, self-admitted debt and git proxies. Exclude generated, vendored and mass-commit noise (Bird et al. 2009; Kalliamvakou et al. 2014).
2. **Configuration.** Start from the config candidates. Names and read sites are reliable (static extraction finds most options, more than the docs list: Rabkin & Katz 2011). For each option, record its meaning, valid range, default, owner and any interactions. Mark each as `inferred`; the human confirms.
3. **Structure.** Build the module dependency graph from imports/AST, not by guessing. Any grouping you call "architecture" is a hypothesis, because recovery techniques have low accuracy (Garcia et al. 2013; Lutellier et al. 2018).
4. **Risk.** Read the top hotspots and the debt comments inside them. Treat them as a review queue, not a defect verdict. No single metric wins across projects (Zimmermann et al. 2009), and churn is a known signal (Nagappan & Ball 2005). Do not publish a single debt score or count smells as risk (Sjøberg et al. 2013).
5. **Tests.** Report what is *not* covered. High coverage does not imply fault detection (Inozemtseva & Holmes 2014). If depth matters, run mutation testing on the top-risk files only (Just et al. 2014).
6. **Process.** Describe cadence, authorship concentration, branching, releases and CI from git as *git-derived proxies*, never as DORA metrics. The team confirms the real process.
7. **Requirements as candidates.** Derive candidates from tests, routes/CLI, error messages, issues and docs. Each candidate gets source files, a confidence level and the tag `inferred from code`. Keep current behaviour apart from intended behaviour. The *why* comes from people, ADRs and issue threads.
8. **Report** `.suite/assess/assessment.md` from [assessment.md](assessment.md) in three tiers: facts, ranked lists, hypotheses. Then interview the human on the hypotheses, one block at a time, with a recommended answer each (`grilling`).

## Hand-off (after confirmation)
- Confirmed requirements and the CFG table go into `.scratch/<feature>/spec.md` as the **as-is baseline**, through the `requirements` skill.
- Confirmed process and architecture become ADRs with status `accepted (recorded retroactively)`, through the `dev-model` skill.
- Gaps and debt the human wants fixed become tickets.

## Gate
Run `suite check 0`. It verifies the mechanical items below and must PASS; you and the human judge the rest. Then `suite stage 0 done --owner <provider>`.
- Every hypothesis is confirmed, corrected or explicitly deferred by a human.
- Nothing inferred reaches spec.md or an ADR unconfirmed.
