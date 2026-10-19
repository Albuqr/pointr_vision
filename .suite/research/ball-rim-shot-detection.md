# How should Pointr Vision add ball and rim detection, and where should shot inference run?

Recommendation: fine-tune the existing RF-DETR as one multi-class detector (person, ball, rim), treat the rim as a once-per-session fixed position confirmed by detections, and run shot inference as a separate layer over the logged streams that works live and post hoc, with post-session full-rate re-processing as the accuracy path for H1 (confidence: medium for the detector option, medium-high for the layer option; the evidence is indirect, see caveats).

Date of research: 2026-10-19. Scope: primary and academic sources only (peer-reviewed papers, university groups, dataset papers, official model cards and docs). Time-box: about 30 searches or fetches; about 33 used.

## Verification legend
- `[V]` the figure was read in the source text this session (page or PDF text extracted).
- `[V-bib]` only a bibliographic record or a search-result snippet was seen; the figure was not read in the source. Treat as a lead, not as evidence.
- `[UNVERIFIED]` recalled, derived, or no source found.
- `[VENDOR]` figure published by the vendor of the model. `[AFFIL]` paper has authors from the vendor.
- Tiers follow `docs/research/sources.md` (A peer-reviewed or official docs, B reputable practitioner or thesis, C other). Tier is trust in the source, not proof of the effect. Items 33+ days old are not stale-flagged unless the area moves fast; all papers below are from 2019-2026, and the fast-moving ones (RF-DETR, YOLO) are from 2025-2026.

## Headline finding
There is no published, peer-reviewed accuracy figure for H1 (shot attempts found and make/miss called) from a single static phone camera. Everything found is either (a) ball or rim detection only, (b) another sport, (c) broadcast basketball, or (d) a patent or practitioner project (excluded here). H1 therefore stays a `believe` hypothesis until the December test; this note gives the best bounds and the design options that the evidence supports.

