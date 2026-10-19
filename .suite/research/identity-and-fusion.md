# Identity (jersey number, re-ID) and two-camera fusion for a phone on a tripod
Recommendation: Treat the jersey number as a **tracklet-level vote** over frames judged legible, never as a per-frame label. Keep ByteTrack, add a thin identity layer (number votes + team colour + ground-plane position and time gap) that can re-link fragments, and fuse the two cameras **late, on the ground plane, as a post-session step**. Published evidence does not show that H3 (80% of player frames with the correct number) or H3b (8 of 10 returns) is reachable from a high phone, and it points to the 80% frame target being unrealistic as worded (confidence: medium on the design, low on the thresholds being met). 
Date: 2026-10-19. Time-box: about 30 searches and fetches. Scope: primary and academic sources only.

Legend. `[V]` = checked this session by fetching the source page (abstract or HTML). `[V-bib]` = bibliographic record or search-result summary only, content not read. `[UNVERIFIED]` = recalled, inferred or my own arithmetic. Several fetches were made through a summarising tool; numbers marked `[V]` were returned from the paper's text or abstract page, but only abstracts or HTML were read, never the PDF layouts. PDFs came back as unreadable binary. Tier follows `docs/research/sources.md` (A = peer-reviewed or primary data; preprints are marked and kept at A only as primary data; see caveat column). No source below is B or C.

## Decision framed
Should the identity layer be "ByteTrack ID = jersey number" (FR-006, FR-007), a vote over number readings plus appearance, or learned re-ID? And should the two phone streams be fused after the session from the per-camera files (FR-004), leaving each camera process unchanged (D-022)?

## 1. Jersey number recognition

### 1.1 Sources
| # | Authors, year | Venue / type | Dataset and sample | Finding | Mark | Tier |
|---|---|---|---|---|---|---|
| J1 | Koshkina and Elder, 2024 | arXiv 2405.13896 (peer-review venue not stated); method + dataset paper | Hockey: 132,983 player images, 4,250 with number labels; soccer: SoccerNet jersey set, 4,064 tracklets, about 2.05 M images, 482 frames per tracklet on average | Pipeline: legibility classifier (ResNet34, 94.5% accuracy, F1 71.7%) -> ViTPose torso crop -> fine-tuned PARSeq -> confidence-weighted vote over the tracklet. Hockey image-level 91.4% (out-of-the-box PARSeq 85.4%). SoccerNet tracklet-level 87.45% test and 79.31% challenge set. Dropping main-subject filtering: 84.56% test. Only about 5.9% of hockey images (7,787 of 132,983) were labelled legible. Hockey-tuned model on soccer 83.9%; soccer-tuned on hockey 65.84%. Pixel height and compute not stated. | [V] | A (preprint) |
| J2 | Balaji, Bright, Prakash, Chen, Clausi, Zelek (Waterloo), 2023 | arXiv 2309.06285 (venue not stated) | SoccerNet jersey set, 4,064 tracklets; 150x120 crops; broadcast low resolution | Keyframe selection before a ResNet-18 + bi-LSTM raised accuracy by 37.8 and 37.7 points: 30.89 -> 68.53 (test), 36.07 -> 73.77 (challenge). Earlier SoccerNet entries 32-58%. KfId reduces 2,052,306 images to 253,350 keyframes (-87.65%). Training on 4x RTX 2080 Ti. Share of tracklets with no readable number not stated. | [V] | A (preprint) |
| J3 | Cioppa, Giancola et al., 2023 | SoccerNet 2023 Challenges Results, arXiv 2309.06006 | SoccerNet challenge | The jersey task is "recognizing the jersey number of players from tracklets"; the abstract page has no accuracy figure. A search summary reports one entry at 76.05% test / 75.17% challenge using body-orientation and image-quality ranking, and one at 77.77% after submission. | task [V]; scores [V-bib] | A (challenge report) |
| J4 | SoccerNet 2024 and 2025 challenge reports (arXiv 2409.10587, 2508.19182) | challenge reports | Game-state reconstruction (GSR) | Jersey number appears only inside GSR, scored by GS-HOTA; no jersey-only accuracy. Teams used YOLOv8 0-99 or digit detectors, PARSeq with ViTPose torso crops, majority voting in tracklets, CLIP, and vision-language models. The baseline's un-fine-tuned MMOCR was called a bottleneck. One team: 0.78 tracklet accuracy. | [V] | A |
| J5 | Bhargavi, Gholami, Pelaez Coyotl (AWS), 2022 | Frontiers in Artificial Intelligence | American football practice video, two camera angles, 5 fps, about 3,000 usable crops | Torso crops average about 20x25 px. Per-frame accuracy 80% baseline, 88.86% with synthetic pre-training, 89.31% for the ensemble. The multi-label model outputs "unrecognizable" on very low-resolution crops. No tracking or temporal aggregation (future work). Accuracy by orientation not quantified. Test set was crops that survived labelling (3,000 of about 9,000 candidates), so it is an accuracy on selected, usable crops, not on all player frames. | [V] | A |
| J6 | Nady and Hemayed, 2021 (S2JN) | SciTePress | 1,872 + 851 basketball images, 1,317 ice hockey | Basketball jersey dataset exists; accuracy not read. | [V-bib] | A |
| J7 | Lin et al., 2024 | arXiv 2406.01033 | Multi-sport, basketball only 522 images (1%) | Basketball is a small slice; not used for figures. | [V-bib] | A (preprint) |
| J8 | E-BARD (Giudici et al.) | university page / Hugging Face model card | NBA broadcast | Basketball detection, team and number labels exist; no accuracy read; broadcast, not tripod. | [V-bib] | not rated |

