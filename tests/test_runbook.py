from pathlib import Path


def test_runbook_documents_half_court_phone_setup_points_and_tape_check():
    runbook = (Path(__file__).resolve().parents[1] / "docs/RUNBOOK_TONIGHT.md").read_text(
        encoding="utf-8"
    )
    assert "mount one phone high near each" in runbook
    assert "corners (x=0) and midcourt-line corners (x=14)" in runbook
    assert "at least 20% of the half-court area" in runbook
    assert "at x=1 m and x=4 m" in runbook
    assert "held-out residuals for each phone" in runbook
