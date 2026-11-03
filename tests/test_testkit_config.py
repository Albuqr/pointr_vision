"""Regression checks at the testkit configuration CLI boundary (#108)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG_CLI = ROOT / "testkit" / "bin" / "lib" / "config.py"


def run_config(command, config_file, **overrides):
    env = {key: value for key, value in os.environ.items() if not key.startswith("TESTKIT_")}
    env.update(TESTKIT_CONFIG=str(config_file), TESTKIT_PROJECT_ROOT=str(ROOT), **overrides)
    return subprocess.run(
        [sys.executable, str(CONFIG_CLI), command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_resolved_config_supports_anonymous_web_checks(tmp_path):
    config_file = tmp_path / "testkit.config.json"
    config_file.write_text(
        json.dumps({"web": {"publicPages": ["/", "/sessions"]}}), encoding="utf-8"
    )
    result = run_config("resolved", config_file, TESTKIT_BASE_URL="http://localhost:8123")
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert "auth" not in config
    assert "mobile" not in config
    assert "role" not in config["api"]
    assert "auth" not in config["web"]["checks"]
    assert "authorization" not in config["web"]["checks"]
    assert "checkSessionCookies" not in config["web"]["security"]
    assert config["web"]["publicPages"] == ["/", "/sessions"]
    assert config["web"]["baseUrl"] == "http://localhost:8123"
    validated = run_config("validate", config_file)
    assert validated.returncode == 0, validated.stdout + validated.stderr


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"web": {"baseUrl": "localhost:8123"}}, "web.baseUrl"),
        ({"python": {"coverageMin": 101}}, "python.coverageMin"),
    ],
)
def test_validate_still_rejects_invalid_supported_settings(tmp_path, override, message):
    config_file = tmp_path / "testkit.config.json"
    config_file.write_text(json.dumps(override), encoding="utf-8")
    result = run_config("validate", config_file)
    assert result.returncode == 1
    assert message in result.stdout


def test_repo_config_validates():
    result = run_config("validate", ROOT / "testkit.config.json")
    assert result.returncode == 0, result.stdout + result.stderr