### 1.2 What this means for the questions
| Question | Evidence | Strength | Note |
|---|---|---|---|
| Is a basketball-specific, tripod-view benchmark available? | None found in the sources checked: only a small image dataset (J6), broadcast data (J8), and a 1% slice (J7). | weak (absence) | Absence in about 30 searches is not proof of absence. |
| Best published tracklet-level accuracy | 87.45% test but 79.31% challenge on SoccerNet (J1); the other published SoccerNet entries are 68-78% (J2, J3). | moderate | Tracklet-level, on broadcast footage, with a vote over hundreds of frames per tracklet. |
| Does the figure equal H3? | No. H3 counts **player frames** with the right number; the literature scores **tracklets** after voting over about 480 frames. The two are different units. A tracklet can be right while most of its frames are unreadable. | strong (definition) | FR-006 must say which one it means. |
| Legibility is its own problem | J1 trains a separate legibility classifier; J2 shows 37 points gained just by choosing keyframes; hockey labelling found about 5.9% of images legible (J1). | strong that selection matters; the 5.9% is hockey with university cameras and is not transferable | Do not read the 5.9% as a basketball rate. |
| Pixel height needed | No source checked binned accuracy by number height. J5 reached about 88% per frame on usable crops of about 20x25 px (torso box, American football, large block numerals). J2 used 150x120 crops. | weak | Any threshold in px is `[UNVERIFIED]`. |
| Viewing angle / facing away | Orientation is used to rank or filter crops (J3 as summarised) and the PARSeq pipeline relies on torso keypoints (J1). The accuracy-vs-angle curve was not found. | weak | |
| Compute | J1: PARSeq plus ViTPose plus ResNet34; hardware and runtime not stated. J2: 4x RTX 2080 Ti for training only; inference cost not stated. J5: runs on stills; cost not stated. | weak (gap) | Cost has to be measured on the borrowed GPU PC (H2). Voting needs to read only a few frames per tracklet, not all. |

