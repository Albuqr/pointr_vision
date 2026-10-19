# 0004 — Ball and rim detection: one multi-class detector, rim fixed per session
status: accepted · date: 2026-10-19 (accepted by the owner)

## Context
FR-008 needs the ball and the rim detected in each processed frame, for H1 (shot attempts and make/miss) and H2 (throughput on a borrowed GPU PC). Today the detector keeps only the COCO person class (`services/edge/perception/detector.py`), runs at 1.8–2.4 fps on a CPU laptop (your own measurement), and `ARCHITECTURE.md` says changing a Protocol needs a `DECISIONS.md` entry. The research found no peer-reviewed accuracy figure for H1 from a single static phone, so H1 stays a `believe` until the December test.

## Options considered
| Option | Pros | Cons | Fit to NFRs |
|---|---|---|---|
| A1. Fine-tune the existing RF-DETR as one multi-class detector (person, ball, rim) from the COCO checkpoint | One forward pass for all classes; no extra latency; the N/S/M/L models are Apache 2.0; fine-tuning beat the stock COCO "sports ball" (AP 0.51 vs 0.17 on broadcast basketball) | Needs labelled boxes from December sessions; person quality must be re-checked; the ball may be about 4 px at 384–512 px input | NFR-001 neutral; NFR-003 compatible |
| A2. A1 plus the rim treated as fixed: detect it over the first N frames, store the median box, re-detect periodically and flag a shift | Removes rim errors; no model cost | No paper tests it; a bumped phone makes the stored rim wrong, so it needs the drift check | Weak evidence, low cost |
| A3. A separate ball model with temporal input (two-frame or TrackNet style) beside the person detector | About 70% ball detection rate at low false positives on unseen arenas (BallSeg, 2 frames 33–40 ms apart) | Second model, more labels, extra GPU time; gaps of 100–500 ms may break the two-frame assumption; no basketball result at 2–15 fps | Best fallback if A1 ball recall is low |
| A4. Keep the stock COCO "sports ball" class | Zero work | AP 0.17 on basketball | Baseline for comparison only |

## Decision
Decided (owner, 2026-10-19): **A1 with A2**, measured first: subsample one recorded 30 fps session to 2, 5, 10 and 15 fps and measure the ball's pixel size before any fine-tuning. A3 is the fallback if the share of frames with the ball found misses what H1 needs. The perception layer emits class-tagged boxes; ByteTrack stays person-only, and ball and rim detections go to the shot layer (ADR 0005) without passing through the tracker.

## Consequences
- Contract: ball and rim boxes need a new file (`objects.csv`) so `tracks.csv` keeps person tracks only; bump from 0.10.0.
- New training and labelling workflow and a dataset licence check: BasketEvent's release is only promised (CC BY 4.0 per arXiv), DeepSportradar's code is CC BY-NC-ND 4.0. A new dependency, so the owner must approve it (`CLAUDE.md` rule 8).
- The CPU laptop cannot run H2. The H2 baseline on the borrowed GPU PC logs time per stage, because decode and tracking may dominate the model's forward time.
- Confidence: medium-low. The direction is supported; accuracy on a high phone view is unmeasured anywhere found.

## Sources
- [BasketballBench: fine-tuned RF-DETR on basketball (Hu et al., 2026)](https://arxiv.org/abs/2608.23435) · tier A, preprint · broadcast frames, 200 test images
- [BallSeg: real-time ball detection in a single view (Van Zandycke and De Vleeschouwer)](https://arxiv.org/abs/2007.11876) · tier A, university group · 280 scenes, 30 arenas
- [TrackNet: tennis ball tracking from broadcast video (Huang et al., 2019)](https://arxiv.org/abs/1907.03698) · tier A, preprint
- [RF-DETR: neural architecture search for real-time detection transformers (Robinson et al., 2025)](https://arxiv.org/abs/2511.09554) · tier A, ICLR 2026 per arXiv comments
- Research note: `.suite/research/ball-rim-shot-detection.md`
