---
name: remotion-prompt
description: Translate a user's video-editing or motion-design brief into a precise, Remotion-ready build prompt (route, spec, beats, copy, technique, negatives, plus a Remotion implementation map), then build it in the Remotion project. Use when a user describes a video they want created, edited, animated, captioned, recut, or turned into a promo and the brief needs clarification before execution. Ask no more than five targeted questions, then produce the final prompt even when some details must be inferred.
---

# Remotion Prompt Skill

Turn an informal video request into a processable, Remotion-ready prompt, then (when asked) implement it as a React composition. Treat the user's intent as authoritative, preserve exact wording, and make visual decisions only where the user leaves gaps.

Remotion videos are React components rendered frame by frame. Every visual must be a pure function of `useCurrentFrame()`. Never use CSS transitions, CSS animations, `setTimeout`, or `Math.random()` for motion; they will not render correctly. Plan the prompt so it maps onto Remotion primitives.

## Project

The Remotion project lives in the project's Remotion folder: `remotion/` or `.suite/media/remotion/` (Remotion 4.x, React, TypeScript). Use it only when the project already uses Remotion; otherwise the media-kit default is HyperFrames. Screen recordings come from `suite media record` / `suite media clip` (`.suite/media/clips/`), music from `suite media bgm`.

- Entry: `remotion/src/index.ts` calls `registerRoot(RemotionRoot)`; compositions are registered in `remotion/src/Root.tsx`.
- Preview: `cd remotion && npm run dev` (Remotion Studio).
- Render video: `npx remotion render src/index.ts <CompositionId> out/<name>.mp4`
- Render still: `npx remotion still src/index.ts <CompositionId> out/<name>.png --frame=<n>`
- Installed packages: `remotion`, `@remotion/cli`, `@remotion/bundler`, `@remotion/renderer`, `@remotion/transitions`, `@remotion/captions`, `@remotion/media`, `@remotion/google-fonts`, `@remotion/shapes`, `@remotion/paths`.
- Add others on demand with `npx remotion add <pkg>` (e.g. `@remotion/media-utils`, `@remotion/lottie`, `@remotion/three`, `@remotion/noise`, `@remotion/motion-blur`, `@remotion/layout-utils`, `@remotion/install-whisper-cpp`, `@remotion/gif`). Keep all `@remotion/*` versions identical to `remotion`.
- Put source media in `remotion/public/` and reference it with `staticFile("name.mp4")`.

## Capturing a website (product launch footage)

Screen recordings come from the Playwright project in `capture/`. Claude cannot type passwords, so the user signs in by hand once.

1. Login (user does this): `cd capture && npm run login -- <login-url>`. A browser opens, the user signs in (including 2FA) and presses Enter. The session is saved to `capture/auth/state.json` (git-ignored). Skip this for public sites.
2. Plan the flow: write `capture/flows/<name>.json` with steps `goto`, `click`, `hover`, `type`, `press`, `scroll`, `wait`, `screenshot` (target by `selector` or visible `text`; optional `pause` ms after each step). Set `"useAuth": true` for logged-in flows. Look at `flows/example.json`. Ask before any step that submits data or changes the account, and never type credentials.
3. Record: `npm run record -- flows/<name>.json` produces `capture/recordings/<name>/<name>.webm` (1920x1080 default, visible cursor and click ripples are injected).
4. Convert: `npm run convert -- <name>` writes `remotion/public/<name>.mp4` (30 fps H.264).
5. Build: use the `ProductDemo` composition in `remotion/src/ProductDemo.tsx` (props: `clip`, `clipSeconds`, `headline`, `cta`, `accent`, optional `focus` punch-in) or a new composition. Set `clipSeconds` to the real clip length, then check frames with `remotion still` and render.

Notes: Playwright records at about 25 fps VP8, which is fine for UI demos. For selectors that fail, add a `wait` step or use `text`. Re-record rather than trimming if a step misfires.

## Workflow

1. Read the entire brief before asking anything.
2. Select the best route. If the user names a route, keep it unless it clearly conflicts with the task.
3. Map the brief to the six decisions below.
4. Ask only about high-impact missing decisions: at most five questions total, in one compact batch. If the brief is specific enough, ask zero.
5. After the user answers, fill any remaining gaps with sensible assumptions. Do not start another round.
6. Return the final prompt (see Output contract).
7. If the user wants the video built, implement it using the Remotion map below, preview with a `remotion still` check at key frames, then render.

