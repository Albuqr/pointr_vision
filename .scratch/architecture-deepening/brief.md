# Architecture deepening: brief

Source: `/improve-codebase-architecture` run on 2026-10-30 against `main` @ f0473bc, plus one read-only
exploration agent per candidate. Line numbers are as of f0473bc. Vocabulary: module, interface,
implementation, depth, seam, adapter, leverage, locality (see `.claude/skills/codebase-design`).

Nothing here is decided. Owner decisions are collected in section 3; the multi-agent plan is in
`coordination.md`. Phase scope (CLAUDE.md rule 1) is decision 0: until it is answered, this work is backlog.

---

## 1. Candidates

### C1. Calibration intake module (Strong)

**Problem.** The same refusal ends differently depending on the entry point, and the code that builds
calibration blocks is copied in several places.

| Entry point | Refusal | Outcome today |
|---|---|---|
| CLI `main`, live or single replay, `--calibration` | unreadable, wrong `camera_id`, size wrong at open | stops before any session, stderr only, `EXIT_CAPTURE_ERROR` (`main.py:598-604`) |
| Studio → `main` (1 camera) | saved document invalid | uncalibrated, `error` event "calibration not used" (`main.py:664-666`), exit 0 |
| Studio → `main` | size wrong at open | fatal, as in the CLI row |
| Studio → `main` / `group_main` | operator refused (D-057) | uncalibrated; run.json `checks` plus `startup_check_failed` |
| `group_main` | size, camera_id or file wrong at open | uncalibrated, `error` event plus `appearance_only` (`group_runner.py:207, 276-279`) |
| any live run | size wrong at first frame | that camera ends with status `error` (`camera_pipeline.py:164-188`) |
| group replay | malformed run.json block | whole replay refused |
| group replay | singular homography in run.json | **runs "calibrated" with every position empty and no event** (`homography.py:314-318`; `as_document` at `replay/group.py:81-87` skips validation) |

- **Converters.** There are three of them (`session_calibration` `camera_pipeline.py:51`, `run_calibration` `document.py:106`, `as_document` `replay/group.py:81`).
- **The `kind`/`type` alias** is patched in 6 places: `document.py:47-54, 115`, `camera_pipeline.py:60`, `replay/group.py:86`, `server.py:615-621`, `reports/build.py:276`.
- **Studio's `calibration_fit`** (`server.py:576-673`) builds the whole document by hand.
- **Replay inconsistency.** Single replay reads `--calibration`; group replay uses the live run's block.
- **Fix commits in this area:** 417ff17, 6b0b0d4, c54186b.

**Recommended shape (A, "intake verdict"):** `take_calibration(offer, camera_id, size) -> Intake`, which never raises.

- **`offer`** is one of: `FromFile(path)`, `FromRun(block)`, `Refused(reason)`, `NotUsed(problem)`, or `None`.
- **`Intake`** carries the `Calibration` (or None), the events to write, the run.json `checks`, and `refused_at_edge`.
- **`Calibration`** is one frozen runtime type that resolves `kind`/`type` once. It provides `session_block()`, `run_block()` and `preview_court()`.
- **`build_document(...)`** sits in the same module, for Studio's fit.
- **Invariants:**
  - A non-None calibration has been validated and its `image_size` equals `size`.
  - `run_block(from_run(b)) == b`.
  - `FromRun` runs `check_homography`, which closes the silent replay gap.
- **Callers:** `main.py` keeps one line of fatal/non-fatal policy. `CameraPipeline` writes the Intake's events and checks in `open_session`. Studio calls the same function in-process for its warning before start.
- **What goes away:** `as_document`, `session_calibration`, `run_calibration`, `failed_calibration_checks`, `calibration_failed_event`, and the alias patches.
- **Rejected alternatives:**
  - B, a value type that raises: shallow, and the policy stays in 4 callers.
  - C, intake owned by the pipeline: the deepest option, but `CameraTracker` is built before the pipeline (`group_runner.py:222-233`).
- **Tests.** Add a new `tests/edge/test_calibration_intake.py` with one row per refusal reason and entry point. The existing calibration tests stay, and nothing has a direct test that would be deleted.
- **Contract.** As a pure refactor, no bump, but a DECISIONS entry (it moves the refusal policy). Recording edge refusals as a failed `calibration` check is a semantic change (§3:212), so it needs a minor bump.

### C2. One run module: a single camera is a group of one (Strong)

