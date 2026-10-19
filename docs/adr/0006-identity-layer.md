# 0006 — Identity layer: jersey-number voting, then colour and position gating
status: accepted · date: 2026-10-19 (accepted by the owner)

## Context
FR-006 sets the track ID to the jersey number; FR-007 keeps it after a player leaves and returns; NFR-003 asks for a replaceable identity method. Today `tracks.csv` has `athlete_id` empty until the athlete assignment phase, and the tracker (ByteTrack) gives temporary IDs that fragment when people leave and return. The literature scores jersey numbers **per track after voting across frames**, not per frame, and no benchmark scores "leaves and re-enters" for teammates in the same kit.

## Options considered
| Option | Pros | Cons | Fit to NFRs |
|---|---|---|---|
| A1. Read the number on legible frames of a ByteTrack track and vote; ID is the voted number | Cheap; matches the tracklet-vote design that reached 79–87% on SoccerNet broadcast video | Fails when the number faces away or the track fragments | NFR-003 if behind an interface |
| A2. A1 plus team colour and position-and-time gating to re-link fragments after a gap | Uses the pieces that worked in sports (number, team, speed; global tracklet association raised IDF1 on a fixed camera) | More code; thresholds tuned on December data | Best use of known pieces |
| A3. A2 plus the operator confirms or corrects IDs at the end of a drill | Meets 8 of 10 by construction | Operator time; not an automatic result | Stated fallback in the spec |
| A4. Learned appearance re-identification alone | No jersey needed | Same-kit teammates look alike; needs data and GPU; already on the backlog | Not supported |

## Decision
Decided (owner, 2026-10-19): **A1 as the first build step, A2 as the target, A3 as the fallback**. An `IdentityResolver` interface after the tracker takes the track observations and crops and returns a player number with a confidence; the method is chosen by CFG-004 (`IDENTITY_METHOD`), so A4 can replace it later without changing the output schema (NFR-003). Registered players (Phase 06) map numbers to athletes later; this layer does not touch registrations.

## Consequences
- `tracks.csv` gains `player_number` and `id_source` columns (contract bump from 0.10.0); `athlete_id` stays empty.
- Spec change (accepted by the owner as CR-3): FR-006 should say whether 80% means player frames, or tracks after voting. The sources support only the second; a per-frame 80% from a high phone is unsupported by any source found.
- H3b (8 of 10 returns) is unproven for same-kit players; A3 meets it by construction. Numeral size on a phone view is the open fact: arithmetic suggests 20–30 px on a full-width 1080p view, which must be checked on a real frame.
- Confidence: medium that the design is right; low that H3 and H3b are met automatically.

## Sources
- [Koshkina and Elder: a general framework for jersey number recognition in sports video (2024)](https://arxiv.org/abs/2405.13896) · tier A, preprint · 79–87% per tracklet on SoccerNet, hockey included
- [Balaji et al.: jersey number recognition with keyframe identification (2023)](https://arxiv.org/abs/2309.06285) · tier A, preprint · SoccerNet 4,064 tracklets
- [Yin et al.: 3x3 basketball tracking dataset (2024)](https://arxiv.org/abs/2412.06258) · tier A, preprint · zero ID switches only because identities were fixed by hand
- [GTA: global tracklet association (Sun et al., 2024)](https://arxiv.org/abs/2411.08216) · tier A, preprint
- Research note: `.suite/research/identity-and-fusion.md`
