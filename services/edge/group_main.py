"""The one process of a group (R2a 04, ADR 0007): what services.edge.main does for one camera,
for every camera of a group, through the group runner. The launcher starts it:

    python -m services.edge.group_main CAMERA_ARGS [CAMERA_ARGS ...]

Each CAMERA_ARGS is a JSON list: the arguments services.edge.main would get for that camera
(launcher.camera_args). The settings of the one detector (device, threshold, det-size) and the
stop channel come from the cameras' arguments. Every output line about one camera starts with
"[camera_id] ", so the launcher can tell the cameras apart; lines about the group (device, model
load, a failure to start) have no prefix.
"""

import argparse
import dataclasses
import json
import sys
import time

from services.edge.capture.sources import SourceOpenError, open_source
from services.edge.capture.types import HealthEvent, utc_now
from services.edge.contract import UI_STOP_DETAIL
from services.edge.group_runner import GroupCamera, run_group
from services.edge.main import (
    EXIT_CAPTURE_ERROR,
    EXIT_INTERRUPTED,
    EXIT_OPEN_FAILED,
    StopRequest,
    create_tracker,
    health_config,
    link_conflict,
    load_perception,
    parse_args,
    print_event,
    resolve_device,
    run_meta,
    start_http_preview,
    stop_on_stdin,
)
from services.edge.matcher import CourtMatcher, MatcherParams
from services.edge.reports.build import format_summary, write_report


def say(camera_id: str, text: str) -> None:
    try:
        for line in text.splitlines():
            print(f"[{camera_id}] {line}", flush=True)
    except OSError:  # the launcher that read this pipe is gone: the files still get everything
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cams = [parse_args(json.loads(text)) for text in argv]
    stop = StopRequest()
    try:
        if any(a.stop_on_stdin for a in cams):
            stop_on_stdin(stop)
        return run(cams, stop)
    except KeyboardInterrupt:  # a stop before the sessions (model load, slow stream open)
        if stop.ui:  # no session yet; Studio's stop is still a normal end
            print_event(HealthEvent("stopped", utc_now(), None, UI_STOP_DETAIL), None)
            return 0
        print_event(HealthEvent("interrupted", utc_now(), None, "Ctrl+C"), None)
        return EXIT_INTERRUPTED


def group_det_size(sizes: set[int | None]) -> int | None:
    """One detector, one size (D-056): the largest a camera asks for; None (the model's own) when
    none asks for one. A camera that asks for none gets the size another camera asked for."""
    return max((s for s in sizes if s), default=None)


def group_matcher(cams: list[argparse.Namespace]) -> CourtMatcher:
    """The cross-camera matcher (D-057): a group ID is kept as long as the longest lost-track time
    of the cameras' trackers, so a track the tracker takes back is not forgotten first."""
    return CourtMatcher(MatcherParams(lost_s=max(a.track_lost_secs for a in cams)))