## 1. Source register (what was read)
| # | Source | Authors, year, venue/publisher | Type | Dataset and sample | Finding | Tier | Mark |
|---|---|---|---|---|---|---|---|
| S1 | RF-DETR: Neural Architecture Search for Real-Time Detection Transformers, arXiv 2511.09554 | Robinson, Robicheaux, Popov, Ramanan, Peri; 2025 (v2 Feb 2026); ICLR 2026 per arXiv comments | paper, vendor-affiliated | COCO val2017, RF100-VL | Table 2: RF-DETR N/S/M/L = 48.0/52.9/54.7/56.5 AP, latency 2.3/3.5/4.4/6.8 ms on NVIDIA T4, TensorRT 10.4, CUDA 12.4, with 200 ms pauses between passes. Input sizes N 384, S 512, M 576, L 704 (Appendix A). Same table: YOLO11 N/S/M 2.2/3.2/5.1 ms at 37.1/44.1/48.3 AP; D-FINE N/S/M 2.1/3.5/5.4 ms at 42.7/50.6/55.0 AP. Precision and batch size not stated in Table 2 (FP16 inferred). | A | `[V]` `[VENDOR]` `[AFFIL]` |
| S2 | RF-DETR repository README (Roboflow) | Roboflow; current at fetch 2026-10-19 | official docs | COCO val2017 | Latency measured "TensorRT, FP16, and batch size 1" on T4. Licences: Apache 2.0 for the package and N/S/M/L detection models; PML 1.0 for XL/2XL and Atto/Femto/Pico. No CPU or ONNX statement on that page. | A | `[V]` `[VENDOR]` |
| S3 | Towards Comprehensive Basketball Understanding (BasketballBench), arXiv 2608.23435, appendix B | Hu, Rao, Zhang, Di, Xie; 2026 | paper (preprint), university group | RF-DETR Medium fine-tuned on a 3,400-image, two-class (player, ball) set sampled from BasketEvent's original train/val/test partitions: 3,000/200/200 videos, one frame per video, 32,191 boxes; broadcast 1280x720 25 fps | Fine-tuned (576x576, 100 epochs, one RTX 3090 about 4 h): 0.6504 mAP@50:95, 0.8709 mAP@50 on the 200-image test set. Class-wise AP@50:95: basketball 0.5122 fine-tuned vs 0.1734 for the stock COCO "sports ball" mapped to basketball; player 0.7886 vs 0.6029. Mapping stock COCO classes gave 0.3882 mAP@50:95 overall. | A (preprint, not yet peer-reviewed as far as seen) | `[V]` |
| S4 | BasketEvent: Understanding Who Did What and When in Basketball Videos, arXiv 2607.21267 | Zhang, Rao, Wu, Xie; submitted 2026-07-23 | dataset paper (preprint) | NBA broadcast; 35k videos, 90.6 h, 51k player-level event samples (size from a search snippet); a 1,000-sample subset with event intervals (abstract page) | CC BY 4.0 per arXiv; authors say data, code and models "will be made publicly available" (not confirmed released). No ball-detection or make/miss numbers visible on the abstract page. | A | abstract `[V]`, sizes `[V-bib]`, release `[UNVERIFIED]` |
| S5 | Real-time CNN-based Segmentation Architecture for Ball Detection in a Single View Setup (BallSeg), arXiv 2007.11876 | Van Zandycke, De Vleeschouwer (UCLouvain); 2020 | paper, university group | 280 scenes from professional games in 30 arenas; cameras cover half a court; 65-265 px/m; 33 or 40 ms between the two consecutive frames; 1000 random crops per scene for evaluation | Input of two consecutive frames plus their difference raises detection accuracy (Fig. 4); top-1 rule at false-positive rate 0.01: true-positive rate 0.66 (text, "tpr=0.66 and fpr=0.33" as printed); "close to 70% detection rate" on unseen games and arenas; off-the-shelf Mask R-CNN "largely fails"; speed on GTX 1080 Ti, batch 2: 38.39 fps (1024x512 single image), 24.67 fps (+diff), 12.08 fps (1280x720, +diff). Dataset "made available" with the paper; licence not read. | A | `[V]` |
| S6 | Basketball Board Detection Using YOLO Algorithms, CEUR-WS vol. 3885 paper 26 | Sirmenis, Lukoševičius (Kaunas University of Technology); IVUS 2024 | workshop paper | 153 phone recordings (Samsung J5 and A52s) of free throws, camera about 45 degrees (plus or minus 10) to the ball position, labels board/rim/net/shooting box, resized 640x640; labelled and hosted in Roboflow; Colab GPU | Best YOLOv9-C: precision 0.996, recall 1.0, mAP@0.5 0.995, mAP@0.5:0.95 0.899 (validation set; the split method is not stated, so same-session leakage is possible). Fastest YOLOv7 about 15 ms per image (GPU type unnamed; Colab). Earlier classical method (Canny plus Hough) gave "disappointing" speed and accuracy. Ball is not a class; the paper's aim is counting free throws. | A (workshop) | `[V]` |
| S7 | TrackNetV3: Enhancing ShuttleCock Tracking with Augmentations and Trajectory Rectification, ACM MMAsia 2023 | Chen, Wang (NYCU); 2023 | paper, university group | TrackNetV2 badminton set: 23 training matches (172 rallies), 3 test matches (29 rallies); 720x1280 source, downsampled to 288x512 for evaluation | Table 1 accuracy / precision / recall / F1 / fps: YOLOv7 57.82 / 78.53 / 59.96 / 68 / 34.77; TrackNetV2 94.98 / 99.64 / 94.56 / 97.03 / 27.70; TrackNetV3 97.51 / 97.79 / 99.33 / 98.56 / 25.11. Uses an estimated background image and a rectification (inpainting) module that fills gaps using the trajectory before and after the gap. Badminton, broadcast court view, not basketball. | A | `[V]` |
| S8 | TrackNet, arXiv 1907.03698 | Huang, Liao, Chen, İk, Peng; 2019; no peer-reviewed venue on the arXiv page | paper (preprint) | Tennis, Universiade 2017 final; input 640x360 | Precision/recall/F1 99.7/97.3/98.5 on one video; 95.3/75.7/84.3 in 10-fold cross-validation. fps of the video and the speed are not stated. | A- (preprint) | `[V]` |
| S9 | TrackNetV4, arXiv 2409.14543 | Raj, Wang, Gedeon; 2024 | paper (preprint) | tennis and shuttlecock datasets | Motion attention maps improve V2 and V3; abstract gives no numbers, no basketball. TrackNetV5 (arXiv 2512.02789, Dec 2025, different group) exists; claims not read. | A- | abstract `[V]`, V5 `[V-bib]` |
| S10 | DeepSportradar (deepsport repository, README) | Van Zandycke et al.; CVPRW 2022 (3D ball localization) and MMSports 2022 (DeepSportradar-v1) | dataset/code | Ball 3D localization set: 233 samples; Keemotion cameras in basketball arenas | Code under CC BY-NC-ND 4.0; separate dataset terms not found on the page. Task is 3D ball position from a calibrated image, not 2D detection plus make/miss. | A | `[V]` (sizes and licence of code), dataset terms `[UNVERIFIED]` |
| S11 | The Impact of Frame-Dropping on Performance and Energy Consumption for Multi-Object Tracking, arXiv 2304.08152 | Henning, Buchholz, Dietmayer; IEEE IV 2023 | paper | KITTI 3D tracking (vehicles, pedestrians) | Dropping frames in tracking-by-detection saves up to 28% energy for a 6.6% HOTA decline. The abstract page has no accuracy-vs-frame-rate curve. A search snippet says an earlier study found a "significant performance drop below 10 Hz" for subsampled rates 25 to 1 Hz. | A | abstract `[V]`, the 10 Hz statement `[V-bib]` |
| S12 | Ultralytics YOLO11 docs | Ultralytics; 2024-2026 | official docs | COCO val2017, 640 px | YOLO11n 39.5 mAP50-95; 56.1 plus or minus 0.8 ms CPU (ONNX) and 1.5 ms T4 (TensorRT10), measured on an Amazon EC2 P4d host. Seen only through a search-result summary. | A | `[V-bib]` `[VENDOR]` |
| S13 | Counting Basketball Shot Attempts with Computer Vision (PoC), Theseus | thesis at a Finnish university of applied sciences; year not seen | thesis | not read (403) | Per search summary: two pretrained Roboflow models plus homography to call make/miss; worked on broadcast-style clips, struggled with amateur footage (poor court lines, camera motion, occlusion). | B | `[V-bib]` |
| S14 | Tracking the Blur: Accurate Ball Trajectory Detection in Broadcast Sports Videos, ACM MMAsia 2024 | authors not seen | paper | broadcast video, sport not confirmed | Per search summary: F1 91.49, accuracy 85.41, AP 91.16, recall 91.82 for ball trajectory detection. Page returned 403. | A (if confirmed) | `[V-bib]` |
| S15 | Šírmenis and Lukoševičius, single-camera practice-shot tracking, CEUR vol. 2915, IVUS 2021 | 2021 | workshop paper | one static camera, one shooter | Compares background subtraction and ball recognition; the page gives no numbers. Master's thesis by Šírmenis (KTU, 2025, 54 pages) compares YOLO versions for backboard/rim/net/ball on a single static stream; abstract has no numbers. | B | `[V-bib]` |

