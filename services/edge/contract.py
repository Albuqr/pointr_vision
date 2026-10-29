"""The contract version of the files this code writes and the Studio saves.

docs/DATA_CONTRACTS.md, the schemas in contracts/ and the fixtures carry the same number;
tests/test_contracts.py compares them. Change it here and nowhere else."""

CONTRACT_VERSION = "0.18.0"

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
# Names in run.json group.params when the court-position matcher ran (0.18.0, D-057); the matcher's
# MatcherParams fields plus the per-camera latency it used. A test compares them with the doc.
MATCHER_PARAMS = ("match_distance_m", "max_offset_s", "lost_s", "max_speed_mps", "latency_s")
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
