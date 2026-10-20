---
name: media-kit
description: Produce a project's media kit — launch/demo/explainer video, vertical cuts, stills and copy — from the real product. The agent writes the brief, script, storyboard and recording flows; deterministic tools do the rest (suite media record/clip/bgm for capture, trimming and music; the pinned HyperFrames CLI for TTS, transcription, captions and render). HyperFrames by default, Remotion when the project already uses it. Use after requirements are approved, or whenever a video, promo, demo or motion graphic is needed.
---

# Media kit

**The AI does:** brief, script, storyboard, recording flows (JSON) and the composition.
**Code does:** capture, trim, music, TTS/transcription, captions and render. Never generate with a model what a tool produces deterministically.

## Setup (once per machine / project)
- `suite media setup` installs Playwright for recordings (into the suite's `media/`, not your project) and creates `.suite/media/flows/`.
- FFmpeg on PATH (`suite doctor`).
- HyperFrames skills for every provider: `npx skills add heygen-com/hyperframes`. The CLI needs no install. Pin it per project, e.g. `npx --yes hyperframes@0.8.133 render`.

## Procedure
1. **Brief** (`.suite/media/BRIEF.md`): audience, one message, CTA, duration, aspect ratios (16:9, 9:16, 1:1), brand tokens. Take the message from the decision record or spec. No new claims.
2. **Script & storyboard.** Use at most ~150 words per minute of voiceover and one idea per scene. List scenes with durations, and name which screen recording each scene needs.
3. **Record the real product** — no mocks:
   - Logged-in flows: `suite media login <url> <profile>`, once. You sign in by hand; the session is saved, and `auth/` is gitignored.
   - Write one flow per scene in `.suite/media/flows/<scene>.json`, using the actions in `media/flow.example.json`: goto, click, type, scroll, hover, mark start/end, waitFor, map helpers…
   - `suite media record .suite/media/flows/<scene>.json` produces a 60 fps capture on Windows, with a synthetic cursor and click ripple.
   - `suite media clip <scene>` trims to the `mark` points and writes `.suite/media/clips/<scene>.mp4`.
   - E2E screenshots in `.scratch/<feature>/e2e/` are valid stills too.
4. **Audio.**
   - Music: `suite media bgm --seconds <n> --bpm 72` generates a licence-free ambient bed procedurally.
   - Voiceover: write the script to `.suite/media/vo-script.md`, then generate it with the HyperFrames TTS (`hyperframes tts`; see `/hyperframes-cli`) or your TTS provider.
   - Captions and timing: `hyperframes transcribe`. Captions are required for prerecorded audio (WCAG 1.2.2).
5. **Compose.**
   - **HyperFrames (default):** start at `/hyperframes`, which routes to `/product-launch-video`, `/faceless-explainer`, `/motion-graphics`… Put the project in `.suite/media/<video-name>/` with its own `package.json` pinning the CLI version.
   - **Remotion:** only if the project already has a Remotion setup. Remotion has commercial licence terms for companies; check them.
   - Keep compositions deterministic: no unseeded randomness, no network at render time.
6. **Render** every aspect ratio with the pinned CLI (`render`, `check` first). Outputs go in `.suite/media/out/`.
7. **Kit** (`.suite/media/out/`): videos, 3 stills (thumbnail, OG 1200×630, square) and copy (one-liner, 50 words, 150 words).

## Gate
- The message is understandable with sound off, and captions are present.
- Every number or claim in the video traces to the spec, decision record or real product.
- Every render is reproducible from source with the pinned CLI, and every clip from its flow JSON.
- The human approved the final cut.