## Six decisions

### 1. Route

Begin with the workflow that should handle the request. Choose the closest fit and the dominant work, not every supporting technique.

| Route | Use for | Core Remotion pieces |
| --- | --- | --- |
| `/motion-graphics` | Short design-led animation, kinetic type, stats, charts, logo stings, graphic transitions | `spring`, `interpolate`, `Easing`, `Sequence`, `@remotion/shapes`, `@remotion/paths` (`evolvePath`), SVG |
| `/product-launch-video` | Product, feature, SaaS, app, marketing promo | `TransitionSeries`, `Img`, `staticFile`, device mockups in CSS, `@remotion/google-fonts` |
| `/talking-head-recut` | Existing interview, podcast, talking-head footage with designed overlays | `OffthreadVideo` or `Video` from `@remotion/media`, `Sequence` overlays, `trimBefore`/`trimAfter`, `playbackRate` |
| `/embedded-captions` | Captions on an existing single-subject video | `@remotion/captions` (`Caption` type, `createTikTokStyleCaptions`), word-level timing, `Sequence` per page |
| `/faceless-explainer` | Text, narration, or a topic turned into a faceless explainer | `Series`, `Audio`, `calculateMetadata` for narration length, `TransitionSeries`, shapes/SVG diagrams |
| `/music-to-video` | Music-led, lyric, or beat-synchronized edit | `Audio`, `visualizeAudio` / `getAudioData` (`@remotion/media-utils`), beat arrays converted to frames |
| `/pr-to-video` | GitHub PR or code change turned into an explainer | Code panels with syntax-highlighted text, diff reveals via `interpolate`, `Series` |
| `/slideshow` | Deck-like sequence of discrete slides | `Series` or `TransitionSeries` with `fade`, `slide`, `wipe`, `flip`, `clockWipe` presentations |
| `/general-video` | Custom edit that fits none of the above | Any combination; stills via `<Still>` for single images |

Routes ending in `-video` that expect Remotion output keep the same names so briefs stay portable between HyperFrames and Remotion.

### 2. Spec

Capture duration and canvas: length, aspect ratio or destination, and optionally frame rate or resolution.

- TikTok/Reels/Shorts imply 1080x1920 (9:16). YouTube implies 1920x1080 (16:9). Square implies 1080x1080. Feed 4:5 is 1080x1350.
- Default frame rate is 30 fps; use 60 only when the brief asks for very smooth motion.
- Convert seconds to frames for `durationInFrames` (seconds x fps). State the result in the prompt.
- If duration is missing, infer a practical length from the content and state the assumption outside the prompt. Ask if it materially changes the edit.
- Delivery format: MP4 (h264) by default; transparent overlay means WebM (VP8/VP9 with alpha) or ProRes 4444; a looping graphic may mean GIF; a single frame means `<Still>`.

### 3. Beats

Describe what happens on screen chronologically, second by second or phase by phase: source-footage moments, entrances, exits, reveals, transitions, emphasis, ending state. Use approximate timing when exact timing is unavailable. For existing footage, distinguish what must remain from graphics to add. Each beat will become a `Sequence`, a `Series.Sequence`, or a `TransitionSeries.Sequence`, so keep beats self-contained.

### 4. Copy

Preserve all user-supplied words exactly. Put on-screen text, titles, labels, captions, CTA language, and required spoken lines in quotation marks. Never silently rewrite, correct, shorten, or paraphrase. If no copy was supplied, describe the copy direction without fabricating final words. In code, pass copy through composition `defaultProps` (optionally validated with a `zod` schema) so it can be edited in Studio without touching layout.

### 5. Technique

Name concrete visual and motion choices, preferring ones Remotion expresses cleanly: spring entrance with a damping value, ease-out via `Easing.out(Easing.cubic)`, staggered reveals using frame offsets, masked reveal with `clipPath`, kinetic typography with per-word `Sequence`, odometer count-up via `interpolate`, parallax with layered `AbsoluteFill`s, punch-in with animated `scale`, path drawing with `evolvePath`, highlight sweep, waveform from `visualizeAudio`, progress bar, color accent, grain overlay, hold on the end card. Pick a small coherent set rather than a grab bag. Load fonts with `@remotion/google-fonts` so renders are deterministic.

### 6. Negatives

State what to omit, especially constraints that protect source material or brand: no narration, no music, no stock footage, no media files, no invented logos, no extra text, no jump cuts, no heavy effects, no background replacement, no color change to the footage, no captions if unwanted. Convert explicit user constraints into negatives. If none are stated, add only safe defaults: "no invented copy, no unrequested assets, no extra scenes."

