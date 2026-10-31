"""The contract version of the files this code writes and the Studio saves, and the schemas.

The version lives here only. The JSON schemas in services/edge/contracts/ carry a semver
pattern, not a number; `validate` compares a document's version with CONTRACT_VERSION. A bump
touches this file, the header and example blocks of docs/DATA_CONTRACTS.md, and DECISIONS.md."""

import copy
import functools
import json
import re
from importlib.resources import files

from jsonschema import Draft202012Validator, ValidationError

CONTRACT_VERSION = "0.26.0"

# Calibration file format -> (lowest contract version that wrote it, inclusive; highest, inclusive,
# None = up to CONTRACT_VERSION). A bump that leaves the calibration format unchanged needs no
# edit here; a bump that changes it adds a format and closes the previous range (D-064).
CALIBRATION_FORMAT = "1"
CALIBRATION_FORMATS = {"1": ("0.8.0", None)}

_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def parse_version(version) -> tuple[int, int, int]:
    """Strict `X.Y.Z` to a tuple of ints, so 0.10.0 sorts after 0.9.0. ValueError otherwise."""
    match = _SEMVER.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        raise ValueError(f"not a version X.Y.Z: {version!r}")
    return tuple(int(part) for part in match.groups())


@functools.cache
def _load_schema(name):
    path = files("services.edge").joinpath("contracts", f"{name}.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def schema(name) -> dict:
    """The packaged JSON schema `name` (calibration, fusion, report, run, session); a copy."""
    return copy.deepcopy(_load_schema(name))


def validate(name, doc) -> None:
    """Raise jsonschema.ValidationError unless `doc` carries CONTRACT_VERSION and fits schema."""
    found = doc.get("contract_version") if isinstance(doc, dict) else None
    if found != CONTRACT_VERSION:
        raise ValidationError(
            f"contract_version {found!r} is not the current contract version {CONTRACT_VERSION!r}"
        )
    Draft202012Validator(schema(name)).validate(doc)


def accepts_calibration(version) -> bool:
    """True when a calibration saved under `version` is in the current format's range."""
    try:
        found = parse_version(version)
        low, high = CALIBRATION_FORMATS[CALIBRATION_FORMAT]
        return parse_version(low) <= found <= parse_version(high or CONTRACT_VERSION)
    except ValueError:
        return False


# The raw recording of a live session (D-042). MKV, not MP4: an MP4 written by
# OpenCV has no index until it is closed, so a killed session leaves an unreadable file (measured
# 2026-10-20); an MKV stays readable up to the last few seconds.
VIDEO_FILE = "video.mkv"

# The detail of the `stopped` event of Studio's stop (DATA_CONTRACTS section 2, D-049): source, then
# a sentence.
UI_STOP_DETAIL = "ui: stop requested in Studio"

# CSV column names of the Track R formats (DATA_CONTRACTS.md sections 11 to 15, D-034 to D-039).
# tests/test_contracts_track_r.py compares each tuple with its table in the doc. The code that
# writes these files arrives in the slice named next to each one (docs/phases/PHASE_R.md).
OBJECTS_COLUMNS = ("seq", "class", "x1", "y1", "x2", "y2", "confidence", "source")  # R2
EVENTS_COLUMNS = (  # R4
    "sensor_id", "sensor_seq", "kind", "t_sensor", "t_pc", "t_wall", "offset_s", "link",
)  # fmt: skip
SHOTS_COLUMNS = (  # R3
    "shot_id", "seq", "t_release", "track_id", "player_number", "call", "call_source",
    "sensor_id", "sensor_seq", "x_m", "y_m", "distance_m", "window_start", "window_end",
    "flags",
)  # fmt: skip
LABELS_COLUMNS = ("time_s", "event", "player_number", "note")  # R1: hand-made, read by the scorer
FUSED_TRACKS_COLUMNS = (  # R6
    "t", "fused_id", "player_number", "x_m", "y_m", "in_court", "cameras", "source_tracks",
)  # fmt: skip
FUSION_DIFF_COLUMNS = (  # R6
    "t", "fused_id", "field", "camera_a", "camera_b", "value_a", "value_b", "delta",
)  # fmt: skip

# Values of the Track R text columns and enums. tests/test_contracts_track_r.py checks that each
# appears in its section of the doc and, where there is one, that the schema enum is the same.
CHECK_NAMES = ("cameras", "calibration", "identity", "id_persistence", "sensor")
LINKS = ("espnow", "usb")
ID_SOURCES = ("jersey_vote", "jersey_gated", "operator")
UNSHARED = "unshared"  # the link of every track row of a run without a group run
TRACK_LINKS = ("position", "appearance", UNSHARED)  # tracks.csv link (0.14.0, D-051)
# Names in run.json group.params when the court-position matcher ran (0.19.0, D-058); the matcher's
# MatcherParams fields plus the per-camera latency it used; the appearance fallback's two (0.21.0,
# D-061). A test compares them with the doc.
MATCHER_PARAMS = (
    "match_distance_m", "max_offset_s", "lost_s", "max_speed_mps",
    "appearance_max_distance", "max_height_diff", "latency_s",
)  # fmt: skip
OBJECT_CLASSES = ("ball", "rim")
OBJECT_SOURCES = ("detector", "session_median")
SENSOR_EVENT_KINDS = ("make", "sync", "outage_start", "outage_end", "reset")
SHOT_CALLS = ("make", "miss", "uncertain")
CALL_SOURCES = ("video", "sensor", "video+sensor")
SHOT_FLAGS = ("no_sensor", "shooter_unknown", "ball_hidden", "gap")
LABEL_EVENTS = ("attempt", "make", "miss", "leave", "return")
FUSION_FIELDS = ("position", "player_number", "presence")
EXCLUDED_REASONS = ("calibration_failed", "operator")
TRACK_R_SESSION_EVENT_KINDS = ("camera_gap", "sensor_outage", "startup_check_failed", "rim_drift")
