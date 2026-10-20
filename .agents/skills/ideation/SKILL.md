---
name: ideation
description: Stage 1 for a FEATURE in an existing product. Turns a raw idea (notes, voice transcript, chat dump, images) into a one-page brief with problem, user, outcome, non-goals and the simplest viable version, using the grilling interview. For a brand-new product use deliberate; for an existing codebase run assess first.
---

# Ideation (feature brief)

New product → use **`deliberate`** instead. Unfamiliar existing codebase → run **`assess`** first.

## Procedure
1. Run `suite feature <slug>` and drop raw inputs in `.scratch/<feature-slug>/inputs/` (notes, images, links). The dashboard shows them.
2. Run the **`grilling`** skill (use `grill-me` if there is no repo yet) on the idea. Walk the design tree from the top: problem → who has it → how they cope today → observable outcome → non-goals → constraints.
3. Separate **problem** from **solution**: the problem statement must not name a technology.
4. Propose three versions — **Ponytail** (hours), **Lean** (days), **Full** (weeks). Recommend the smallest that proves the outcome. *Simplify, then add lightness.*
5. If one question can only be answered by running code, detour through **`prototype`** (throwaway), then come back.
6. Name the riskiest assumption and the cheapest test for it.
7. Write `.scratch/<feature-slug>/brief.md` from [brief.md](brief.md).

Method note: the three sizes and the gate are practice heuristics, not measured methods.

## Gate
Run `suite check 1`. It verifies the mechanical items below and must PASS; you and the human judge the rest. Then `suite stage 1 done --owner <provider>`.
- Problem ≤ 3 sentences, no solution words.
- ≥ 1 non-goal.
- Human approved the chosen version (record `approved_by` in the brief).
