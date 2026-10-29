"""Phase 03 B6 (D-053): run.json `power` holds AC or battery and the charge at the start and the
end of a run. What the OS does not say is null, never a guess."""

import pytest

from services.edge import power
from services.edge.power import SystemPowerStatus, read_power
from tests.edge.test_session import run_main, session_files, validate


def fake_os(monkeypatch, *answers):
    """Each call of the OS probe returns the next answer; the last one repeats."""
    queue = list(answers)

    def answer():
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(power, "system_power_status", answer)


def status(ac: int, percent: int) -> SystemPowerStatus:
    return SystemPowerStatus(ACLineStatus=ac, BatteryLifePercent=percent)


@pytest.mark.parametrize(
    "ac,percent,expected",
    [
        (1, 87, {"ac": True, "battery_percent": 87}),
        (0, 40, {"ac": False, "battery_percent": 40}),
        (1, 255, {"ac": True, "battery_percent": None}),  # a desktop: mains, no battery
        (255, 255, {"ac": None, "battery_percent": None}),  # the OS cannot say
        (255, 60, {"ac": None, "battery_percent": 60}),
    ],
)
def test_the_os_answer_is_mapped_and_unknown_is_null(monkeypatch, ac, percent, expected):
    fake_os(monkeypatch, status(ac, percent))
    assert read_power() == expected


def test_no_os_answer_is_all_null(monkeypatch):
    fake_os(monkeypatch, None)
    assert read_power() == {"ac": None, "battery_percent": None}


def test_a_failing_probe_does_not_stop_the_run(monkeypatch):
    def broken():
        raise OSError("no power API")

    monkeypatch.setattr(power, "system_power_status", broken)
    assert read_power() == {"ac": None, "battery_percent": None}


def test_a_run_records_the_power_state_at_start_and_end(monkeypatch, tmp_path, clips):
    fake_os(monkeypatch, status(1, 87), status(0, 84))
    out = tmp_path / "sessions"
    assert (
        run_main(
            monkeypatch, out, "--source", str(clips["moving"]), "--link", "file", "--no-detect"
        )
        == 0
    )
    _, run, _, _ = session_files(out)
    validate("run", run)
    assert run["power"] == {
        "start": {"ac": True, "battery_percent": 87},
        "end": {"ac": False, "battery_percent": 84},
    }


def test_an_unknown_os_answer_writes_null_in_the_run(monkeypatch, tmp_path, clips):
    fake_os(monkeypatch, status(255, 255))
    out = tmp_path / "sessions"
    assert (
        run_main(
            monkeypatch, out, "--source", str(clips["moving"]), "--link", "file", "--no-detect"
        )
        == 0
    )
    _, run, _, _ = session_files(out)
    validate("run", run)
    null = {"ac": None, "battery_percent": None}
    assert run["power"] == {"start": null, "end": null}
