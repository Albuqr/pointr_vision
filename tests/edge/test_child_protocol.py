"""T6: the versioned text protocol at its public emit/parse seam."""

from io import StringIO

import pytest

from services.edge.child_protocol import (
    DeviceChosen,
    PreviewListening,
    SessionOpened,
    StartFailed,
    Stop,
    Summary,
    emit,
    parse,
)


def test_t6_golden_wire_strings():
    stream = StringIO()
    for message in (
        SessionOpened("C:/out/cam_1"),
        DeviceChosen("cpu"),
        PreviewListening(51234),
        StartFailed("source_open_failed", "cannot open source: [fake]"),
        Summary("t0_wall=x captured=11 dropped=0 failed_reads=2 processed=9"),
        Stop(),
        Stop("ui"),
    ):
        emit(message, stream=stream)
    assert stream.getvalue() == (
        "session: C:/out/cam_1\ndevice: cpu\npreview_port: 51234\n"
        "error: source_open_failed: cannot open source: [fake]\n"
        "t0_wall=x captured=11 dropped=0 failed_reads=2 processed=9\nstop\nstop ui\n"
    )


@pytest.mark.parametrize("camera", [None, "cam_1"])
@pytest.mark.parametrize(
    "message",
    [
        SessionOpened("C:/out/a: [session]"),
        DeviceChosen("cuda: [0]"),
        PreviewListening(12345),
        StartFailed("model_load_failed", "cannot open: [weights]: detail"),
        Summary("t0_wall=x captured=2 dropped=0 failed_reads=3 processed=2"),
    ],
)
def test_t6_round_trip_every_output_message(camera, message):
    stream = StringIO()
    emit(message, camera, stream=stream)
    assert parse(stream.getvalue()) == (camera, message)


@pytest.mark.parametrize("source", [None, "ui"])
def test_t6_round_trip_stop(source):
    stream = StringIO()
    emit(Stop(source), stream=stream)
    assert parse(stream.getvalue()) == (None, Stop(source))


@pytest.mark.parametrize("camera", [None, "cam_1"])
@pytest.mark.parametrize(
    "kind",
    [
        "source_open_failed",
        "model_load_failed",
        "calibration_refused",
        "config_conflict",
        "start_timeout",
        "spawn_failed",
        "exited",
    ],
)
def test_t6_failure_round_trip_all_kinds_with_multiline_masked_detail(camera, kind):
    stream = StringIO()
    emit(
        StartFailed(
            kind,
            "first: [x] rtsp://user:password@host/x?token=secret\r\n"
            "session: injected\n\nlast: [bracket]",
        ),
        camera,
        stream=stream,
    )
    assert "password" not in stream.getvalue() and "secret" not in stream.getvalue()
    assert [parse(line) for line in stream.getvalue().splitlines()] == [
        (camera, StartFailed(kind, "first: [x] rtsp://***@host/x?token=***")),
        (camera, StartFailed(kind, "session: injected")),
        (camera, StartFailed(kind, "")),
        (camera, StartFailed(kind, "last: [bracket]")),
    ]


@pytest.mark.parametrize(
    "message, expected",
    [
        (SessionOpened("first\nsecond"), [SessionOpened("first"), SessionOpened("second")]),
        (DeviceChosen("cpu\rcuda"), [DeviceChosen("cpu"), DeviceChosen("cuda")]),
    ],
)
def test_t6_multiline_status_payloads_repeat_their_own_header(message, expected):
    stream = StringIO()
    emit(message, "cam1", stream=stream)
    assert [parse(line) for line in stream.getvalue().splitlines()] == [
        ("cam1", part) for part in expected
    ]


@pytest.mark.parametrize(
    "line, camera, message",
    [
        (
            "error: could not open weights: [x]",
            None,
            StartFailed("exited", "could not open weights: [x]"),
        ),
        ("[cam1] error: future_kind: detail", "cam1", StartFailed("exited", "future_kind: detail")),
        ("[cam1] log: rtsp://u:p@h/x", "cam1", None),
        ("session interrupted: x", None, None),
        ("preview_port: invalid", None, None),
        ("preview_port: 0", None, None),
        ("preview_port: 65536", None, None),
        ("stop app", None, None),
        ("[cam1] stop ui", "cam1", None),
    ],
)
def test_t6_parser_legacy_and_free_text(line, camera, message):
    assert parse(line) == (camera, message)


def test_t6_parse_also_masks_legacy_emitters_and_summary_exposes_failed_reads():
    assert parse("error: cannot open rtsp://u:p@h/x?token=secret") == (
        None,
        StartFailed("exited", "cannot open rtsp://***@h/x?token=***"),
    )
    _, message = parse("t0_wall=x captured=1 failed_reads=14 processed=1")
    assert message.failed_reads == "14"


def test_t6_default_stream_selection_and_flush(capsys):
    emit(SessionOpened("x"))
    emit(StartFailed("exited", "failed"))
    out = capsys.readouterr()
    assert out.out == "session: x\n"
    assert out.err == "error: exited: failed\n"

    class Stream(StringIO):
        flushed = False

        def flush(self):
            self.flushed = True

    stream = Stream()
    emit(DeviceChosen("cpu"), stream=stream)
    assert stream.flushed


@pytest.mark.parametrize(
    "action",
    [
        lambda: Stop("app"),
        lambda: StartFailed("unknown", "x"),
        lambda: PreviewListening(True),
        lambda: PreviewListening(-1),
        lambda: emit(Stop()),
        lambda: emit(Stop(), "cam1", stream=StringIO()),
        lambda: emit(DeviceChosen("cpu"), "bad] tag", stream=StringIO()),
    ],
)
def test_t6_invalid_values_cannot_emit_ambiguous_wire_lines(action):
    with pytest.raises(ValueError):
        action()


def test_t6_camera_tag_cannot_leak_credentials():
    stream = StringIO()
    with pytest.raises(ValueError):
        emit(DeviceChosen("cpu"), "http://user:pass@host", stream=stream)
    assert stream.getvalue() == ""