### 1.3 Phone-on-tripod arithmetic (my estimate, not from a source) `[UNVERIFIED]`
A 3x3 half court is about 15 m x 11 m. If one 1080p phone sees roughly the full 15 m width, that is about 128 px per metre at the scale of the image plane. A 15-25 cm numeral on a vest then spans roughly 20-30 px, or about 40-60 px at 4K, before perspective loss on far players and before the high viewing angle foreshortens a back print. This is the same order as the 20x25 px torso crops in J5 where the crop-level result was about 88%, so reading is plausible only if numerals are large and high-contrast (which agrees with the decision record's "vests with large numbers"). The estimate depends on lens field of view, distance, and number size, none of which I measured. It must be checked on a real frame (count pixels on a real vest at the far baseline).

### 1.4 Verdict on H3
| Claim | Verdict | Why |
|---|---|---|
| "At least 80% of player frames with the correct number", per-frame, from a high phone | **Not supported as realistic.** Players face the camera only part of the time; a high camera sees the back of a vest or the top of the shoulders for some of every possession. No source shows a per-frame rate near 80% in a team sport; the closest per-frame figure (J5) is on selected usable crops. | `[UNVERIFIED]` for the exact visible fraction |
| 80% of **tracklets** (or of player-seconds) with the right number after a vote | **Plausible** with large numerals: SoccerNet tracklet accuracy 79-87% (J1) with a dedicated legibility step and a vote. | moderate, transfers imperfectly (broadcast soccer to tripod basketball) |
| Carrying an ID through frames where the number is not readable | Needs tracking between readings (Section 2). The accuracy then depends on the tracker, not the reader. | |

Recommendation for the spec: redefine H3 as "share of player frames whose assigned ID is correct, where the ID may come from a vote earlier or later in the same track" and report separately the share of frames with a direct reading. This keeps the 80% bar but makes it measurable.

## 2. Re-identification after leaving the frame

### 2.1 Sources
| # | Authors, year | Venue / type | Dataset | Finding | Mark | Tier |
|---|---|---|---|---|---|---|
| R1 | Cui, Zeng, Zhao, Yang, Wu, Wang, 2023 (SportsMOT, MixSort) | ICCV 2023 per the search record; the arXiv page lists no venue | 240 sequences, over 150K frames, over 1.6M boxes; basketball, volleyball, football | "The key challenge of SportsMOT lies in object association." Numbers: MixSort-Byte 65.7 HOTA / 74.1 IDF1 vs ByteTrack 64.1 / 71.4 on the test set; basketball is the hardest sport (HOTA 60.8, IDF1 67.8 for MixSort-Byte). Those numbers came from the repository summary in a search result, not the paper. | claim [V]; figures [V-bib] | A |
| R2 | Sun, Huang, Yang, Jiang, Hwang (U. Washington), 2024 (GTA) | ACCV 2024 Workshops per the search record; arXiv 2411.08216 page lists no venue | SportsMOT and SoccerNet 2023 tracking set (oracle detections on SoccerNet) | Plug-in post-processing: split mixed tracklets (DBSCAN on OSNet embeddings), join cut tracklets (hierarchical clustering with distance limits). On SportsMOT: ByteTrack 63.46 -> 69.74 HOTA, IDF1 70.76 -> 83.16; Deep-EIoU 77.21 -> 81.04 HOTA, IDF1 79.81 -> 86.51. Assumes a fixed camera. Basketball-only figures and compute not stated. ReID model trained on SportsMOT. | [V] | A (preprint / workshop) |
| R3 | Yin, Yeung, Hu, Ichikawa, Azechi, Takahashi, Fujii, 2024 | arXiv 2412.06258 (no venue) | **3x3 basketball**, fixed camera, 42 videos, 7,531 frames, 6 players (camera height not stated) | Pose-marker tracker 72.6 HOTA vs BoT-SORT 55.7, Deep-EIoU 58.0, Basketball-SORT 61.5 (the abstract says 72.3). ID switches per video: 0.0 for the proposed method vs 4.3 / 6.2 / 8.1 for baselines; the zero comes from a pipeline where identities were set by hand during annotation, so it is **not** an automatic result. Jersey numbers and re-entry not handled. | [V] | A (preprint), only 3x3 data found |
| R4 | Liang, Wu, Yang, Zhang, Peng, Xu, 2020 | Applied Sciences 10(3):864 | Multi-view basketball | Adds jersey colour and jersey number to K-shortest-paths tracking. Abstract: about 70% of jersey colour and 50% of jersey number "over a whole sequence" would let the method keep identity better than plain KSP. The page does not define the percentages; my reading (cue must be usable on that share of the sequence) is not confirmed. | [V], meaning of % `[UNVERIFIED]` | A |
| R5 | Koshkina and Elder / SoccerNet 2025 GSR entries | see J1, J4 | | Winning GSR entries combine ReID embeddings, team, jersey number and speed to join tracklets into longer tracks (GSR-1); others use CLIP-ReID or BPBReID. | [V] | A |

### 2.2 Option table
| Option | Evidence | Strength | Mechanism | Cost |
|---|---|---|---|---|
| ByteTrack alone (today) | R1: association is the hard part in sports; basketball hardest. | strong | Motion + IoU only; a gap makes a new ID. | none |
| ByteTrack + appearance post-link (GTA-style) | R2: +6 to +13 IDF1 on SportsMOT, fixed camera. | moderate (not basketball-only; ReID trained on SportsMOT) | Cluster embeddings, split and merge tracklets. | OSNet inference per box; compute not stated |
| Tracker + number votes + team colour (jersey as hard key) | R4 (weak abstract-level), R5 (GSR winners join tracklets with number, team, speed), J1/J2 (vote works on tracklets) | moderate for "works", weak for "meets 8/10 from a tripod" | Fragments are re-linked when their voted numbers agree and team colour matches; exclude merges that break time or position. | small if readings are sparse; PARSeq/pose per sampled crop |
| Learned re-ID alone | R2/R5 show it helps; 3x3 players of one team wear similar kit, and SportsMOT says players have "similar but distinguishable appearances" (R1 abstract). | weak for same-kit teammates | Embedding distance. | training data and GPU |
| Manual correction of IDs | R3 reaches 0 switches only because identities were fixed by hand during labelling. | strong, but not automatic | Operator confirms IDs at the end of a drill. | operator time |

### 2.3 How often is a number readable, and effect of facing away
No source measured the share of frames in which a number is readable on a high camera in a team sport. What exists: 5.9% of hockey images were labelled legible [V] (J1, not transferable); keyframe selection alone was worth 37 points [V] (J2); body orientation is used to rank crops (J3, `[V-bib]`). So the rate is **unmeasured** for the Pointr setting and must be counted in the December test. Plan to report it directly: for each tracklet, the share of frames where the number is readable by a human labeller.

H3b (8 of 10 returns keep ID): no benchmark found that scores "leaves and re-enters" for same-kit teammates. GTA-type results (R2) are in IDF1 and not per re-entry. Whether it is realistic therefore depends on a number reading after return; since a player may re-enter facing away, a return can stay unlabeled until the next readable frame (a delay of some frames). `[UNVERIFIED]`. A 30-second absence (AC-007.1) is far outside what motion-based association handles, so the number or team and position must carry the identity.

## 3. Multi-camera fusion on a ground plane

### 3.1 Sources
| # | Authors, year | Venue / type | Dataset | Finding | Mark | Tier |
|---|---|---|---|---|---|---|
| F1 | Chavdarova et al. (Idiap, EPFL, ETH), 2018 (WILDTRACK) | CVPR 2018 | 7 static, synchronized, jointly calibrated cameras, 400 annotated frames at 2 fps, open public area | Defines the benchmark. Sync method and accuracy and the resolution not stated in the portion read. | [V] partial | A |
| F2 | Hou, Zheng, Gould, 2020 (MVDet) | ECCV 2020 | WILDTRACK and MultiviewX (synthetic, controlled occlusion) | 88.2% MODA on WILDTRACK, +14.1 over the prior best. A later table (2025 paper) lists MVDet on MultiviewX at 83.9 (search summary only). | WILDTRACK [V]; MultiviewX [V-bib] | A |
| F3 | Teepe et al., 2023 (EarlyBird) | arXiv 2310.13350 | WILDTRACK, MultiviewX | **Early fusion** in the bird's-eye view: detect each person once, then only temporal association remains, using learned re-ID. WILDTRACK +4.6 MOTA, +5.6 IDF1 over prior best. Sync not discussed. | [V] | A (preprint) |
| F4 | Teepe, Wolters, Gilg, Herzog, Rigoll, 2024 (TrackTacular) | arXiv 2403.12573 (CVPRW per search record, not confirmed) | WILDTRACK, MultiviewX, Synthehicle | WILDTRACK MODA 91.8-93.2 and tracking IDF1 94.2-95.3 / MOTA 89.6-91.8 (best variants); MultiviewX MODA 94.2-96.5, IDF1 83.4-85.6, MOTA 91.4-92.4. EarlyBird in same tables: WILDTRACK IDF1 92.3 / MOTA 89.5; MultiviewX IDF1 82.4 / MOTA 88.4. **No** ablation on camera synchronization, number of cameras (e.g. 2), camera dropout or calibration noise; calibration noise is added only in training. RTX 3090; runtime not stated. | [V] | A (preprint) |
| F5 | Nguyen, Henschel, Rosenhahn, Sonntag, Swoboda, 2022 (LMGP) | CVPR 2022 ("official version" in the arXiv comments) | WILDTRACK, Campus, PETS-09 | **Late fusion of tracklets:** single-camera tracklets are refined with 3D geometry projections, then linked across cameras and time by a lifted multicut. "Near-perfect" on WILDTRACK, no numbers on the page read. Notes ID switches inside tracklets propagate into the cross-camera graph. Sync assumption not stated on the page. | [V] page; numbers not read | A |
| F6 | On-the-fly homographies for multi-camera tracking, 2026 | arXiv 2609.18582 (as listed in a search result) | | Late fusion with sequential Kalman updates per camera; says planar-homography association is very sensitive to noise (a few pixels of vertical jitter give large ground displacements) and feeds smoothed single-view states instead of raw boxes. Does not test timestamp misalignment. | [V-bib] | A (preprint) |
| F7 | Delannay et al., 2009; Hayet et al., 2005 | conference papers | football and general | Ground-plane fusion for sports with "loosely synchronized" cameras; a supervisor module fuses per-view tracks; numbers can be read only when facing a camera, so graph tracking propagates identity along the trajectory. | [V-bib] | A |
| F8 | 2014 two-camera paper, "Recovery of temporal synchronization error through online 3D tracking with two cameras" (Ozyegin) | ICDSC 2014 per the record | | Recovers sync error when the product with object speed is within limits. Page returned 403. | [V-bib] | A |

### 3.2 Option table
| Option | Evidence | Strength | Mechanism | Cost |
|---|---|---|---|---|
| Early fusion (project features to the ground plane, detect once) | F2-F4: best published numbers (MODA about 92-97, IDF1 up to 95 on WILDTRACK) | strong **on those datasets**; weak for Pointr | Learned multi-view network on synchronized frames. | Needs training on multi-view data of the court, GPU, cameras must be frame-synchronized; the per-camera processes would have to change. Conflicts with D-022. |
| Late fusion: per-camera tracks, associate on the ground plane | F5, F6, F7 | moderate | Project each foot point to court metres, match by distance and time, then resolve identity with number / colour. | Light; can run after the session; accuracy depends on per-camera quality and sync |
| Late fusion with cross-camera appearance | F5 (tracklet graph), F3 (re-ID features) | moderate | Add appearance distance to the ground-plane cost. | Embeddings; same-kit teammates limit it (R1) |
| No fusion; report per camera | none needed | n/a | | none; fails FR-004 |

### 3.3 Timing error
No source I read measured fusion accuracy against camera time offset in a team-sport or pedestrian dataset. WILDTRACK and the BEV methods assume synchronized cameras (F1; F3/F4 do not discuss it). The only quantitative statements are indirect: tolerance scales with offset times object speed (F8, `[V-bib]` via search summary); one tracker is said to work within one second by estimating offsets (search summary, `[V-bib]`); another reaches a median sync error under 50 ms by video alignment (search summary, `[V-bib]`). My arithmetic, `[UNVERIFIED]`: at 5 m/s, a 33 ms offset is about 0.17 m and a 100 ms offset about 0.5 m, which uses up the 0.5 m calibration budget (FR-002) before any other error. So FR-005's phone-to-phone limit of 33 ms (one frame) is sensible; the published literature does not give a tested tolerance.

## 4. Architecture: post-session or near-live fusion reading per-camera files

### 4.1 Evidence
| Point | Evidence | Mark |
|---|---|---|
| Late fusion of per-camera tracks is a recognised family (tracklets first, then cross-camera association). | F5, F6, F7 | [V] / [V-bib] |
| Fusion run offline on stored tracks is normal in benchmarks (WILDTRACK is evaluated offline on stored frames). | F1-F4 | [V] |
| Per-camera ID errors propagate into the fused result. | F5 abstract | [V] |
| Homography-based association is noise-sensitive. | F6 | [V-bib] |
| Published examples of a deployed "separate fusion step over per-camera session files" in a commercial product | none found in sources checked | `[UNVERIFIED]` |

Conclusion: the design is sound on the evidence available, because it matches the late-fusion family and keeps the per-camera processes untouched. This is a design judgement; the sources show that the pattern works in research, not that it holds up with phones. Confidence: medium.

### 4.2 Failure modes and how to detect them
| Failure | Cause | Detection in the fusion step |
|---|---|---|
| Same player counted twice (double count) | Two per-camera tracks not matched: ground-plane distance above the gate, or offset too large | Report unmatched tracks in the overlap zone (AC-004.1 difference report) |
| Two players merged | Close players in the overlap zone; foot point error from homography (F6) | Gate on distance and require number/colour agreement |
| ID conflict | Camera A says 7, camera B says 11 for the matched pair | Keep both readings with votes; flag; never overwrite silently |
| Same ID on two different people | Each camera assigns number 7 to different people (misreads) | Check the same number twice at the same time in different places |
| Sync error | Different clocks, drift | Use FR-005 offsets; estimate and compensate with a constant offset plus drift; flag when residual is high |
| Per-camera ID switch inside a track | tracker error propagates (F5) | Split tracks at an ID jump before matching (GTA splitter idea, R2) |
| Shot counted twice or by two shooters | Event seen in both views | Merge events by time window and position, count once |

## Dissent / caveats
- Nearly all jersey and ID figures are from broadcast soccer or hockey; none are from a tripod basketball camera. Transfer is untested.
- Several sources are arXiv preprints without a confirmed venue (J1, J2, F3, F4, R3). Tier A here means primary data, not proven.
- Self-reported leaderboards: figures on WILDTRACK vary between papers (TrackTacular's MODA appears as 91.8 and 92.1 in different tables).
- Sports-vmTracking (R3) reports zero ID switches only because identities were fixed by hand during annotation.
- Search summaries (tier-A pages read through a summarising tool) are labelled `[V-bib]` unless a fetch returned the figure.

## Open questions
1. What share of player frames shows a readable number on the owner's real vest from the planned tripod height? Count it from the first recording.
2. Is H3 meant per frame or per tracklet? See the wording change in 1.4.
3. Which phones, resolution and frame rate (decides pixels per numeral)?
4. Are all players in the same kit with numbers on both back and front? (Fronts help only when facing the camera.)
5. Does the owner accept a final operator confirmation of IDs per drill (manual correction)?

## Options for the ADR

### A. Identity layer
| Option | Trade-offs | Evidence strength | Fits H3 / H3b |
|---|---|---|---|
| A1. Track-level number vote on legible frames, linked to ByteTrack tracks, ID = voted number | Cheap; matches the tracklet-vote design that gave 79-87% on SoccerNet (J1). Fails whenever the number is hidden (back to camera) or the track fragments. | moderate (broadcast soccer, not tripod) | H3 realistic **per tracklet**, not per frame; H3b not shown |
| A2. A1 + team colour + position/time gating to re-link fragments after a gap (GTA-style post-processing with number and colour as the key) | Best use of known-good pieces: GSR winners use number, team and speed (R5); GTA improves IDF1 on a fixed camera (R2). More code; thresholds must be tuned on December data. | moderate | H3b plausible if the player shows the number after returning; unproven |
| A3. A2 + operator confirms or corrects IDs at drill end | Meets 8 of 10 by construction; costs operator time; R3 shows manual labelling is how zero switches were reached. | strong that it works, weak as an automatic result | H3b met, H3 by assisted measure |
| A4. Learned appearance re-ID alone | Same-kit teammates look alike (R1); needs training data and GPU; spec already puts it on the backlog. | weak for same-kit teams | H3b not supported |

Recommendation: **A2 as the target, A1 as the first build step, A3 as the stated fallback** (matches the spec's "vests with large numbers or manual correction" branch). Confidence: medium that the design is right; **low** that H3 at 80% per frame and H3b at 8 of 10 are met without A3. Keep the interface fixed per NFR-003 so A4 can replace it later.

### B. Cross-camera fusion
| Option | Trade-offs | Evidence strength | Notes |
|---|---|---|---|
| B1. Post-session late fusion of per-camera tracks on the court plane, match by distance + time, then by number/colour; difference report | Leaves per-camera processes alone (D-022); easy to test offline; relies on FR-005 sync and FR-002 calibration (0.5 m). | moderate (late fusion family F5-F7) | Recommended |
| B2. B1 run near-live on a rolling window of the growing session files | Same logic, shorter latency; needs files readable while being written (NFR-004) and a stable ID policy for provisional merges; ID changes visible to users. | weak-moderate (no deployed examples found) | Defer until B1 works |
| B3. Early fusion (BEV multi-view network) | Highest published numbers, but trained and tested on 7 synchronized cameras (WILDTRACK) and 6 (MultiviewX); needs synchronized frames and training data; changes the architecture; no 2-camera ablation found (F4). | strong on benchmarks, weak for Pointr | Not for December |
| B4. No fusion, per-camera stats and a manual merge | Violates FR-004 but is a safe fallback if sync fails. | n/a | Fallback only |

Recommendation: **B1** with a hard gate (FR-005: fix clock sync before trusting any fusion result), pair matching limited to the overlap zone, keep both cameras' readings in the output and flag disagreements. Confidence: medium on the design; low on any numeric accuracy because no published two-camera, same-kit, tripod result exists and no timing-tolerance curve was found.
