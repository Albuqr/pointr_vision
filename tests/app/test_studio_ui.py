"""The packaged Studio source must keep the controls and persistent error affordances exposed."""

from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "services/app/ui/src/studio.tsx"


def test_camera_form_exposes_validated_settings_and_field_errors():
    source = SOURCE.read_text(encoding="utf-8")
    for control in (
        "Camera ID",
        "Display name",
        "Detection size",
        "FPS cap (optional)",
        "Enabled for recording",
        'fieldError("name")',
        'fieldError("source")',
        'fieldError("det_size")',
        'fieldError("fps_cap")',
        "Camera configuration warning:",
    ):
        assert control in source


def test_camera_error_panel_never_uses_a_timer_to_dismiss():
    source = SOURCE.read_text(encoding="utf-8")
    panel = source.split("function ErrorPanel", 1)[1].split("function EventLog", 1)[0]
    assert 'role="alert"' in panel
    assert "Technical detail" in panel
    assert "Copy" in panel and "Dismiss" in panel
    assert "setTimeout" not in panel


def test_camera_test_result_and_event_log_are_visible_until_user_action():
    source = SOURCE.read_text(encoding="utf-8")
    assert "Event log ({events.length})" in source
    assert "Test passed" in source and "Test failed:" in source
    assert "setTested" in source and "Dismiss" in source


def test_half_court_controls_recommend_anchors_and_warn_below_area_coverage():
    source = SOURCE.read_text(encoding="utf-8")
    assert '<option value="fiba_half">Half court</option>' in source
    assert "midcourt_near_corner" in source and "midcourt_far_corner" in source
    assert "Best visible anchors: baseline corners and midcourt" in source
    assert "(14 * 15)" in source and "fitAreaCoverage < 0.2" in source
    assert "at least 20% is required" in source
    assert "points too close together, add the baseline corners or" in source
