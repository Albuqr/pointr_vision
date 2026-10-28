# MVP Decision Record — pointr-vision
date: 2026-10-16 · participants: project owner (developer, first user), deliberation agent (Claude Sonnet 5.5) · review date: 2026-12-31

## 1. Idea and value proposition
For amateur and club basketball teams and their coaches (3x3 first) who cannot see where each player shoots from, whether they were guarded and whether the shot went in, Pointr Vision delivers per-player shot location, defender proximity and make/miss from 2+ phones on tripods, a PC and a rim sensor, so the coach gives each player the shooting practice they need and, later, makes in-game decisions.
v1 is a test rig built for the developer (1v1 and 3x3 community testing), not for a paying customer. Product audience and v1 audience differ on purpose.

## 2. Confidence
before: 100% (basis: the former basketball coach said it solves most of his problems after a pitch) · after: 80%
what changed and why: the person-tracking pipeline runs (know: pasted run, RF-DETR Nano on CPU, ByteTrack, 1280x720 stream). The value the coach described (shots, usage, passing, defense) needs a ball, rim and make/miss layer that is not built; identity (jersey numbers) is not built; calibration has only been tested on synthetic points. The 80% is the owner's number. The owner reports ball tracking looks consistent; no run, footage or count was given, so this is `believe` until H1.

