---
name: requirements
description: Stage 2. Turns a decision record (new product), a brief (feature) or a confirmed assessment (existing code) into a validated spec using a structured, prompt-guided interview, a completeness check, requirements tied to hypotheses, concrete acceptance examples, measurable quality requirements and an evidence-based configuration register. Methods are chosen from verified research (.suite/research/re-elicitation-evidence.md, configuration-evidence.md). Use after stage 1 or 0 and whenever scope changes.
---

# Requirements & configuration

Tags: **[V]** verified at abstract level · **[weak]** thin or contested evidence · **[H]** suite heuristic. Most experimental evidence in this area comes from students and small tasks, so treat the rules as best available, not proven.

## Inputs
- New product: `.scratch/<f>/decision-record.md`. Its hypotheses and scope are the starting point.
- Feature: `.scratch/<f>/brief.md`.
- Existing code: the confirmed `.suite/assess/assessment.md`, which becomes the **as-is** baseline. Keep `as-is` and `to-be` requirements apart.

Missing or unapproved input → stop, `status: blocked`. Scale depth to the change: a small change gets a short spec [H].

## 1. Elicit with a structured, prompt-guided interview
- Use a scripted interview, not free chat. Structured interviews are among the most effective elicitation techniques; the original studies were not replicated [V Davis et al. 2006 SLR].
- Prompt by category, one block at a time: roles, tasks, data, rules, exceptions and failure cases, constraints (cost, licence, deadline), quality, current workaround [V Browne & Rogich 2001, weak: single experiment]. Use `grill-with-docs` for the question rounds, each question with a recommended answer.
- After each block, play back a summary and hunt for vague terms in the transcript. Ambiguity hides misunderstandings and tacit knowledge [V Ferrari et al. 2016; 2017, preliminary].
- Check yourself against common interviewer mistakes: wording, omitted questions, order, planning [V Bano et al. 2019].
- Don't rely on "experience" or domain knowledge to fill gaps. Their effect is small and can cut both ways [V Aranda et al. 2016; 2023; Hadar et al. 2014].

## 2. Completeness check (mandatory)
Ask "what is missing?" and "who else should have a say?" before writing. The most frequent problems in practice are incomplete or hidden requirements, communication flaws, underspecification and moving targets. Respondents link hidden requirements to weak completeness checking [V NaPiRE, Méndez Fernández et al. 2017; Kalinowski et al. 2015].

## 3. Write the spec (`to-spec`, then harden with [requirements.md](requirements.md))
- **MVP requirements carry their hypothesis.** Give each one the falsifiable hypothesis, metric, pre-set threshold and the action if it fails [V Camuffo et al. 2020; 2024]. Don't prescribe how many pivots to make; the two RCTs disagree.
- **Short user stories with concrete acceptance examples** (Given/When/Then, IDs `AC-<FR>.<n>`). Examples improve comprehension [V Ricca et al. 2009], and stories beat use cases for deriving conceptual models [V Dalpiaz & Sturm 2020]. Formal Gherkin/BDD is not required, because its evidence is weak.
- **System-level statements may use a template** such as EARS. Templates beat free text, but no template wins and training is needed [V Großer et al. 2024]. Avoid passive voice when stating relations between concepts [weak: Femmer et al. 2014, contested by reanalysis].
- **Quality requirements are verifiable behaviour** with a metric and a target. Most "NFRs" describe behaviour [V Eckhardt et al. 2016]. Ask about constraints together with quality, since architects often treat NFRs as secondary to constraints [V Ameller et al. 2012]. Use ISO/IEC 25010 as the category list [H].
- **Automated checks are cheap filters, not validation.** QUS criteria and smell detection run at ~59% precision, so about 4 in 10 alerts are false [V Lucassen et al. 2016; Femmer et al. 2017; Frattini et al. 2023]. The banned-word list is a suite heuristic [H].

## 4. Configuration register (CFG)
Every row fills all the fields in the template. The rules:
1. **Few options, each justified.** An option exists only if the system cannot decide for itself; about 52% of one system's parameters were removable [V Xu et al. FSE 2015]. The "~20 per component" ceiling is our heuristic [H].
2. **Validate at startup and fail fast.** Refuse to start on an invalid value, with a message naming the option, the value and the valid range. Never fix silently. Clear messages made diagnosis 3–13× faster, and many systems lack init-time checks [V Yin et al. SOSP 2011; Xu et al. OSDI 2016].
3. **Write constraints between options as checkable rules.** 12–30% of parameter errors are inconsistent values, and many dependencies are undocumented [V Yin et al. 2011; Chen et al. FSE 2020].
4. **Safe, working defaults** (no admin by default, no plain HTTP) [V Rahman et al. ICSE 2019; low-medium strength].
5. **Secrets never live in the repo or in defaults.** They come from a vault or injected env vars, with pre-commit and CI scanning. Rotate anything leaked. Prevention beats detection: only ~15% of detector hits are real secrets [V Meli et al. NDSS 2019; Basak et al. 2023].
6. **A feature flag ≠ an option.** Every flag has an owner, an expiry date and a removal criterion [V Rahman et al. MSR 2016; Mahdavi-Hezaveh et al. EMSE 2021; the effect on failures is unmeasured].
7. **Config is code**: reviewed, and tested in the context of the code that reads it [V Sun et al. OSDI 2020; other practices low-medium].
8. **Test interacting options pairwise**, not exhaustively [V Kuhn et al. 2004; Medeiros et al. 2016].

## 5. Validate
- **Individual structured reading** before any group meeting. Meetings did not raise detection [V Porter et al. 1995; Lanubile & Visaggio 1997]. Prefer usage-based reading: walk the main user tasks through the spec [V Thelin et al. 2003].
- **Walk the flow with the user** using the acceptance examples [V Ricca et al. 2009].
- **Use a low-fidelity prototype** for UI-heavy requirements. It finds largely the same usability problems as a high-fidelity one [V Virzi et al. 1996].
- **For the MVP, run the cheapest hypothesis test first** (problem interviews, smoke test, clickable prototype). Fewer than a third of tested ideas improve their target metric [V Kohavi et al. 2013]. Five users can find as little as 55% of problems, so iterate [V Faulkner 2003].

## 6. Prioritize
- For the MVP, put the riskiest hypothesis first [inferred from Camuffo].
- With up to ~15–20 items, use pairwise comparison with a consistency check or planning-game partitioning. Their accuracy did not differ, and partitioning is easier [V Karlsson et al. 2007]. Score value and cost separately, and collect votes independently before discussion [H].
- MoSCoW is a communication label only [V Vijayakumar et al. 2024: less effective than assumed]. WSJF and Kano are not evidence-based.

## Gate
Run `suite check 2`. It verifies the mechanical items below and must PASS; you and the human judge the rest. Then `suite stage 2 done --owner <provider>`.
- Every FR has an ID, an acceptance example and, for MVP items, a hypothesis with a threshold.
- The completeness check is done and the open questions are 0 or deferred with an owner.
- Every CFG row is complete; every flag has an expiry date; no secret has a default.
- A structured reading pass is recorded; the human signed off.