Excluded under the primary-and-academic rule (read as context only, not used as evidence): Roboflow blog "How to Build an AI Basketball Shot Evaluator" (vendor tutorial: RF-DETR-small on a fork of a University of Arizona dataset of about 9.8k images; the author reports makes logged as misses because the net hides the ball), an open-source GitHub shot tracker (77.7% end-to-end on 103 hand-labelled shots, 94% make/miss correct once a shot is found, 66.7% outdoors vs 88.5% indoors; self-reported, not reviewed), and all patents.

## 2. Findings by question

### Q1. Ball and rim detection from a single static camera; effect of low processing rate and blur
| Option / method | Evidence | Strength | Mechanism | Cost |
|---|---|---|---|---|
| Single-frame detector fine-tuned for basketball (RF-DETR M) | S3: basketball AP@50:95 0.5122 on broadcast 576x576, 2 classes | moderate (one preprint, broadcast, one frame per video, 200 test images) | appearance cues; fails when ball is tiny, blurred or hidden | one fine-tune, about 4 h on an RTX 3090 for 3,400 images (S3) |
| Rim detection (YOLOv5/7/9) | S6: mAP@0.5 0.995, mAP@0.5:0.95 up to 0.899 on 153 phone videos at 640x640 | moderate-high for rim as a static, large, high-contrast target; validation split unclear so optimistic | static object, large in image | labelling about 150 clips; cheap |
| Two-frame input with difference (BallSeg) | S5: input with frame difference "significantly improves" detection; about 70% detection rate on unseen arenas at low false-positive rate | moderate (university group, 280 scenes, half-court cameras, 30 arenas) | motion cue separates the ball from static clutter | segmentation net at 12 fps on a 2017 GPU at 1280x720 |
| Heatmap tracker with temporal stack and trajectory repair (TrackNet family) | S7: 97.51% vs single-frame YOLOv7 57.82% on badminton; S8 tennis F1 98.5 / 84.3 (single video / 10-fold) | strong for other sports; none for basketball | stacks consecutive frames plus background; fills gaps from before and after | needs frames at game rate and ball-position labels; 25-28 fps at 288x512 on the authors' GPU (hardware not read) |
| Stock COCO "sports ball" class | S3: 0.1734 AP@50:95 for basketball vs 0.5122 after fine-tuning | moderate (one measurement) | COCO includes mostly other balls and large balls | zero training, but not usable alone |

