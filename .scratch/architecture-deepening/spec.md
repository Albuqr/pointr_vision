# Spec: architecture deepening (Phase 03 bugs + R2a follow-up)

Status: ready-for-agent · 2026-10-30 · brief: `.scratch/architecture-deepening/brief.md` ·
multi-agent plan: `.scratch/architecture-deepening/coordination.md`

## Problem Statement

The operator starts sessions from Studio. They get different results for the same situation, depending
on whether they record one camera or a group:
- A refused calibration stops a single camera before it records, but a camera in a group records
  uncalibrated.
- A model that fails to load shows up in Studio as a generic "failed to start" for one camera, but with
  the real reason for a group.
- A Studio stop during group setup ends the session in error, although stops are meant to end it cleanly.

There are also failures the operator cannot explain:
- Studio will not start at all if the folder named in its active-group pointer holds a `session.json`
  that is not a JSON object.
- A camera that is recording is shown as failed after another camera in its group prints an error.
- A group replay can come out "calibrated" with no court positions and no event saying why.
- Calibrations saved under contract versions 0.14 to 0.18 are refused although their format never changed.

The developer, and the coding agents working for them, pay for the same problems every day:
- How a run starts and ends is written three times (single camera, group, group replay). The copies
  have drifted.
- Calibration is loaded, validated and converted in four places, each with its own refusal behaviour.
- The session folder is parsed by hand in about eleven places, each handling damaged files its own way.
- The status lines the edge prints to Studio are typed out by hand in several files and recognised by
  substring.
- A contract version bump touches about fifteen files.

On 2026-10-29 these overlaps made four parallel branches collide on the same files. A line-ending
mismatch rewrote about 2,000 lines in one commit.

## Solution

Two layers of work, in order.

**First, Phase 03 bug fixes.** Each one has a failing test written first. They land quickly:
- Studio and the edge tolerate damaged session files.
- A camera is not marked failed by an error printed after it started recording.
- A single-camera model-load failure reaches Studio with its reason.
- A Studio stop during group setup ends the group cleanly.
- A replay calibration that cannot be used is recorded as an event.
- Saved calibrations from 0.14 to 0.18 load again.

**Then the R2a follow-up: refactors that deepen a few modules,** so that each concept lives in one place:
- **Contract version.** One module owns it. Schemas carry no version, and a bump touches three files.
- **Calibration intake.** One module decides whether a calibration can be used, for every entry point and
  for Studio. A single camera follows the same rule as a group: a refused calibration records
  uncalibrated, with the refusal written as a failed calibration startup check.
- **Session folder.** One reader serves every caller and tolerates damage the same way everywhere.
- **Status lines between edge and Studio.** One protocol module emits and parses them, with typed
  failure kinds. The protocol is documented as a contract section.
- **Camera pipeline.** It exposes a small interface (lifecycle, stats snapshot, live views) instead of its
  parts.
- **One run module** runs one or more cameras, live or replay. A single camera is a group of one, and the
  command-line entry points only parse arguments.

From the operator's side nothing changes except the fixes and the more consistent single-camera
behaviour. Output files stay readable by today's readers, apart from the documented contract changes.

## User Stories

### Operator
1. As an operator, I want Studio to start even if a session folder on disk is damaged, so that one bad folder does not stop me recording a practice.
2. As an operator, I want the sessions page and recording status to show a damaged session with the reason it is damaged, so that I know what happened instead of seeing an error page.
3. As an operator, I want a camera that is recording to stay "recording" in Studio when another camera in the group prints an error, so that I do not stop a good recording by mistake.
4. As an operator, I want a camera's failure in Studio to say what kind of failure it was (source could not open, model could not load, calibration refused, start timed out, process exited), so that I know what to fix.
5. As an operator, I want a model that fails to load on a single camera to show its real reason in Studio, as it does for a group, so that I am not left with "failed to start (exit N)".
6. As an operator, I want a stop from Studio during group setup to end every camera's session cleanly with a "stopped" event, so that a stop is never recorded as an error.
7. As an operator, I want a single camera whose calibration is refused (wrong size, wrong camera, unreadable file) to start recording uncalibrated with a recorded reason, as a group camera does, so that a failed startup check never blocks the start.
8. As an operator, I want a calibration refused by the edge to be recorded the same way as one I refused myself in Studio, so that the session always shows a failed calibration check for either cause.
9. As an operator, I want a camera whose first frame is a different size from its calibration to still end that camera with a clear error, so that a camera that changed resolution mid-setup is never recorded with wrong positions.
10. As an operator, I want calibrations I saved under earlier versions with the same calibration format to keep loading, so that I do not have to recalibrate at the court after an update.
11. As an operator, I want Studio's warning about an unusable calibration before start to give the same verdict as the edge, so that what Studio warns me about is what actually happens.
12. As an operator, I want Studio's calibration fit to reject a bad fit with a reason instead of an internal error, so that I can retry or start uncalibrated.

