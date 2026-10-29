"""B13, the Studio side: what the operator is told when a calibration is refused, the choice to
start that camera uncalibrated, and the start that follows (D-057)."""

import pytest
from starlette.testclient import TestClient

from services.app.config import CameraConfig
from services.app.server import create_app
from tests.app.test_api import FakeLauncher
from tests.app.test_calibration_holdout import GOOD_FIT, payload, point
from tests.fixtures.make_clips import make_clips

BAD_CHECKS = [point((100, 100), (3, 2), "check"), point((300, 200), (1, 1), "check")]
GOOD_CHECKS = [point((100, 100), (1, 1), "check"), point((300, 200), (3, 2), "check")]
FIT_URL = "/api/cameras/clip/calibration/fit"
SAVE_URL = "/api/cameras/clip/calibration"
SKIP_URL = "/api/cameras/clip/calibration/uncalibrated"


@pytest.fixture
def studio(tmp_path):
    clips = make_clips(tmp_path)
    clip = clips["moving"]
    config = CameraConfig(tmp_path / "config.json")
    config.write(
        [
            {"camera_id": "clip", "source": str(clip), "link": "file"},
            {"camera_id": "other", "source": str(clips["frozen"]), "link": "file"},
        ]
    )
    FakeLauncher.instances.clear()
    app = create_app(str(tmp_path / "sessions"), config, FakeLauncher)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
        client.token = client.get("/api/cameras/clip/calibration/frame").headers["x-frame-token"]
        yield client


def test_too_few_points_say_how_many_are_there_and_needed(studio):
    response = studio.post(FIT_URL, json=payload(studio.token, GOOD_FIT[:3]))
    assert response.status_code == 422
    body = response.json()
    assert "four calibration points" in body["detail"]
    assert body["refusal"] == {
        "kind": "too_few_points",
        "role": "calibration",
        "have": 3,
        "need": 4,
    }
    response = studio.put(SAVE_URL, json=payload(studio.token, GOOD_FIT))
    assert response.json()["refusal"] == {
        "kind": "too_few_points", "role": "check", "have": 0, "need": 2,
    }  # fmt: skip


def test_a_check_error_over_the_limit_lists_each_check_error_and_the_mean(studio):
    response = studio.put(SAVE_URL, json=payload(studio.token, GOOD_FIT + BAD_CHECKS))
    assert response.status_code == 422
    refusal = response.json()["refusal"]
    assert refusal["kind"] == "check_error_over_limit"
    assert refusal["check_point_indices"] == [4, 5]
    assert refusal["max_check_error_m"] == 0.5
    assert [round(e, 2) for e in refusal["check_errors_m"]] == [2.24, 2.24]
    assert round(refusal["check_mean_m"], 2) == 2.24


def test_any_other_refusal_has_the_invalid_kind_and_a_message_not_a_traceback(studio):
    line = [point((i * 100, 50), (i, 1), "calibration") for i in range(4)]
    response = studio.post(FIT_URL, json=payload(studio.token, line))
    assert response.status_code == 422
    assert response.json()["refusal"] == {"kind": "invalid"}
    assert "collinear" in response.json()["detail"] and "Traceback" not in response.text


def test_starting_uncalibrated_needs_a_refusal_first(studio):
    assert studio.post(SKIP_URL).status_code == 409
    studio.post(FIT_URL, json=payload(studio.token, GOOD_FIT[:3]))
    skipped = studio.post(SKIP_URL)
    assert skipped.status_code == 200
    assert skipped.json()["camera_id"] == "clip"
    assert "four calibration points" in skipped.json()["reason"]
    assert studio.get("/api/status").json()["uncalibrated"] == {"clip": skipped.json()["reason"]}


def test_a_later_success_or_a_delete_takes_the_choice_back(studio):
    studio.put(SAVE_URL, json=payload(studio.token, GOOD_FIT + BAD_CHECKS))
    studio.post(SKIP_URL)
    assert studio.delete(SKIP_URL).status_code == 200
    assert studio.get("/api/status").json()["uncalibrated"] == {}
    studio.post(SKIP_URL)  # the refusal is still the last answer
    saved = studio.put(SAVE_URL, json=payload(studio.token, GOOD_FIT + GOOD_CHECKS))
    assert saved.status_code == 200, saved.text
    assert studio.get("/api/status").json()["uncalibrated"] == {}
    assert studio.post(SKIP_URL).status_code == 409  # the success cleared the refusal too


def test_the_start_after_the_choice_starts_that_camera_uncalibrated_and_not_the_others(studio):
    studio.put(SAVE_URL, json=payload(studio.token, GOOD_FIT + BAD_CHECKS))
    reason = studio.post(SKIP_URL).json()["reason"]
    started = studio.post("/api/recording/start")
    assert started.status_code == 200, started.text
    clip, other = FakeLauncher.instances[-1].cameras
    assert (clip.camera_id, clip.calibration_failed, clip.calibration_path) == (
        "clip",
        reason,
        None,
    )
    assert (other.calibration_failed, other.calibration_path) == (None, None)
    by_id = {c["camera_id"]: c for c in started.json()["cameras"]}
    assert reason in by_id["clip"]["calibration_warning"]
    assert by_id["other"]["calibration_warning"] is None


def test_the_choice_and_its_undo_are_in_the_audit_trail(studio):
    studio.put(SAVE_URL, json=payload(studio.token, GOOD_FIT + BAD_CHECKS))
    studio.post(SKIP_URL)
    studio.delete(SKIP_URL)
    audit = studio.app.state.studio.audit.path.read_text(encoding="utf-8")
    assert '"calibration_uncalibrated"' in audit
    assert '"calibration_uncalibrated_clear"' in audit