Camera and image size in the evidence: S5 half-court cameras at 65-265 px/m (ball 0.24 m would be about 16-64 px; `[UNVERIFIED]` arithmetic); S6 phones at 640x640 after resize; S3 broadcast at 576x576 after resize; S7 288x512 from 720x1280. No source reports ball pixel size on a high phone view like Pointr's.

Effect of 2-15 fps and blur:
- No study was found that measures basketball (or any ball) detection accuracy as a function of processing rate from 2 to 15 fps. This is an evidence gap, not a finding of "no effect".
- Motion blur is named as a difficulty for small fast objects in the TrackNet papers (S7 text on blur and ghost images; S9 abstract). TrackNetV3 reports that frame mixup did not help but video mixup did (S7), which is about augmentation, not frame rate.
- What can be said from geometry, `[UNVERIFIED]` arithmetic (not from a source): at an assumed ball speed of 8 m/s the ball moves about 1.6 m per processed frame at 5 fps, 0.8 m at 10 fps and 0.53 m at 15 fps; at 2 fps a 0.75 s close shot has 1 to 2 samples and a 2.1 s half-court shot has about 4. Two-frame methods (S5) assume frame gaps of 33-40 ms, so they do not transfer to 100-500 ms gaps without retraining.
- For multi-object tracking in general, S11 reports a modest HOTA loss for moderate frame dropping on KITTI, and a snippet cites a larger drop below 10 Hz (`[V-bib]`). Cars and people move far less per frame than a ball, so this does not bound the ball case.
- Practical reading: processing rate and capture rate are different. A phone can record at 30 fps while the live loop processes 2-10 fps; a post-session pass at full rate removes the low-rate penalty for H1 (see section 4).