## Question policy

Ask only when the answer would materially change the route, runtime, story order, exact copy, source-footage treatment, or delivery format. Prioritize these five categories and combine related gaps:

1. Destination, aspect ratio, approximate duration, and delivery format (MP4, transparent overlay, GIF, still)?
2. Which source media must be used, and what may be added or changed?
3. What happens in sequence, especially the opening hook and the ending?
4. What exact on-screen copy, captions, CTA, or spoken words are required?
5. What visual style, motion behavior, audio treatment, or exclusions matter most?

Make it easy to answer in one reply, for example: "1. Is this a 10-15 second vertical Reel (MP4), or another duration/format? 2. Only the supplied footage, or may I add graphics and music? 3. What exact text must appear? 4. Calm and premium, or fast and energetic? 5. Anything to exclude?"

## Output contract

After intake, return in order:

1. A short "Assumptions" sentence, only if you had to infer an important detail.
2. A single paragraph beginning with the route, in this order: `[route]. [spec]. [beats]. [exact copy in quotes]. [technique and visual direction]. [negatives].`
3. A compact "Remotion map" line listing the composition id, size, fps, `durationInFrames`, the primitives each beat will use, and the render command. Include it whenever the user wants the video built, and optionally otherwise.

Do not expose an empty checklist as the prompt. Do not put the route in a heading or the prompt in a code block unless the user asks for a copyable block. The paragraph should read as if someone texted the brief to a video-making agent.

## Implementation rules (when building)

- One composition per deliverable, registered in `src/Root.tsx` with explicit `id`, `width`, `height`, `fps`, `durationInFrames`, and `defaultProps`.
- Drive all motion from `useCurrentFrame()` and `useVideoConfig()`. Use `interpolate` with `extrapolateLeft/Right: "clamp"` and `spring` for natural settle.
- Sequence time is local: inside a `<Sequence from={n}>`, `useCurrentFrame()` restarts at 0.
- Use `OffthreadVideo` (or `Video` from `@remotion/media`) for footage, `Audio` for sound, `Img` for images; never raw `<video>`, `<audio>`, or `<img>`.
- Overlap scenes with `TransitionSeries`; remember each transition shortens total duration by its length, so set `durationInFrames` accordingly (or compute it in `calculateMetadata`).
- Derive length from media (narration, source footage) with `calculateMetadata` rather than hard-coding when the asset is supplied.
- Captions: transcribe to the `Caption[]` shape, group with `createTikTokStyleCaptions`, render one `Sequence` per page, and highlight the active word by comparing the current time to each token.
- Check key frames with `npx remotion still ... --frame=N` before rendering the full video. Fix text overflow and safe-zone issues (keep captions and CTAs clear of platform UI in vertical formats).

## Quality checks

Before handing off, verify:

- The first token is a valid route such as `/motion-graphics`.
- The opening sentence states duration and format, or clearly signals an assumption.
- Beats are chronological and describe visible action.
- Exact copy is quoted and unchanged.
- Technique describes intentional motion/design choices, not vague adjectives alone, and each is achievable with Remotion primitives.
- Negatives include the user's exclusions and do not contradict the requested edit.
- No more than five clarification questions were asked.

## Example transformation

Brief: "Make my 12-second product clip feel premium for Instagram. Start with the product shot, bring in the price, then end on the logo. Use my footage only; no voiceover."

After asking only for missing high-impact details, produce something like:

/product-launch-video. 12-second vertical 9:16 Instagram Reel, 1080x1920 at 30 fps (360 frames), MP4. Open on the supplied product shot for two seconds, ease into a clean price reveal, hold the product while the end card assembles, and finish on the supplied logo. Show the exact price copy in quotes when provided and keep the logo wording unchanged. Use a restrained premium palette, soft shadow, masked text reveal via clipPath, a gentle punch-in with an animated scale, and a spring settle on the end card. Use only the supplied footage and logo; no voiceover, no stock footage, no invented copy, no unrequested assets.

Remotion map: composition `ProductReel`, 1080x1920, 30 fps, 360 frames. Beat 1 `OffthreadVideo` in a `Sequence`; beat 2 price text with `spring` and `clipPath`; beat 3 end card with `Img` logo and `spring`. Render with `npx remotion render src/index.ts ProductReel out/product-reel.mp4`.