### Coach and data consumer
13. As a coach, I want a replayed group to use the same calibration as the live run, or to record why it could not, so that court positions in replays are comparable with the live data.
14. As a coach, I want a single-camera replay to use the live run's calibration by default, so that replaying a session reproduces its positions.
15. As a coach, I want a group replay whose saved calibration cannot be used to record that as an event, not to look calibrated with empty positions, so that I do not read a missing shot map as "no shots".
16. As a data consumer (fusion and the scoring tool), I want a camera that did not use its calibration to always carry a failed calibration check, so that excluding uncalibrated cameras needs only one field.
17. As a data consumer, I want a single camera's run to keep writing no group block and "unshared" links, so that existing reports and fusion read single-camera sessions as before.
18. As a data consumer, I want track IDs, links, events and counts from a single camera to be unchanged by the refactor, so that sessions recorded before and after it compare directly.

### Developer (owner)
19. As the developer, I want a contract version bump to touch only the version constant, the contract document header and the decision record, so that bumps are small and never conflict across branches.
20. As the developer, I want schemas to live in one packaged copy, so that the runtime and the tests can never validate against different schemas.
21. As the developer, I want calibration compatibility declared as a calibration format range, separate from the contract version, so that an unrelated bump never makes saved calibrations unreadable.
22. As the developer, I want the contract module to validate a document and its version in one call, so that every writer and test uses the same check.
23. As the developer, I want the contract document's example blocks checked against the current version, so that the docs cannot drift silently.
24. As the developer, I want one calibration intake module that every entry point and Studio calls, so that a refusal rule is fixed once.
25. As the developer, I want the calibration intake to never raise and instead return the calibration or a refusal with the events and checks to write, so that callers cannot forget to record a refusal.
26. As the developer, I want the calibration's legacy `kind`/`type` alias resolved once at intake, so that no other module patches it.
27. As the developer, I want a calibration rebuilt from a run's saved block to be checked like one loaded from a file, so that replays cannot skip validation.
28. As the developer, I want one session-folder reader that returns a snapshot with every field optional and a list of problems, so that every caller tolerates damage the same way.
29. As the developer, I want callers that need certain fields to ask the reader for them and get one clear "session damaged" error, so that strict paths like replay refuse cleanly.
30. As the developer, I want "the latest run" of a session defined once, so that Studio, the launcher and the reports agree on which run they show.
31. As the developer, I want marking an interrupted session to live in one place, so that Studio's recovery and the writer cannot diverge.
32. As the developer, I want one protocol module that emits and parses every status line between edge and Studio, including the stop channel, so that the wire strings exist in one place.
33. As the developer, I want error lines to carry a typed failure kind, with old lines still parsing, so that Studio stops guessing from substrings.
34. As the developer, I want an error printed after a session opened never to count as a start failure, so that run-time problems are session events, not start failures.
35. As the developer, I want the protocol written down as a contract section, so that the Studio–edge interface is versioned like every other format.
36. As the developer, I want the camera pipeline to expose a stats snapshot, its lifecycle and its live views, so that callers stop reaching into capture, processor and writer.
37. As the developer, I want live and replay input to be one value chosen when the session opens, so that the replay flag stops spreading through constructor arguments.
38. As the developer, I want the session writer interface to state everything the pipeline actually relies on, so that the writer seam is real and another adapter could fill it.
39. As the developer, I want run metadata built from a small settings value instead of the parsed command line, so that tests do not parse fake arguments to get defaults.
40. As the developer, I want the model-loaded time passed when run metadata is built, so that three callers stop patching it afterwards.
41. As the developer, I want device and model loading written once, so that a load failure is reported the same way on every path.
42. As the developer, I want the stop policy (Studio stop vs Ctrl+C, at any phase) defined in one table, so that every path maps a stop to the same status, event and exit code.
43. As the developer, I want one run module that takes a plan of one or more cameras, live or replay, and runs it, so that a change to run start or end is made once.
44. As the developer, I want a single camera to run as a group of one without the matcher and without a group block, so that one path serves both cases without changing single-camera output.
45. As the developer, I want a single camera's status lines to stay untagged, so that the launcher keeps finding its session line.
46. As the developer, I want the command-line entry points reduced to argument parsing plus one call, so that they cannot drift again.
47. As the developer, I want groups to accept the benchmark option, so that group speed can be measured the same way as single-camera speed.
48. As the developer, I want a benchmark recorded on the same clip before and after a single camera moves onto the group path, so that any speed change is measured, not claimed.
49. As the developer, I want shared test fakes in one place, so that tests do not import from other test modules.