### Q2. Datasets and pretrained models
| Resource | Labels | Size | Licence | Fit for Pointr | Mark |
|---|---|---|---|---|---|
| BasketEvent (S4) | player-level events, player and ball trajectories | 35k broadcast videos, 90.6 h, 51k events | CC BY 4.0 per arXiv; release "will be" public | broadcast view, wrong camera; use for pretraining only if released | `[V-bib]` / release `[UNVERIFIED]` |
| Detector set derived from BasketEvent (S3) | player, ball boxes | 3,400 images, 32,191 boxes | not stated; not confirmed released | same | `[V]` |
| UCLouvain / DeepSport ball-segmentation set (S5) | ball masks | 280 scenes, 30 arenas | not read | half-court arena cameras are the closest geometry found; ball only | `[V]` size, licence `[UNVERIFIED]` |
| DeepSportradar-v1 (S10) | 3D ball position, calibration, player masks, re-id | 233 ball samples in the ball task | code CC BY-NC-ND 4.0; data terms not found | calibrated arena views; non-commercial | `[V]` |
| KTU rim/board/net set (S6) | board, rim, net, shooting box | 153 phone clips, 640x640 | hosted on Roboflow, licence not read | phone, free-throw view; inside Roboflow Universe, so not outside it | `[V]` |
| SportsMOT | players only | 240 videos, 150k frames, 1.6M boxes (summary) | CC BY-NC 4.0 (summary) | players only, no ball or rim | `[V-bib]` |
| COCO "sports ball" | any ball | n/a | n/a | AP 0.1734 for basketball in S3; not usable alone | `[V]` |

Outside Roboflow Universe: no public dataset of a high, phone-quality, static view with ball and rim labels was found. The nearest academic items are S5 (ball only, arena cameras), S6 (rim, phone, but Roboflow-hosted) and S3/S4 (broadcast). Practical consequence: Pointr will need its own labelled frames from the December sessions; S3 suggests a few thousand boxes is enough to move the basketball class from 0.17 to 0.51 AP@50:95 on broadcast.

