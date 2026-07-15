import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from teaforge.cli import app

runner = CliRunner()


def test_doctor_reports_pytest_workflow_as_machine_readable_json():
    result = runner.invoke(
        app,
        [
            "doctor",
            "--framework",
            "pytest",
            "--path",
            "tests/fixtures/test_sample_pytest.py",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["framework"] == "pytest"
    assert payload["ready"] is True
    assert any(check["name"] == "pcl-template" for check in payload["checks"])
    syntax_check = next(
        check for check in payload["checks"] if check["name"] == "javascript-syntax"
    )
    assert syntax_check["status"] == "ok"


def test_doctor_rejects_missing_target_path(tmp_path):
    missing = tmp_path / "missing-tests"

    result = runner.invoke(
        app,
        ["doctor", "--framework", "pytest", "--path", str(missing)],
    )

    assert result.exit_code == 1
    assert "Path does not exist" in result.stdout
    assert "Ready: no" in result.stdout


def test_doctor_never_falls_back_to_npx_for_jest(tmp_path):
    test_file = tmp_path / "tests" / "user.test.js"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("test('ok', () => expect(1).toBe(1));", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}', encoding="utf-8")

    result = runner.invoke(
        app,
        ["doctor", "--framework", "jest", "--path", str(test_file)],
    )

    assert result.exit_code == 1
    assert "No project-local Jest executable" in result.stdout


def test_doctor_checks_the_requested_target_python():
    result = runner.invoke(
        app,
        [
            "doctor",
            "--framework",
            "pytest",
            "--path",
            "tests/fixtures/test_sample_pytest.py",
            "--python-executable",
            sys.executable,
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    pytest_check = next(
        check for check in payload["checks"] if check["name"] == "pytest"
    )
    assert str(Path(sys.executable).absolute()) in pytest_check["detail"]


def test_doctor_rejects_missing_target_python(tmp_path):
    missing_python = tmp_path / "venv" / "bin" / "python"

    result = runner.invoke(
        app,
        [
            "doctor",
            "--framework",
            "pytest",
            "--path",
            "tests/fixtures/test_sample_pytest.py",
            "--python-executable",
            str(missing_python),
        ],
    )

    assert result.exit_code == 1
    assert "Python executable does not exist" in result.stdout


def test_doctor_json_mode_keeps_service_errors_machine_readable():
    result = runner.invoke(
        app,
        ["doctor", "--framework", "unknown", "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["ready"] is False
    assert payload["error"]["code"] == "invalid-input"
    assert "Unsupported framework" in payload["error"]["message"]
