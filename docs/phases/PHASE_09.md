# Phase 09: Video lane and plans

## Goal
Two plans, enforced by the server. Video is locked on the basic plan and uploaded
resumably on the video plan when the account setting is on.

## Requirements
RF16, RF17, RF18, RF19, RF20, RNF10, RNF11, RN12.

## Scope
- Server: plans (`basic`, `video`) on the account, account-level `cloud_video` setting,
  entitlement endpoint. All checks server-side. No payment integration: plan changed by an
  admin command for the TCC.
- Object storage (Q-06) and video endpoints from `DATA_CONTRACTS.md` section 7.
- Client video lane: separate outbox lane; chunked upload; on restart query received chunks
  and continue from the first missing one; `complete` with sha256; mark synced only when
  the server verifies.
- Local copy removal only after verified upload and only if the user setting allows it
  (RF15).
- Locked video (RNF11): per-video data key, file encrypted at rest; key wrapped by the
  server and released only under the video entitlement (Q-05). Basic-plan UI lists the
  video as locked.
- Downgrade: cloud videos kept for `RETENTION_DAYS` (config, RN12), then purged by a job.

## Out of scope
Payment, streaming playback from the cloud, transcoding.

## Acceptance
| # | Criterion | Test |
|---|---|---|
| A1 | Basic account: video endpoints refuse with 403 even if the client sends requests | integration |
| A2 | Upload interrupted at chunk k resumes at k, final sha256 verified | integration |
| A3 | Corrupted chunk → `complete` reports mismatch, video not marked synced, local copy kept | integration |
| A4 | Repeated chunk upload does not duplicate storage | integration |
| A5 | Locked video file is not playable with a normal player | manual |
| A6 | Upgrade → locked video becomes playable in the app | manual |
| A7 | Downgrade → videos still retrievable until retention ends, purged after (time-mocked) | integration |

## Gate reviewers
All five.

## Milestone B
Full local-first platform: capture to cloud, both plans.