### Q3. Shot attempt and make/miss detection from video
| Approach | Published evidence found | Evaluation protocol | Strength | Mechanism | Cost |
|---|---|---|---|---|---|
| Trajectory-based (ball arc toward rim) | none peer-reviewed with a shot count; S13 thesis (pretrained models plus homography) reports failure on amateur footage | not read | weak | arc fit, ball crossing the rim plane | detector plus tracker only |
| Rim-region or net-motion classifier | only patents and a practitioner blog (excluded) | none | very weak | net deflection or ball slowing under the rim | small classifier on a rim crop; needs labelled makes and misses |
| End-to-end action recognition on clips | shot-type classification 96.8% on 1,500 shots (Olea et al., Vanderbilt/NOAH, `[V-bib]` via snippet); BASKET skill estimation (arXiv 2503.20781) is multi-class and not comparable | different task | weak for make/miss | clip classifier | video model, needs thousands of labelled shots |
| Event detection on broadcast (PlayNet in S3/S4) | S3 reports its use; accuracy for made vs missed shot not read | broadcast clips, 25 fps | unknown | tracks plus video | heavy |
| Audio of ball through net (Univ. of Siegen, ubi_bsn24) | a paper classifies outcomes from audio (`[V-bib]`, snippet only) | not read | unknown | ball hitting rim vs passing through net sounds different | microphone near the rim; could back up the rim sensor |
| Rim sensor (Pointr's hedge) | no academic source evaluated; timing note exists in `.suite/research/timing-and-make-window.md` | n/a | n/a | physical event | about 100 BRL |

No peer-reviewed paper was found that reports make/miss accuracy with a stated number of shots and camera view. Net occlusion of the ball is the recurring difficulty (S13 summary, excluded blog).

### Q4. Architecture patterns for adding classes to the person detector
| Pattern | Evidence | Strength | Mechanism | Cost and throughput |
|---|---|---|---|---|
| One multi-class RF-DETR (person, ball, rim) fine-tuned from the COCO checkpoint | S3 fine-tuned a two-class head from the official checkpoint; basketball AP@50:95 rose 0.17 to 0.51 | moderate | extra classes only change the classification head; the backbone cost per frame is the same | no extra inference; latency about 2.3-4.4 ms on a T4 for N-M (S1, `[VENDOR]`); risk is the person class regressing after fine-tuning (S3 saw person AP improve, 0.60 to 0.79, on broadcast) |
| Separate small ball detector (or crop around rim/court) | S5 and S7 show dedicated ball models gain from motion input and from full-resolution crops | moderate | higher effective resolution on the ball; independent frame rate | second model per frame; at 1280x720 the S5 two-frame net ran at 12 fps on a 1080 Ti; throughput roughly adds up (`[UNVERIFIED]` arithmetic) |
| Rim located once per session, then ball only | no paper tests it; S6 shows the rim is the easiest class (mAP@0.5 0.995) on fixed phone views | weak (reasoned, not measured) | rim is static if the tripod does not move; fixed pixel box lets a small crop classifier read net/ball events | saves no model time if the multi-class model already runs; saves false rim detections and allows a high-resolution rim crop; needs a drift check (re-detect every N frames, flag a shift) |
| Tile or crop the 1280x720 frame | no basketball paper found | n/a | RF-DETR Nano/Small run at 384/512 px (S1), so a 1280x720 frame is downscaled by 2.5-3.3 times and a ball of 12 px becomes about 4 px `[UNVERIFIED]` arithmetic | extra passes multiply cost |

### Q5. Hardware
| Detector | Hardware | Figure | Source and caveat |
|---|---|---|---|
| RF-DETR N/S/M/L | NVIDIA T4, TensorRT 10.4, FP16 (README), batch 1 | 2.3 / 3.5 / 4.4 / 6.8 ms at 384 / 512 / 576 / 704 px | S1, S2; `[VENDOR]` `[AFFIL]`; model forward only, 200 ms pause between passes so no sustained-throughput claim; not CPU |
| YOLO11 N/S/M | T4, TensorRT | 2.2 / 3.2 / 5.1 ms (S1 table) | S1, `[VENDOR]` figures in a third-party-run table |
| YOLO11n | T4 TensorRT10; CPU ONNX | 1.5 ms; 56.1 ms at 640 px | S12 `[V-bib]` `[VENDOR]`, EC2 P4d host CPU, not a laptop |
| BallSeg | GTX 1080 Ti, batch 2 | 12.08 fps at 1280x720 with frame difference | S5 `[V]` |
| TrackNetV3 | not named in the text read | 25.11 fps at 288x512 | S7 `[V]` |
| RF-DETR on CPU | none published in the pages read | not found | project measurement: 1.8-2.4 fps on the owner's CPU laptop (project data, not a source) |

Which GPU class: for two 720p streams at 10-15 fps total, the detector must run about 10-15 frames per second in total (5-8 per stream) or 20-30 if each stream runs at 10-15. Using the vendor T4 figures, RF-DETR Medium at 4.4 ms would use about 13% of a T4 at 30 detections per second, so a T4-class card (or a consumer GPU of the 2018+ generation) is enough for the model on paper (`[UNVERIFIED]` derived arithmetic from `[VENDOR]` figures). The observed 1.8-2.4 fps on CPU suggests that decoding, resizing, tracking and Python overhead may matter as much as the model; H2 should log time per stage, not only fps. No source was found for end-to-end pipeline throughput including decode and ByteTrack.

## 3. Dissent and caveats
- S3 is a preprint, evaluated on broadcast frames with one frame per video; broadcast shots show the ball larger than a high phone view, so 0.51 AP@50:95 is probably an upper bound for the ball class (`[UNVERIFIED]` inference).
- S6 has no stated split between train and validation clips; near-perfect rim mAP may be inflated by frames from the same video.
- S1 and S2 latency figures are vendor figures from the model's authors; S12 likewise. They exclude decode, resize and tracking.
- S7 is badminton at broadcast court view; its 97.5% should not be read as an H1 figure.
- Several sources were reached only through search summaries (S4 sizes, S11 snippet, S12, S13, S14, S15, Olea et al., Siegen audio paper). Those are `[V-bib]` and carry no weight in a decision.
- The arXiv ids 2607.21267 and 2608.23435 are dated 2026; they are recent preprints and may change.

## 4. Open questions
1. Ball pixel diameter on the actual phone view at 1280x720 (measure on a December frame); it decides whether 384-576 px inputs are enough or a crop is needed.
2. Basketball-specific accuracy of any detector at 2, 5, 10 and 15 fps: no source; measure by subsampling a recorded 30 fps session (post-hoc, cheap).
3. Whether the BasketEvent data and the S3 detector set are released, and under what licence.
4. DeepSportradar and S5 dataset licences.
5. Real make/miss accuracy from video on amateur footage: only unreviewed or excluded sources.
6. Whether the rim sensor can also be validated against an audio cue (Siegen paper not read).

## Options for the ADR

### A. How to add ball and rim detection
| Option | Evidence | Strength | Mechanism | Cost | Trade-offs |
|---|---|---|---|---|---|
| A1. Fine-tune the existing RF-DETR as one multi-class detector (person, ball, rim) from the COCO checkpoint | S3 (0.17 to 0.51 basketball AP@50:95, broadcast); S6 (rim near saturation) | moderate | one forward pass for all classes; head change only | one fine-tune plus labelling of a few thousand boxes from December sessions; no added latency; Apache 2.0 for N/S/M/L (S2) | person quality must be re-checked after fine-tuning; at 384-512 px input the ball may be about 4 px, so Small or Medium and the pixel size check matter |
| A2. A1 plus the rim fixed per session: detect the rim over the first N frames, store the median box, re-detect periodically and flag a shift | no paper; S6 supports an easy static rim | weak, reasoned | rim position is constant on a tripod | small code addition, no model cost | if a phone is bumped the stored rim is wrong; needs the drift check; makes rim detection errors vanish but not ball errors |
| A3. Separate ball model with temporal input (two-frame difference or TrackNet-style) alongside the person detector | S5 (about 70% at low false-positive rate, 2 frames at 33-40 ms), S7 (97.5% vs 57.8% single-frame, badminton) | moderate for other sports, none for basketball at 2-15 fps | motion cue and trajectory repair | second model, ball-position labels, retraining; gaps of 100-500 ms may break the two-frame assumption; extra GPU time | best candidate if A1 ball recall is low; do not start here |
| A4. Keep stock COCO "sports ball" | S3 (0.17 AP@50:95) | weak | none | zero | not recommended; only as a first baseline for comparison |

Recommendation: A1 with A2, measured first on a 30 fps recording subsampled to 2, 5, 10 and 15 fps; hold A3 as the fallback if the share of frames with the ball found misses the H1 needs. Confidence: medium-low. The direction (fine-tuning beats stock COCO) is supported by S3; the actual accuracy on a high phone view is unmeasured anywhere in the literature found.

### B. Where and when shot inference runs
| Option | Evidence | Strength | Mechanism | Cost | Trade-offs |
|---|---|---|---|---|---|
| B1. Live inside the processing loop | none specific; S11 and the geometry above show low rates reduce samples per shot | weak | decide make/miss as frames arrive | couples shot logic to the 2-10 fps loop; any bug stops perception; hard to re-score | lowest delay; worst accuracy at low fps; hard to compare against hand labels (FR-013) |
| B2. Separate layer over logged streams (per-frame ball/rim/person boxes, timestamps, sensor events), usable live by tailing the log and post hoc by replay | S7 shows rectification using frames before and after a gap helps (offline-friendly); project spec already logs per-frame data and scores against labels (FR-013) | moderate (architectural, plus S7) | shot rules read the log; a candidate shot can trigger re-detection on recorded video at full rate | log schema contract; one extra process; same code serves live and replay | live results arrive after the shot completes (a window of about 1-2 s); gives replayability for H1 scoring and rule tuning |
| B3. Post-session only | S7 (bidirectional rectification), S3 (offline tracking pipeline) | moderate | process stored 30 fps video with the best model, forward and backward smoothing | no real-time requirement; high accuracy for H1 | no live numbers (H8 is backlog anyway); results only after the session |

Recommendation: B2, with the post-session full-rate pass as the number that decides H1, and the live tail as a convenience only. Confidence: medium-high for the structure (it is driven by the constraints: videos are kept, FR-013 scores from logs, H8 is backlog), medium-low that a live tail will be accurate at 2-10 fps.

## RESULT
status: done
artifact: C:\Users\Glia-Produto\Desktop\pointr_vision\.suite\research\ball-rim-shot-detection.md
next: stage 3 (dev-model) ADRs for options A and B; measure ball pixel size and a subsampling test on one recorded session
open_questions: 6
