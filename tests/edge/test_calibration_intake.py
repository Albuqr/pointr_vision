import copy
import json
import uuid
from pathlib import Path

import pytest

from services.edge import contract
from services.edge.calibration import intake as intake_module
from services.edge.calibration.court import court_model
from services.edge.calibration.document import validate_calibration
from services.edge.calibration.homography import fit_calibration
from services.edge.calibration.intake import (
    Calibration,
    FromFile,
    FromRun,
    NotUsed,
    Refused,
    build_document,
    take_calibration,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "contracts" / "calibration.example.json"
SIZE = (640, 480)
NOW = "2026-10-30T12:00:00.000Z"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(intake_module, "utc_now", lambda: NOW)


def document():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["contract_version"] = contract.CONTRACT_VERSION
    return doc


def write(tmp_path, doc, name="calibration.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def legacy_kind_only(doc):
    doc = copy.deepcopy(doc)
    del doc["court"]["type"]
    return doc


def run_block():
    doc = document()
    return {
        "calibration_id": doc["calibration_id"],
        "check_error_m": doc["errors"]["check_mean_m"],
        "homography_image_to_court": doc["homography_image_to_court"],
        "court": {"type": "custom", "length_m": 3.0, "width_m": 2.0},
        "image_size": {"width": 640, "height": 480},
    }


def failed(reason):
    return [{"check": "calibration", "result": "failed", "detail": reason, "t_wall": NOW}]


# (id, offer builder taking tmp_path, camera_id, size, expected refusal fragment)
REFUSALS = [
    ("file unreadable", lambda p: FromFile(p / "missing.json"), "cam1", SIZE, "cannot read"),
    (
        "file not json",
        lambda p: FromFile(write(p, {}, "empty.json")),
        "cam1",
        SIZE,
        "calibration contract version",
    ),
    (
        "file fails the schema",
        lambda p: FromFile(write(p, {**document(), "forced": "yes"})),
        "cam1",
        SIZE,
        "calibration.schema.json",
    ),
    (
        "file singular homography",
        lambda p: FromFile(
            write(p, {**document(), "homography_image_to_court": [[1, 0, 0], [0, 1, 0], [0, 0, 0]]})
        ),
        "cam1",
        SIZE,
        "singular",
    ),
    (
        "file old format",
        lambda p: FromFile(write(p, {**document(), "contract_version": "0.1.0"})),
        "cam1",
        SIZE,
        "is not accepted",
    ),
    (
        "file for another camera",
        lambda p: FromFile(write(p, document())),
        "cam2",
        SIZE,
        "is for camera 'cam1', not 'cam2'",
    ),
    (
        "file without a camera id",
        lambda p: FromFile(write(p, document())),
        None,
        SIZE,
        "--camera-id is required",
    ),
    (
        "file of another size",
        lambda p: FromFile(write(p, document())),
        "cam1",
        (1280, 720),
        "differs from capture size 1280x720",
    ),
    (
        "run block not an object",
        lambda p: FromRun([1, 2]),
        "cam1",
        SIZE,
        "must be an object",
    ),
    (
        "run block missing a key",
        lambda p: FromRun({k: v for k, v in run_block().items() if k != "court"}),
        "cam1",
        SIZE,
        "lacks 'court'",
    ),
    (
        "run block bad court",
        lambda p: FromRun({**run_block(), "court": {**run_block()["court"], "type": "ice"}}),
        "cam1",
        SIZE,
        "court kind",
    ),
    (
        "run block court not an object",
        lambda p: FromRun({**run_block(), "court": ["fiba_full"]}),
        "cam1",
        SIZE,
        "must be objects",
    ),
    (
        "run block image_size not an object",
        lambda p: FromRun({**run_block(), "image_size": "1920x1080"}),
        "cam1",
        SIZE,
        "must be objects",
    ),
    (
        "run block bad matrix shape",
        lambda p: FromRun({**run_block(), "homography_image_to_court": [[1, 0], [0, 1]]}),
        "cam1",
        SIZE,
        "3 x 3",
    ),
    (
        "run block singular homography (B5)",
        lambda p: FromRun({**run_block(), "homography_image_to_court": [[0] * 3] * 3}),
        "cam1",
        SIZE,
        "singular",
    ),
    (
        "run block of another size",
        lambda p: FromRun(run_block()),
        "cam1",
        (1280, 720),
        "differs from capture size",
    ),
]


@pytest.mark.parametrize(
    ("offer", "camera_id", "size", "fragment"),
    [pytest.param(*row[1:], id=row[0]) for row in REFUSALS],
)
def test_edge_refusal_is_a_failed_calibration_check(tmp_path, offer, camera_id, size, fragment):
    verdict = take_calibration(offer(tmp_path), camera_id, size)

    assert verdict.calibration is None
    assert fragment in verdict.refused_at_edge
    assert verdict.checks == failed(verdict.refused_at_edge)
    assert [(e.kind, e.t_mono, e.detail) for e in verdict.events] == [
        ("error", None, f"calibration not used: {verdict.refused_at_edge}"),
        ("startup_check_failed", None, f"calibration: {verdict.refused_at_edge}"),
    ]


def test_operator_refusal_matches_what_main_writes():
    from services.edge import main

    verdict = take_calibration(Refused("points too few"), "cam1", SIZE)

    assert verdict.calibration is None
    assert verdict.refused_at_edge is None  # the operator refused, the edge detected nothing
    assert len(verdict.checks) == 1
    expected = main.failed_calibration_checks("points too few")[0]
    assert {**verdict.checks[0], "t_wall": None} == {**expected, "t_wall": None}
    (event,) = verdict.events
    old = main.calibration_failed_event("points too few")
    assert (event.kind, event.t_mono, event.detail) == (old.kind, old.t_mono, old.detail)


def test_studio_not_usable_is_an_error_event_and_no_check():
    verdict = take_calibration(NotUsed("saved file is invalid"), "cam1", SIZE)

    assert verdict.calibration is None
    assert verdict.checks is None
    assert verdict.refused_at_edge is None
    assert [(e.kind, e.t_mono, e.detail) for e in verdict.events] == [
        ("error", None, "calibration not used: saved file is invalid")
    ]


def test_no_offer_is_uncalibrated_and_silent():
    verdict = take_calibration(None, "cam1", SIZE)

    assert (verdict.calibration, verdict.events, verdict.checks, verdict.refused_at_edge) == (
        None,
        (),
        None,
        None,
    )


@pytest.mark.parametrize("legacy", [False, True], ids=["current court", "legacy kind-only court"])
def test_file_offer_is_taken_and_matches_the_existing_converters(tmp_path, legacy):
    doc = legacy_kind_only(document()) if legacy else document()
    path = write(tmp_path, doc)

    verdict = take_calibration(FromFile(path), "cam1", SIZE)

    calibration = verdict.calibration
    assert (verdict.events, verdict.checks, verdict.refused_at_edge) == ((), None, None)
    assert calibration.image_size == SIZE
    valid = validate_calibration(doc)
    assert calibration.session_block() == {
        "calibration_id": valid["calibration_id"],
        "check_error_m": valid["errors"]["check_mean_m"],
        "court": {"type": "custom", "length_m": 3.0, "width_m": 2.0},
    }
    assert calibration.run_block() == run_block()
    assert calibration.preview_court() == court_model(
        "custom", 3.0, 2.0, valid["court"]["landmarks"]
    )


def test_calibration_is_immutable():
    calibration = take_calibration(FromRun(run_block()), "cam1", SIZE).calibration

    with pytest.raises(AttributeError):
        calibration.calibration_id = "other"


def test_run_block_round_trips_and_is_taken():
    block = run_block()

    verdict = take_calibration(FromRun(block), "cam1", SIZE)

    assert verdict.refused_at_edge is None
    assert verdict.calibration.run_block() == block
    assert Calibration.from_run(verdict.calibration.run_block()).run_block() == block
    assert verdict.calibration.session_block() == {
        "calibration_id": block["calibration_id"],
        "check_error_m": block["check_error_m"],
        "court": block["court"],
    }


def test_run_block_is_not_changed_by_intake():
    block = run_block()
    before = copy.deepcopy(block)

    take_calibration(FromRun(block), "cam1", SIZE)

    assert block == before


def test_programming_errors_are_not_swallowed():
    with pytest.raises(TypeError):
        take_calibration("a path", "cam1", SIZE)


def fit_inputs():
    def point(x, y, role="calibration"):
        return {"image_px": [x * 100, y * 100], "court_m": [x, y], "role": role}

    points = [
        point(0, 0),
        point(4, 0),
        point(4, 3),
        point(0, 3),
        point(1, 1, "check"),
        point(3, 2, "check"),
    ]
    return points, court_model("custom", 28, 15)


def studio_document(points, court, camera_id, image_size, result, max_check_error_m, now):
    """Studio's `calibration_fit` as it builds the document today (services/app/server.py)."""
    result = {**result}
    result["court"] = {
        "kind": court.kind,
        "type": court.kind,
        "length_m": court.length_m,
        "width_m": court.width_m,
        "landmarks": court.landmarks,
    }
    result["point_errors_m"] = []
    calibration_index = check_index = 0
    for point in points:
        if point["role"] == "calibration":
            result["point_errors_m"].append(result["calibration_errors_m"][calibration_index])
            calibration_index += 1
        else:
            result["point_errors_m"].append(result["check_errors_m"][check_index])
            check_index += 1
    residual_iter = iter(result["point_errors_m"])
    return {
        "contract_version": contract.CONTRACT_VERSION,
        "calibration_id": "3f1c2a8e-5b7d-4e9a-8c21-6d4f0b9e7a13",
        "camera_id": camera_id,
        "created_at": now,
        "court": result["court"],
        "image_size": {"width": image_size[0], "height": image_size[1]},
        "homography_image_to_court": result["homography_image_to_court"],
        "points": [
            {
                "image_px": [float(v) for v in p["image_px"]],
                "court_m": [float(v) for v in p["court_m"]],
                "role": p["role"],
                "residual_m": next(residual_iter),
            }
            for p in points
        ],
        "errors": {
            key: result[key] for key in ("calibration_mean_m", "check_mean_m", "check_max_m")
        },
        "max_check_error_m": float(max_check_error_m),
        "forced": result["forced"],
        "audit_frame": "frame.jpg",
    }


def test_build_document_reproduces_studios_fit_and_validates():
    points, court = fit_inputs()
    fit = fit_calibration(points, 0.5, False, enforce_limit=True, require_checks=True)
    cid = str(uuid.uuid4())

    built = build_document(
        camera_id="cam1",
        court=court,
        image_size=(640, 480),
        points=points,
        fit=fit,
        max_check_error_m=0.5,
        calibration_id=cid,
        created_at=NOW,
    )

    expected = studio_document(points, court, "cam1", (640, 480), fit, 0.5, NOW)
    expected["calibration_id"] = cid
    assert built == expected
    validate_calibration(built)
    contract.validate("calibration", json.loads(json.dumps(built)))  # as written


def test_built_document_is_taken_by_intake(tmp_path):
    points, court = fit_inputs()
    fit = fit_calibration(points)
    built = build_document(
        camera_id="cam1",
        court=court,
        image_size=(640, 480),
        points=points,
        fit=fit,
        max_check_error_m=0.5,
        calibration_id=str(uuid.uuid4()),
        created_at=NOW,
    )

    verdict = take_calibration(FromFile(write(tmp_path, built)), "cam1", (640, 480))

    assert verdict.refused_at_edge is None
    assert verdict.calibration.session_block()["court"]["type"] == "custom"


def test_malformed_file_court_is_refused_instead_of_raising(tmp_path):
    verdict = take_calibration(
        FromFile(write(tmp_path, {**document(), "court": None})), "cam1", SIZE
    )
    assert verdict.calibration is None
    assert verdict.checks[0]["result"] == "failed"
    assert verdict.refused_at_edge