**Problem.**
- Run start and end is written 3 times: `main.py:532-747`, `group_main.py:80-186` (which imports 15 names from main.py), and `replay/group.py:140-204` over `group_runner.run_group` (`:150-327`).
- **Drift** (all verified by the agent):
  - Model-load failure: in main.py it is an event line on stdout that the launcher's `error:` parser misses (`launcher_impl.py:440`). In the group code it goes to stderr as `error:`, which Studio does see.
  - The early-stop hold (`main.py:613-679`) is missing from groups. A Studio stop during group setup ends with `error` and exit 130, contrary to D-049 (BACKLOG line 79).
  - A replay never passes `ui_stop` (`replay/group.py:179`).
  - Groups lose the `source:`/`health:`/`versions:` lines, the `events={}` count, and `--benchmark` (silently ignored).
  - `cv2.error` handling differs between paths.
- **Why a single camera cannot simply call `run_group` today:**
  - It would write a non-null `group` block (§3 says null without a group).
  - The matcher would renumber its tracks (`matcher.py:150,166`).
  - Its tagged `[cam]` lines would never reach Studio as `session:`, because the launcher strips tags only when there are 2 or more children (`launcher_impl.py:412`). Studio would time out after 180 s.

**Recommended shape (A, "plan then execute"):**

- **Entry point.** `plan_from_args(list[Namespace]) -> RunPlan` raises `PlanError` (exit 2) before the model loads. Then `execute(plan, stop, *, load_perception, say: Reporter, wait: Waiter) -> RunOutcome(exit_code, statuses)`.
- **Camera kinds.** `CameraSpec` is `Live(ref)`, `ReplayIntoSession(RecordedCamera)` or `ReplayNewSession(file)`.
- **Invariants:**
  - Every opened session gets a final status on every path.
  - One table maps a stop at any phase to its outcome (`ui` → `ended`, `stopped` event, exit 0; any other stop → `interrupted`, exit 130).
  - `group` is null exactly when there is one camera and it is not a group replay.
  - With one camera, its `session:` line is untagged.
- **Adapters:**
  - `Reporter`: plain or tagged.
  - `Waiter`: plain, benchmark deadline, or the cv2 window on the main thread.
  - `load_perception`: a fake detector in tests.
- **What the entry points shrink to:** about 15 lines in main and about 20 in group_main. `services/edge/replay/group.py` keeps only `resolve_group`.
- **ADR 0007** is strengthened by this. Keep the per-camera capture threads (FR-014). There is no contract bump if a group of one writes `group: null`.
- **Risks:**
  - The cost of an uncontended `SharedDetector` lock with one camera is unmeasured, so record `--benchmark` before and after (rule 5).
  - Skip `describe()` per track for one camera.
  - Starting the HTTP preview in `on_session` turns a bind failure into a setup failure, so it needs a test.

**Migration, one PR per step:**
1. A characterisation table test that pins today's lines, exit codes and files, with the known drift marked expected-fail.
2. Extract `services/edge/run/perception.py` (device and model load). It emits both the event line and an `error:` line, and keeps a re-export so the `cli.load_perception` monkeypatches still work.
3. Extract `services/edge/run/stop.py` (`StopRequest`, the hold/ignore helpers, `end_of(exc, stop)`) and use it at all 4 sites.
4. Hold Ctrl+C during `run_group` setup (closes BACKLOG line 79).
5. Add the group-of-one mode to `run_group` (no matcher, `group` null), the `ReplayNewSession` kind, and the `Waiter`/`Reporter` adapters.
6. `execute(plan)`, with `run_replay` and then `group_main` routed through it.
7. Route `main` through it, delete `main.run`, and drop the re-exports.

**Tests.**
- **Rewritten through `execute`:** `test_cli.py:145-260`, `test_session.py:80-460`, `test_group_main.py:18-56`, `test_preview_disconnect.py:52`, `test_calibration_size.py:56,128`, `test_replay.py:274,289`.
- **Unchanged:** the group, matcher, pipeline, launcher, subprocess and writer tests.

### C3. Contract version owned by `contract.py` (Strong)