## 3. Central question and options
Can a phone-based system produce per-player shot location, defender proximity and make/miss that a team would use, within one developer's time and ~100 BRL of hardware?
| option | criteria it meets | criteria it fails | chosen? |
|---|---|---|---|
| Video only (ball + rim detection, make/miss from trajectory) | no extra hardware, simple setup | net occlusion and ball behind rim make make/miss ambiguous; accuracy unmeasured | yes, as primary, gated by H1 |
| Video + rim sensor for makes | removes the make/miss ambiguity, gives ground truth for training | ~1 month shipping, extra setup step, still needs video for attempts and shooter | yes, ordered now as a hedge (~100 BRL) |
| Manual tagging of shots (person with a sheet) | no build cost | one untrained person cannot keep up at game speed; adds nothing a scoresheet does not | no |
| Hire assistant coaches | works today | far more expensive (owner's statement) | no |
| Process recorded video afterwards | removes real-time constraint | owner expects about an hour of processing (CPU figure, GPU unmeasured) and wants real time | no (owner decision: real time) |

## 4. Critical assumptions → falsifiable tests
| # | assumption | know (source) / believe | refutation test | threshold | time/cost | if it fails → |
|---|---|---|---|---|---|---|
| H1 | Video finds shot attempts and calls make/miss correctly | believe (no accuracy figure found in the sources checked; blog, patents and a thesis only) | December 1-person session, 30+ shots, hand-counted ground truth | >=85% of attempts found and >=90% of those called right = continue; 70-85% = add the rim sensor; <70% = stop vision-only | ~1 day plus labelling/tuning | see threshold column |
| H2 | A borrowed GPU PC sustains the frame rate ball tracking needs | believe (never run; CPU laptop clean runs were 1.8-2.4 fps) | one GPU run on the borrowed PC with one phone | sustain ~10-15 fps | hours, once a PC is borrowed | below that H1 cannot pass; rethink the approach |
| H3 | Jersey numbers give a correct identity on enough frames | believe (not built; a public demo shows team and number recognition on broadcast footage only) | jersey test on the scrimmage, hand-label ~200 frames | >=80% of player frames with the right number = continue; 50-80% = vests with large numbers or manual correction; <50% = drop the jersey approach | ~1 day | see threshold column |
| H4 | Calibration gives correct metres on a real court | believe (tested on synthetic points only) | tape test: app check error vs hand measurement | error over ~0.5 m = fail | ~1 hour on a court | fix calibration or stop |
| H5 | A coach acts on a hand-made report and changes practice | believe (one coach, reaction to a pitch) | hand-make one report from a recorded practice, check what he changes next practice | NOT SET; owner parked it until a recording exists (2-3 weeks) | hours plus a recording | decide at review |

Secondary hypotheses (not among the 3-5 riskiest; thresholds partly open):
- H6: 2 phones on a 3x3 half court give coverage and merge into one set of tracks. believe (camera fusion not built). Test: 2-phone scrimmage. Threshold NOT SET. If it fails: decide at review.
- H7: a team sets up the phones and calibrates in 15 minutes or less. believe. Test: time a full setup at a court. Threshold <=15 minutes. If it fails: simplify setup.
- H8: a live number changes a coach's decision (subs, play calls). believe. Test: show a live number in a scrimmage after H1-H3. Threshold NOT SET. If it fails: cut live metrics from v1.

Edge-case rules (accepted): sensor fires with no attempt seen = log a make, shooter unknown, flagged, not counted as an attempt; attempt seen with no sensor signal within a window = miss (window length measured in the December tests); ball hidden or ambiguous near the rim = "uncertain", kept out of the stats; no clear possession before the shot = shooter unknown.
Attribution mechanism (owner, `believe`): after a make or miss, the algorithm checks ball position and takes whoever last had possession; sensor timestamps are tied to the session.

## 5. Arguments
| claim | grounds | strongest rebuttal | status |
|---|---|---|---|
| Real time is the right mode | owner expects ~1 hour of post-processing; wants live use in games | the report is wanted after the session anyway; GPU post-processing time is unmeasured | owner decision, kept |
| Sensor for makes is worth the hedge | cheap (~100 BRL), removes the hardest make/miss ambiguity, gives ground truth | adds setup and a month of shipping; does not detect attempts, shooter or defender | accepted, ordered now |
| Manual tagging does not beat a scoresheet | one untrained person cannot tag game-speed play | a trained tagger on recorded video is cheap | accepted by owner |
| Live in-game shot accuracy guides decisions | owner: subs and play calls | a player with 5 attempts has a wide interval (3 of 6 is roughly 19-81%); live make/miss and identity are the two hardest pieces | open, kept in scope by owner with no hypothesis |

## 6. Premortem
| cause of failure | response (mitigate / accept / test) |
|---|---|
| Too computationally demanding (hardware) | test: H2 on a borrowed GPU PC |
| Ball tracking algorithm fails on phone footage | test: H1; hedge: rim sensor |
| Needs too many cameras or too expensive | accept/test: 2 phones for 3x3 tested in H6; owner supplies 2-3 phones; no cost limit set |
| Athletes may be minors, consent needed | accept: owner says arrangements are in motion; nothing in the record shows it is done |
| Identity (jersey numbers) does not work at game conditions | test: H3 |
| Non-technical causes (a coach, player or club says no, adoption, channel) | accept: owner did not name any after being asked twice; see open objections |

## 7. Outside view
Similar projects or own history used: the owner's own history (the current detect-track-calibrate pipeline took about 2 weeks with heavy AI assistance, built mostly from pretrained models). The agent flagged that the ball and rim layer is a different kind of work (data, training, rules), and the owner confirmed the 2 weeks excludes labelling and training. Public ball and hoop detectors exist (Roboflow Universe projects, 157 to ~1,700 images) and the owner wants non-Roboflow options researched; none outside Roboflow was found for basketball in a quick search. No published make/miss accuracy was found. · slack applied: the agent's rough drafts, accepted by the owner as working estimates, add about 40-60% above the owner's lower figures for unbuilt items; unmeasured.

## 8. MVP scope
| in scope | tests hypothesis # |
|---|---|
| Person tracking with calibration into metres (built) | H4 |
| Ball and rim detection from video | H1, H2 |
| Rim sensor (make timestamps, ground truth), received by the PC | H1 |
| Make/miss calls and edge-case rules above | H1 |
| Shooter attribution by last possession before the shot | H1, H3 |
| Jersey-number identity | H3 |
| Shot location map | H1, H4 |
| "Guarded by" as proximity using team colour | none yet |
| Camera fusion for 2 phones | H6 |
| Movement metrics (already built) | H5 |
| Session browser | none (engineering support for testing across sessions) |
| Live metrics | H8 (threshold not set) |
| Cloud sync | none (team access to data); first item dropped if behind |
Out of scope: shot form and hand-position analysis (v2, needs more cameras), plans and payments, a per-player cloud service, a coach-facing report until the H5 test, 5x5 courts, a UI beyond Studio.

## 9. Estimate (ranges, with the origin of each number)
effort: ball and rim detector 2-4 weeks (owner), identity about 4 weeks (owner), shooter attribution 2-4, 3x3 adjustments 1-3, camera fusion 3-8, cloud sync + session browser + live metrics 2-6 (these last four are agent drafts accepted by the owner, with no data; the owner says he does not know the real durations) · cost: about 100 BRL for the rim sensor; phones supplied by the owner (2, maybe 3); a borrowed GPU PC · time: about 11 weeks from 2026-10-16 to 2027-01-01 (December 1- and 2-person tests; full 3x3 testing from January); if the work were serial the ranges sum to about 14-29 weeks. Solo with AI agents; hours per week not given.

## 10. Open objections and who decides
- Need evidence for teams is one coach's reaction to a pitch (n=1), and he is not the v1 customer. Decider: owner, after the H5 test.
- The shot layer (ball, rim, attribution) is unbuilt and its accuracy is unmeasured; the "ball tracking is consistent" report has no run behind it. Decider: owner, at H1.
- Non-technical premortem causes (adoption, channel, a coach or club declining) were not answered. Decider: owner.
- Cloud sync, session browser and live metrics are in scope without a tested hypothesis; live in-game accuracy is a small-sample problem. Decider: owner (kept in by owner decision; cloud sync dropped first).
- Effort is unmeasured and the serial sum exceeds the time to January 1. Decider: owner.
- Real-time frame rate on a GPU is untested and H1 cannot pass without it. Decider: owner, at H2.
- Consent for recording possible minors is "in motion", not confirmed. Decider: owner.
- H5, H6 and H8 have no thresholds yet.

## 11. Triggers
pivot if: H1 lands at 70-85% (add the sensor) or H3 at 50-80% (vests or manual correction) · stop if: H1 <70% and the sensor route also fails, or H2 cannot sustain the needed frame rate with no alternative, or H4 error stays over ~0.5 m · next review: 2026-12-31, after the December 1- and 2-person tests

## Change request (2026-10-28, grill-with-docs, owner-approved)
- **Edge-case rule, "sensor fires with no attempt seen".** Replace "log a make, shooter unknown, flagged, not counted
  as an attempt" with: log an **unmatched sensor make**, flagged; it is not an attempt or a make in the statistics, and
  the scorer counts it as an attempt the video missed (`GLOSSARY.md`, D-047, `DATA_CONTRACTS.md` section 12).
- **Scope for December.** All of Phase R, including the new slice R2a (one process, shared live IDs, ADR 0007), plus
  every D-044 item; the owner accepts that the serial estimate exceeds the time left (D-047).
- **GPU PC.** Arranged and set up with CUDA (D-046); the objection "real-time frame rate on a GPU is untested" stands
  until R2-A3 is recorded.
