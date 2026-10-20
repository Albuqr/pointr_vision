---
name: dev-model
description: Stage 3. Choose the development model with research and analysis (process, stack, architecture with deep modules, test seams, delivery metrics, agent allocation) and record each decision as an ADR. Use after the spec is signed off, or when revisiting a major technical decision.
---

# Development model

## Procedure
1. Read `spec.md`. List the architecturally significant requirements: NFRs and constraints that force decisions.
2. For each decision below, run **`research-sources`** (time-boxed), then write `docs/adr/NNNN-<title>.md` from [adr.md](adr.md) with ≥ 2 real alternatives. Write each ADR as `proposed` before implementation. ADRs are shown to help knowledge transfer, not quality (Chalmers 2023/2024); ~63% of OSS ADRs start already accepted (ICSA 2026).
   - **Process.** Default: trunk-based development, small batches, vertical slices, CI on every push. DORA survey research (correlational) associates these with higher delivery performance. Deviate only with a reason.
   - **Stack.** Prefer what the team knows and what has official long-term support. Score the options against the NFRs in a table.
   - **Architecture.** Use the **`codebase-design`** vocabulary (deep modules, seams, locality). Start with a modular monolith unless an NFR forces distribution. Add a C4 Context + Container diagram in Mermaid.
   - **Test seams.** Agree the highest seams to test at (what `tdd` will use), and which `testkit/` checks apply (`testkit/bin/run-all.sh --detect`).
   - **Delivery metrics.** DORA four keys, and how each will be measured. Measure them before and after introducing agents; change-failure rate and time-to-restore are veto metrics (DORA 2024/2025: the AI effect on stability is contested).
   - **Agent allocation.** Which provider runs which stage. The default is the whole pool rotating (`suite route`); pin a provider only with a reason. Set a token budget.
3. Run **`domain-modeling`** so `GLOSSARY.md` names every core concept.
4. Simplicity pass: for every component, ask "what breaks if we delete this?" (the deletion test). Delete what nothing needs.

## Gate
Run `suite check 3`. It verifies the mechanical items below and must PASS; you and the human judge the rest. Then `suite stage 3 done --owner <provider>`.
- Every decision has an ADR citing tier A/B sources.
- Every NFR is covered by at least one decision.
- Human approved.