**Problem.**
- **Bump fan-out.** A bump touches about 15 files: 5 `contracts/*.schema.json`, 5 fixtures, `contract.py`, `ACCEPTED_VERSIONS`, the byte-identical `services/edge/calibration/calibration.schema.json` (the only schema read at runtime, shipped through `pyproject.toml:35-36`), `DATA_CONTRACTS.md` and `DECISIONS.md`.
- **Accepted versions are kept by hand.** The calibration schema body has not changed since 0.13.0, yet `ACCEPTED_VERSIONS` is maintained by hand and is missing 0.14 to 0.18 (BACKLOG:85), so those files are refused.
- **Doc examples can drift unnoticed.** `DATA_CONTRACTS.md` example blocks (lines 66, 140, 413, 756) are compared on keys only (`test_contracts.py:276`).
- **No outside readers.** `services/api`, `sync_agent` and `data` are empty.

**Recommended (design c plus a calibration format table):**
- **Schemas drop the version.** `contract_version` becomes a semver `pattern`, and `$id` drops the version (`urn:pointr:contracts:calibration`).
- **`contract.py` becomes the deep module:** `CONTRACT_VERSION`, `CALIBRATION_FORMAT`, `schema(name)` (via `importlib.resources`, cached), `validate(name, doc)` (jsonschema plus a version-equality check), and `accepts_calibration(version)`. The last uses a range table (`CALIBRATION_FORMATS = {"1": ("0.8.0", None)}`) and compares tuples, not strings.
- **Schemas move** into `services/edge/contracts/*.schema.json` as package data, and the top-level `contracts/` is deleted. Update `ARCHITECTURE.md:51`, `.claude/agents/contract-guardian.md:11,18` and `DATA_CONTRACTS.md:5`.
- **After this, a bump is 3 files:** `contract.py`, the `DATA_CONTRACTS.md` header and `DECISIONS.md`. Fixtures are stamped at test load.
- **The refactor itself is a contract change:** 0.22.0 and a DECISIONS entry amending D-009 and D-027 and closing BACKLOG:85.
- **Rejected alternatives:**
  - (a) A placeholder token replaced at load: the schemas stop being valid JSON Schema on their own.
  - (b) A generator script: shallow, and it keeps the CRLF hazard.

**Line endings (do this first, as its own commit).**
- **Current state:** `core.autocrlf=true`, `.gitattributes` covers only `.githooks/*` and `*.sh`, and the index is mixed (25 files CRLF, 374 LF), including every contract file. Any tool that writes LF to one of those files produces a full-file diff (36217e3, then b471907).
- **Fix:** add `* text=auto eol=lf` plus `binary` rules, run `git add --renormalize .` as one whitespace-only commit, and add that commit to `.git-blame-ignore-revs`.
- **Why this matters for multi-provider work:** Claude, Codex and Antigravity write line endings differently.

**Tests.**
- **`test_contracts.py:65-69` assertions:**
  - The doc header equals `CONTRACT_VERSION`.
  - The fixtures equal `CONTRACT_VERSION`.
  - No schema holds a semver literal.
- **Read schemas through `contract.schema(name)`.** About 12 direct reads of `contracts/…` go through it instead.
- **Drop `test_calibration_schema.py:28-29`.**
- **New tests:**
  - `validate` rejects a wrong version.
  - `accepts_calibration` accepts 0.8.0 to current, including 0.14–0.18 as a regression test.
  - Every doc example block equals `CONTRACT_VERSION`.
  - An installed-wheel `schema()` check.

### C4. Session-folder reader, and one protocol module for the lines the edge prints to Studio (Worth exploring, two PRs)

**C4a, the reader.**

About 11 sites parse `session.json`/`run.json` by hand, each handling damage its own way:
- `server.py:80` (recover, which also *writes* session.json, a second writer), `:330` status, `:1003` camera_state, `:1078` session_row (the most tolerant, and the de facto spec)
- `launcher_impl.py:630-660`
- `replay/resolve.py:36,57`
- `replay/group.py:104,117`
- `reports/build.py:180-207`
- `reports/cli.py:104`
- `score.py:147`
- `writer.py:231`
- `camera_log.py:56`

They also disagree on which run is the latest: `next(iterdir())`, the only one in `iterdir()`, or `runs[-1]`. Encoding is `utf-8` in some readers and `utf-8-sig` in others.