def run(cams: list[argparse.Namespace], stop: StopRequest) -> int:
    """The group's settings (device, threshold, detection and recording on or off, out, group)
    come from the first camera: the launcher passes every camera the same ones. det-size is per
    camera in Studio, so a disagreement is a warning."""
    first = cams[0]
    by_id = {a.camera_id: a for a in cams}
    config = health_config(first)  # the launcher passes no health settings: the defaults
    if any(a.preview for a in cams):
        print("warning: no preview window in a group; Studio shows each camera's preview")
    sizes = {a.det_size for a in cams}
    if len(sizes) > 1:
        first = argparse.Namespace(**{**vars(first), "det_size": group_det_size(sizes)})
        asked = sorted(sizes, key=str)
        print(f"warning: cameras ask for det-size {asked}; the group uses {first.det_size}")
    detector = gpu = model_loaded = None
    if not first.no_detect:
        try:
            device, gpu = resolve_device(first.device)
        except Exception as e:  # forced cuda without a GPU, or a broken torch install
            print(f"error: {e}", file=sys.stderr)
            return EXIT_CAPTURE_ERROR
        print(f"device: {device}" + (f" ({gpu})" if gpu else " (no CUDA GPU in use)"))
        try:
            detector, _ = load_perception(first, device)
            model_loaded = {"t_wall": utc_now(), "t_pc": time.perf_counter()}
        except Exception as e:  # e.g. no network for the first weights download
            print(f"error: model load failed: {e!r}", file=sys.stderr)
            return EXIT_CAPTURE_ERROR

    cameras = []
    for a in cams:
        try:
            source = open_source(a.source, (a.width, a.height))
        except SourceOpenError as e:
            say(a.camera_id, f"error: cannot open source: {e}")  # Studio shows it on that camera
            return EXIT_OPEN_FAILED
        source.fps_cap = a.fps_cap
        if conflict := link_conflict(source.kind, a.link):
            say(a.camera_id, f"error: {conflict}")
            return EXIT_OPEN_FAILED
        cameras.append(GroupCamera(a.camera_id, source, a.link, a.calibration))

    def make_run(camera_id, info):
        a = by_id[camera_id]
        tracker = None if detector is None else create_tracker(a)
        meta = run_meta(a, info, config, detector, tracker, gpu)
        return dataclasses.replace(meta, ready={"model_loaded": model_loaded})

    pipelines, previews = {}, []

    def on_session(camera_id, pipeline):
        a = by_id[camera_id]
        pipelines[camera_id] = pipeline
        say(camera_id, f"session: {pipeline.writer.dir}")
        if a.calibration_problem:  # before any run, so no t0: t_mono is null
            detail = f"calibration not used: {a.calibration_problem}"
            pipeline.log_event(HealthEvent("error", utc_now(), None, detail))
        if a.http_preview is not None:
            previews.append(start_http_preview(a.http_preview, pipeline))
            say(camera_id, f"preview_port: {previews[-1].port}")

    code = 0
    try:
        statuses = run_group(
            first.group_id,
            cameras,
            detector,
            lambda camera_id: create_tracker(by_id[camera_id]),
            first.out,
            config,
            make_run,
            record=not first.no_record,
            matcher=group_matcher(cams),
            on_event=lambda camera_id, ev, t0: print_event(ev, t0, f"[{camera_id}] "),
            on_session=on_session,
            ui_stop=lambda: stop.ui,
        )
        if any(s != "ended" for s in statuses.values()):
            code = EXIT_CAPTURE_ERROR
    except KeyboardInterrupt:  # every session already ended `interrupted`
        code = EXIT_INTERRUPTED
    except Exception as e:  # every session already ended `error`, with the failure as an event
        print(f"error: the group did not run: {e}", file=sys.stderr)
        code = EXIT_OPEN_FAILED if isinstance(e, SourceOpenError) else EXIT_CAPTURE_ERROR
    finally:
        for preview in previews:
            preview.close()
    try:  # the sessions are saved: a stop now only cuts the summaries short
        for camera_id, p in pipelines.items():
            c, proc = p.capture, p.processor
            say(camera_id, f"session {p.writer.status}: {p.writer.dir}")
            say(
                camera_id,
                f"t0_wall={c.t0_wall} captured={c.captured} dropped={c.dropped} "
                f"failed_reads={c.failed_reads} processed={proc.processed} "
                f"unprocessed={proc.unprocessed}",
            )
            try:  # a failure is a warning: the session is saved (D-023)
                say(camera_id, format_summary(write_report(p.writer.run_dir)))
            except Exception as e:
                print(f"warning: {camera_id}: report not written: {e!r}", file=sys.stderr)
    except KeyboardInterrupt:
        print("warning: reports interrupted; run python -m services.edge.report", file=sys.stderr)
        code = code or EXIT_INTERRUPTED
    return code


if __name__ == "__main__":
    sys.exit(main())
