---
name: research-sources
description: Evidence-first research protocol. Use whenever a decision depends on facts — choosing a stack, a method, a market comparison, "what do leaders do", best practices. Produces a cited research note ranked by source trust tier.
---

# Research

Decisions in this suite rest on **human-authored, trustworthy sources**, not on model memory.

## Procedure
1. **Frame** the question as one decision: "Should we X or Y, given constraints Z?" Write it at the top of the note.
2. **Search** with the tools you have (web search, docs fetch). Run ≥ 3 independent queries.
3. **Rank** every source with the tiers in `docs/research/sources.md`:
   - **A** — standards, official docs, peer-reviewed research, primary data (ISO, W3C, IETF, vendor docs, DORA report, NN/g studies).
   - **B** — recognized practitioners with track record, reputable engineering blogs with data.
   - **C** — aggregators, SEO blogs, forum posts, AI-generated pages. **Never sole support for a decision.**
   Tier means *trustworthy source*, not *effect proven*. Also tag the **evidence type**: standard · controlled study · case study · practitioner report. Say when evidence is contested or vendor-affiliated.
4. **Cross-check:** a claim used for a decision needs one A or two independent B sources. Otherwise mark `[UNVERIFIED]`.
5. **Date-check:** note publication/fetch date. Anything older than 18 months in fast-moving areas (AI tooling, frameworks) is flagged `[STALE?]`.
6. **Synthesize** — recommendation first, then evidence, then dissent.

## Output — `.suite/research/<slug>.md`
```
# <Question>
Recommendation: <one sentence> (confidence: high|medium|low)
## Evidence
- <claim> — [Source](url) · tier A · controlled study · 2026-05
## Dissent / caveats
## Open questions
```

## Anti-patterns
- Quoting star counts or adoption numbers from aggregators as fact.
- Copying long passages (summarize; ≤ 1 short quote per note).
- Researching forever: cap at the time-box set by the requester (default 20 min of tool calls).