**Recommended (A1):** `services/edge/session/folder.py`.
- **Reads:** `read_session(dir) -> SessionSnapshot` and `read_run(run_dir) -> RunSnapshot`. Both are frozen, with optional fields plus `problems: tuple[str, ...]`, and never raise on content.
- **Strict callers** use `snap.require(...)`, which raises `SessionDamaged(ValueError)`.
- **Lookup and runs:** `find_sessions(out, *, group_id=None, session_id=None)`, plus `live_run` and the run directories.
- **Recovery:** `mark_interrupted` moves here from `server.py:80-97`, which duplicates `writer.py:117-139`.
- **Dependencies:** local-substitutable (`tmp_path`). Studio already imports from edge, so no new dependency direction.
- **Tests:** a new `tests/edge/test_session_folder.py` damaged-fixture table: missing, empty, truncated, JSON list, `status: null`, events not a list or an event not a dict, runs not a list, a run id with no folder, missing run.json, `ready` missing or null, `counts: null`, BOM. Plus one test per caller: a JSON-list session.json in a sibling folder must not break `resolve_group`, `_find_session`, `group_sessions`, `/api/recording` or Studio start.

**C4b, the protocol.**

- **What crosses today:**
  - stdout: `session: `, `device: `, `preview_port: `, `error: ` (stderr merged in), the `[cam] ` prefix, `failed_reads=N`, and `session <status>: `.
  - stdin: `stop` and `stop ui`.
- **Where it's written down:** only in prose (D-056, ARCHITECTURE §5), not in DATA_CONTRACTS.
- **Emitters** are spread over `main.py`, `group_main.py`, `services/edge/replay/group.py`, `camera_pipeline.py:182,311` and `group_runner.py:326`.
- **Parsing** is at `launcher_impl.py:67-69, 424-441`.
- **Studio** guesses the failure kind from substrings (`server.py:176-196`: `"open" in failure.lower()` also matches "opencv").

**Recommended (B2):** `services/edge/child_protocol.py`, with typed messages over the same text wire.
- **Messages:** `SessionOpened`, `DeviceChosen`, `PreviewListening`, `StartFailed(kind, detail)`, `Summary`, `Stop(source)`.
- **`emit(msg, camera_id=None)`** owns the prefix, line splitting, masking and stderr.
- **`parse(line) -> (camera_id | None, Message | None)`.**
- **`StartFailed.kind`** is one of `source_open_failed`, `model_load_failed`, `calibration_refused`, `config_conflict`, `start_timeout`, `spawn_failed`, `exited`.
- **Wire format:** `error: <kind>: <detail>`. An old-format line parses as `exited`.
- **Invariant:** a failure after `SessionOpened` is not a start failure.
- **Contract:** DATA_CONTRACTS gets a new §16, a minor bump and a DECISIONS entry.
- **Rejected:**
  - B1, a module of constants: shallow.
  - B3, JSON lines: harder to read in the console, and it churns every fixture.
- **Tests:**
  - A round trip of emit → parse for every message, with and without a camera, covering details that contain `": "`, `[x]`, newlines or credentials.
  - One golden test that keeps the literal wire strings, replacing the scattered literals at `test_preview_timing.py:97` and `test_session.py:103`.
  - `fake_camera.py:68` calls `emit()`.

### C5. The camera pipeline stops exposing its parts (Worth exploring)

**Corrections to the original finding.**
- `open_session` is really a two-way branch, `start` vs `start_run` (`camera_pipeline.py:139-144`).
- The replay flag changes only `lossless=` (:106) and the `t_video` fallback (:205).

**Leaks.**
- **From the pipeline into the writer:** the pipeline uses `writer.dir` (:146) and `writer.done` (:192), which are not in the `SessionWriter` Protocol (`session/types.py:105-139`). So it is coupled to `FileSessionWriter`.
- **From callers into the pipeline** (each reads a part directly):
  - `main.py:510-529, 524, 632, 687-745, 761-796`; `print_benchmark` takes the whole Capture and Processor.
  - `group_main.py:170-177`
  - `group_runner.py:146-147, 272`
  - `replay/group.py:175, 201`