### Coding agents (Claude, Codex, Antigravity working in parallel)
50. As a coding agent, I want every ticket to name the files it owns and the files it may touch only in named functions, so that parallel branches do not conflict.
51. As a coding agent, I want decision numbers reserved per ticket, so that two branches never pick the same one.
52. As a coding agent, I want line endings fixed repo-wide before any branch is cut, so that my editor cannot cause whole-file diffs.
53. As a coding agent, I want each new deep module built in a new file before callers are switched, so that the parallel work cannot conflict.
54. As a coding agent, I want the bug fixes' tests to land before the refactors, so that the refactors have regression tests to keep green.
55. As a coding agent, I want a characterisation test of today's run behaviour before the run module is built, so that I can see exactly which differences are intended.

## Implementation Decisions

### Scope and order (owner, 2026-10-30)
- The bug fixes are Phase 03 work. The refactors are an "R2a follow-up": PHASES.md gets an entry and the decision record gets an entry (D-063) when the line-ending normalisation lands.
- Line endings are normalised to LF repo-wide in one whitespace-only commit, before any other branch. That commit is listed in the blame-ignore file.
- Merge order, lanes, file ownership and reserved decision numbers are in `coordination.md`. That file binds every agent.

### Contract module
- The contract module owns the contract version, the calibration format version, schema loading (one packaged copy, cached), validation of a document plus its version, and calibration acceptance by format range.
- Schemas no longer embed the version (owner decision 2). The `contract_version` field keeps a semver pattern, and schema identifiers drop the version.
- Version comparison is numeric per part, never string comparison.
- Calibration acceptance is a table that maps a calibration format to the range of contract versions that wrote it. It replaces the hand-kept list of accepted versions and makes 0.14–0.18 acceptable.
- This refactor is a contract change: 0.22.0, with a decision entry amending D-009 and D-027.
- After it, any later contract change takes the next free version at rebase time.

### Calibration intake module
- Interface: one function. It takes an offer of calibration, the camera ID and the capture size, and returns an intake verdict. It never raises on content.
  - The offer is one of: from a calibration file, from a run's saved block, refused by the operator (with reason), not usable per Studio (with problem), or none.
  - The verdict holds the usable calibration (or none), the events to write, the run's startup checks, and the reason the edge itself refused, if it did.
- The runtime calibration is one immutable type. It resolves the legacy `kind`/`type` alias once and produces the session block, the run block and the preview court.
- Invariants:
  - A calibration in the verdict has been validated and matches the capture size.
  - A run block read back and produced again is unchanged.
  - A calibration from a run block goes through the homography check.