**Recommended (A, narrow interface with value snapshots, with C's input modes folded in).**
- **Lifecycle:** `open_session(run)`, `start()`, `done`, `stop(status) -> str`, `error`.
- **Events:** `log_event(ev)`.
- **Session paths and status:** `session_dir`, `run_dir`, `status`.
- **Counters:** `stats() -> CameraStats`, a frozen record of every counter, exact after `stop()`.
- **Live views:** `health_state()`, `hud()`, `latest()`, `raw_snapshot()`, `calibration`.
- **Preview:** `on_preview(cb)` (registering after `start()` raises) and `mark_preview_ready()`.
- **Construction:** the constructor takes `LiveInput(source, info, meta, recorder)` or `ReplayInput(source, info, session_dir)` in place of the replay flag and the 11 parameters.
- **What it does not touch:** `CameraPipeline` is not a documented Protocol (ARCHITECTURE:67-69), so no Protocol changes.
- **Optional writer change:** making the writer's real contract explicit (adding `dir`, `run_dir`, `status`, `done` to `SessionWriter`) *is* a Protocol change. It needs a DECISIONS entry, ARCHITECTURE §4 and `test_interfaces.py:35-70`. Merging `start`/`start_run` is not worth it.
- **Rule 6:** dropped, failed_reads, unprocessed and rec_dropped stay visible in both `RunCounts` and `stats()`.
- **Order:** do this **before C2**, otherwise C2 copies the summary leaks into the new module.
- **Tests:**
  - Edit `test_camera_pipeline.py:70` and `test_group_runner.py:267`.
  - New tests: `stats()` equals the run.json counts; `on_preview` gets every frame; `ReplayInput` adds a run and writes no `video.mkv`; `error` exposes a `SharedCodeError`; `print_benchmark` takes a `CameraStats` built by hand.

### C6. Run metadata without argparse (downgraded: small, do first)

**Corrections to the original finding.**
- `test_power.py` has 2 monkeypatches, not 14, and both patch the existing internal seam `power.system_power_status`.
- The Namespace rebuild at `group_main.py:91` feeds `load_perception`, not `run_meta`.
- The GPU value is passed in.
- `power.end` comes from `camera_pipeline.py:301`.
- **An `EnvironmentProbe` port would be a hypothetical seam**, because no test varies platform or versions. Rejected.

**Recommended (B).**
- **`RunSettings`:** a frozen value `RunSettings(requested_size, calibration_refusal)` with `from_args(args)`, living in main.py for now.
- **New signature:** `run_meta(settings, info, config, detector, tracker, gpu, replay=None, model_loaded=None)`. Taking `model_loaded` removes 3 `replace(ready=...)` calls.
- **Calibration helpers:** `failed_calibration_checks` and `calibration_failed_event` take the refusal string.
- **Test fakes (separate commit):** move them into the existing `tests/edge/fakes.py`. That covers `EvenFrameDetector` and `OneTrackPerDetection` from `test_session.py`, the `meta()` helper, the test helper `run_meta` (renamed `sample_run_meta` so it stops shadowing the production name), and `_run` merged with `test_replay.py:176`. This removes about 20 imports from one test module into another. `testkit/` is the wrong place for them (it is a vendored CI/QA kit).
- **What it leaves alone:** no contract change. The `load_perception(args)` coupling stays for C2.

---

## 2. Bugs found along the way (exploration agents reported these; reproduce each with a failing test first)

| # | Bug | Where | Candidate that fixes it |
|---|---|---|---|
| B1 | A non-dict session.json (a JSON list or string) in any folder raises `AttributeError`, which is uncaught. It aborts every group replay. Studio status returns 500. **Studio fails to construct when `active_group.json` exists.** | `replay/group.py:104-107`, `replay/resolve.py:36-40`, `reports/cli.py:107`, `server.py:330`, `server.py:82` | C4a |
| B2 | Mid-run `error:` lines (`camera_pipeline.py:182,311`, `group_runner.py:326`) carry no camera prefix, so in a group every camera receives them. `camera_state` then shows `error` for a camera that is recording, and `note_child` logs "could not start recording". | `server.py:178, 992` | C4b |
| B3 | A single-camera model-load failure is printed as an event line, not `error:`, so Studio shows the generic "failed to start (exit N)". | `main.py:589, 597` | C2 step 2 |
| B4 | A Studio stop during group setup ends the session with `error` and exit 130 (contrary to D-049). | `group_runner.py:282-290`, `group_main.py:161` (BACKLOG:79) | C2 step 4 |
| B5 | Group replay with a singular homography runs "calibrated" with every position empty and no event. | `homography.py:314-318`, `replay/group.py:81-87` | C1 |
| B6 | Calibrations saved at 0.14 to 0.18 are refused on load. | `document.py:20-22` (BACKLOG:85) | C3 |
| B7 | In the launcher, `status: null` raises `TypeError` (`+= " (killed)"`) and so does a non-dict event. | `launcher_impl.py:600, 635` | C4a |
| B8 | `camera_state` crashes on `ready: null`. | `server.py:1003` | C4a |
| B9 | Studio status picks a run with `next(iterdir())`, so the order is arbitrary. | `server.py:337` | C4a |
| B10 | A failure is classified by substring: `"open"` also matches "opencv" and "could not open weights". | `server.py:176-196` | C4b |

---

## 3. Owner decisions

**Decided by the owner on 2026-10-30:**

| # | Decision |
|---|---|
| 0 | **Scope.** Fix bugs B1–B10 now under Phase 03. The refactors (T1–T12) become an **R2a follow-up**, with their own PHASES.md entry and DECISIONS entry (D-063 records the scope). |
| 2 | **Schemas drop the version** (`const` and the version in `$id`). `contract.py` checks it through `validate()`. |
| 6 | **A single camera whose calibration is refused at open records uncalibrated, with an event**, the same as a group. It is no longer fatal. |
| 8 | **Edge refusals are recorded as a failed `calibration` check** (run.json `checks` plus `startup_check_failed`). This is a minor bump. |
| 9 | **A single-session replay uses the live run's calibration**; `--calibration` overrides it. |
| 14 + 15 | **The protocol on the edge's printed lines becomes DATA_CONTRACTS §16** (minor bump), with typed `error: <kind>: <detail>`. The parser still accepts old lines, reading them as kind `exited`. |

**All other rows below:** the recommended answer applies unless the owner says otherwise.

**Owner decisions (recommended answer first)**

**0. Scope.** Is this in Phase 03 scope (CLAUDE.md rule 1), or backlog? Recommended: fix the bugs B1–B10 now under Phase 03; open the refactors as an R2a follow-up with its own scope entry in PHASES.md and DECISIONS.

| # | Decision | Recommended |
|---|---|---|
| 1 | Normalise all line endings to LF in a separate commit before anything else | Yes |
| 2 | Schemas drop the version (`const` and `$id`); `contract.py` checks it instead | Yes (no outside readers yet) |
| 3 | Calibration compatibility: a table in code, or a new `calibration_format` field in files | A table in code now; add a field only when the format next changes |
| 4 | Schemas live in `services/edge/contracts/` as package data, as the only copy | Yes |
| 5 | Is the C3 refactor itself a contract bump? | Yes, 0.22.0 |
| 6 | A single camera whose calibration is refused when the source opens: record uncalibrated with an event (as groups do), not fatal | Yes (ADR 0007, "a failed check never blocks the start") |
| 7 | A first-frame size mismatch still ends that camera | Yes (D-059); write down why it differs from 6 |
| 8 | An edge-detected refusal is written as a failed `calibration` check (run.json `checks` plus `startup_check_failed`) | Yes, with a minor bump |
| 9 | A single-session replay uses the live run's calibration (as D-060 does for groups), with `--calibration` as an override | Yes |
| 10 | A group of one writes `group: null` | Yes (no bump) |
| 11 | A model-load failure prints both the event line and an `error:` line | Yes |
| 12 | Groups accept `--benchmark` per camera; the preview window stays single-camera | Yes |
| 13 | A single replay's tracker keeps using its own receive times (not group time) | Yes |
| 14 | The protocol on the lines the edge prints becomes DATA_CONTRACTS §16, with a minor bump and a DECISIONS entry | Yes |
| 15 | Wire format `error: <kind>: <detail>`, and the parser still accepts old lines | Yes |
| 16 | An `error:` in the middle of a run does not mark the camera failed; errors during a run are session events or `warning:` | Yes |
| 17 | Make the writer's real contract explicit (`dir`, `run_dir`, `status`, `done` in `SessionWriter`) | Yes; do not merge `start`/`start_run` |
| 18 | Fold the input modes (`LiveInput`/`ReplayInput`) into C5 | Yes |
| 19 | `print_benchmark` takes a `CameraStats` | Yes |
| 20 | `run_meta` takes `model_loaded`; `RunSettings` lives in main.py for now | Yes |
| 21 | Move shared test fakes into `tests/edge/fakes.py` and rename the test `run_meta` | Yes, as a separate commit |
| 22 | GLOSSARY gains "launcher", "child" and "stop channel" | Yes |
| 23 | Record `--benchmark` on the fixture clip before and after C2 step 5 (rule 5) | Yes |