- Building a calibration document from fitted points lives in the same module, for Studio's fit.
- Refusal policy (owner decisions 6 and 8):
  - A calibration refused when the source opens means the camera records uncalibrated, on every path, single camera included.
  - The refusal is recorded as a failed calibration startup check (the run's checks plus the startup-check-failed event), exactly as for an operator refusal. This changes the meaning of the run's checks, so it is a minor contract bump.
  - A first-frame size mismatch still ends that camera (D-059). The decision entry says why it differs from a refusal at open.
- A single-session replay uses the live run's calibration, and an explicit calibration argument overrides it (owner decision 9).
- Studio keeps validating before start, through the same function, in-process. The verdict still reaches the edge as process arguments, because Studio and the edge are separate processes.

### Session-folder reader
- Interface:
  - Read a session.
  - Read a run.
  - Find sessions in the output folder by group or session ID.
  - Each read returns an immutable snapshot with every field optional plus a list of problems. Reads never raise on content.
  - A `require` call on the snapshot raises one "session damaged" error for strict callers.
- "Latest run" is defined once, as the last entry of the session's run list.
- The text encoding policy is the same for every reader (tolerates a byte-order mark).
- Marking a session interrupted lives in this module. Studio's recovery uses it.
- It lives in the edge package. Studio already depends on the edge package, so the dependency direction does not change.

### Edge–Studio protocol module
- Typed messages over the existing text wire:
  - session opened
  - device chosen
  - preview listening
  - start failed (kind, detail)
  - summary
  - stop (source)
- Emit owns the camera prefix, line splitting, credential masking and the output stream. Parse returns the camera (or none) and the message (or none for free text).
- Failure kinds: source open failed, model load failed, calibration refused, configuration conflict, start timeout, spawn failed, exited. The wire form is `error: <kind>: <detail>`. A line in the old form parses as "exited" (owner decisions 14 and 15).
- Invariant: an error after the session-opened line is never a start failure.
- The protocol becomes a new contract section, §16, with a minor bump and a decision entry. The glossary gains "launcher", "child" and "stop channel".

### Camera pipeline
- Interface:
  - Lifecycle: open session, start, done, stop (returns status), error.
  - Event logging.
  - Session and run directories, and status.
  - A stats snapshot: every capture, processing and recording counter, exact after stop.
  - Live views: health state, HUD, latest processed frame, raw snapshot, calibration.
  - Preview callback registration, which must happen before start.
- Live or replay is one input value given at construction. It replaces the replay flag and most constructor arguments.
- The camera pipeline is not a documented Protocol; its interface is documented in the architecture overview.
- The session writer Protocol is extended to state what the pipeline uses (directory, run directory, status, done). This is a Protocol change with a decision entry; the writer's start methods stay separate.
- Rule 6 holds: dropped, failed reads, unprocessed and recording-dropped counts stay in both the run's counts and the stats snapshot.

### Run metadata
- A small immutable settings value carries what the run metadata needs from the command line: requested capture size, and calibration refusal. It is built once per entry point.
- Run metadata takes the model-loaded time directly.
- Power and version reads stay inside the module. No environment port is added, because no test varies them.

### Run module
- Interface:
  - Plan from parsed arguments. This fails with exit 2 before the model loads.
  - Execute a plan with a stop request, a perception loader, a reporter and a waiter. It returns the outcome: exit code and each camera's status.
- Each camera in the plan is live, a replay into an existing session, or a replay of a file into a new session.
- Invariants:
  - Every opened session gets a final status on every path.
  - One table maps a stop at any phase to its status, event and exit code (Studio stop: ended, stopped event, exit 0; any other stop: interrupted, exit 130).
  - The group block is null exactly for one camera that is not a group replay.
  - A single camera's lines are untagged.
- Adapters:
  - Reporter: plain or tagged.
  - Waiter: plain, benchmark deadline, or the preview window on the main thread.
  - Perception loader: real or fake.
- A group of one bypasses the matcher and per-track appearance description, so single-camera track IDs and links are unchanged.
- Built in steps, each its own ticket:
  1. A characterisation test.
  2. Device and model load extracted.
  3. Stop policy extracted.
  4. Ctrl+C held during group setup.
  5. Group-of-one mode and the adapters.
  6. Replay and group routed through execute.
  7. The single camera routed through execute; the old single-camera run deleted.
- ADR 0007 holds: one process, one shared detector, per-camera capture threads, and stream loss handled per camera.

## Testing Decisions

- **What a good test is here.** It drives a module through its interface and checks external behaviour:
  - the files in the session folder (session.json, run.json, events, the track rows),
  - the status lines and exit codes,
  - Studio's HTTP responses,
  - or the return value of a new module.

  It does not reach into private attributes or monkeypatch internals. A test that needs a module's
  internals means the interface is the wrong shape.
- **Default tests need no camera, model weights or network.** They use synthetic fixture clips through
  the file source, the fake detector and tracker, temporary directories, and the fake camera child.
  Anything needing real weights is marked slow.
- **Seams tested, highest first:**
  - **Edge run entry point.** Run in-process with a fixture clip and a fake detector, then read the session folder back. Today this is the single-camera and group entry points; after the run module lands it is `execute`.
    - A table covers one or two cameras; live, session replay, file replay or group replay; no stop, a Studio stop or a plain stop at each phase; and each fault (model, source open, OpenCV error, calibration, shared detector).
    - Each row asserts the exit code, statuses, event kinds, required status lines, untagged lines for one camera, the group block, and links.
  - **Studio HTTP API**, through the test client with the fake camera child behind the launcher.
  - **Contract module:** validate and schema.
  - **New module interfaces**, each with its own table:
    - calibration intake: one row per refusal reason and offer kind;
    - session-folder reader: damaged fixtures, i.e. missing, empty, truncated, JSON list, null status, events not a list, an event not an object, runs not a list, a run with no folder, missing run.json, missing or null ready, null counts, byte-order mark;
    - protocol: emit-then-parse round trip for every message, with and without a camera, and with details containing separators, brackets, newlines or credentials.
- **Bug tickets.** Each bug gets a failing test first, at the highest seam that shows it:
  - Studio API for damaged sessions and the mid-run error;
  - edge run entry point for model load, setup stop and replay calibration;
  - contract module for 0.14–0.18.

  These tests must stay green through every refactor.
- **Characterisation.** Before the run module is built, one test pins today's behaviour on every path, with the known drift marked as expected failures. Each later step flips the expectations it fixes.
- **Measurement.** The benchmark option is recorded on the same fixture clip before and after the group-of-one step (rule 5). The figures go in the PR and the decision entry, never as unmeasured claims.
- **Targeted runs (D-062).** Each PR runs the test files for what changed and for their importers, and names them. The full suite runs only when the owner asks.
- **Prior art:**
  - group runner, group failures and group replay tests (in-process runs read back from disk);
  - the sessions page tests (the tolerance spec for damaged sessions);
  - the launcher tests with the fake camera child;
  - the contract tests;
  - the calibration refusal API tests;
  - the shared fakes module.

## Out of Scope

- Separate processes per camera, or crash isolation between cameras (ADR 0007).
- A learned re-identification model, and any new dependency.
- Changing the session writer's two start methods into one.
- An environment-probe port for run metadata.
- Turning the edge–Studio protocol into JSON lines.
- Studio UI changes beyond showing the typed failure kind.
- Publishing versioned schemas for an outside reader (there is none yet).
- A per-file calibration format field (only when the calibration format next changes).
- Running real model weights or real footage in the default tests. A real-clip before/after comparison was considered, then dropped for now because no suitable clip is available.
- Sync, the server and later phases.

## Further Notes

- **Ticket breakdown.**
  - T0 normalises line endings and records the scope.
  - BK, BS and BE are the Phase 03 bug tickets, one per lane.
  - T1–T12 are the refactors.
  - Blockers, lanes, owned files and reserved decision numbers (D-063 to D-070, contract 0.22.0 for T1) are in `coordination.md`.
- **Models per provider (owner).**
  - Claude Code runs an Opus overseer that delegates implementation to Sonnet subagents.
  - Codex runs only on "6.1 sol".
  - Antigravity runs only on "3.8 flash".
- **The bugs B1–B10 were reported by read-only exploration agents.** Each one is confirmed only when its failing test reproduces it. A bug that does not reproduce is closed with that test as evidence.
- **Contract bumps in this work:**
  - 0.22.0 (T1)
  - one for the protocol section (T6)
  - one for recording edge refusals as failed checks (T8)

  The last two take the next free version at merge time.
