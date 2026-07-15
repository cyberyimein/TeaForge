import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from teaforge import __version__
from teaforge.cli import app
from teaforge.coverage.service import (
    CoverageThresholdError,
    CoverageThresholdViolation,
)
from teaforge.pcl.models import PCLDocument

runner = CliRunner()


def test_version_option_matches_package_version():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_generate_and_get_commands(tmp_path):
    html_path = tmp_path / "pcl.html"
    source = Path("tests/fixtures/test_sample_pytest.py")

    result = runner.invoke(
        app,
        ["pcl", "generate", "--path", str(source), "--output", str(html_path)],
    )
    assert result.exit_code == 0

    output_dir = tmp_path / "test_sample_pytest"
    generated_html = output_dir / "pcl-test-create-user-normal.html"
    generated_json = output_dir / "pcl-test-create-user-normal.json"
    assert generated_html.exists()
    assert generated_json.exists()
    assert (output_dir / "pcl-test-create-user-boundary.html").exists()
    assert (output_dir / "pcl-test-get-user-exceptional-not-found.html").exists()
    html_content = generated_html.read_text(encoding="utf-8")
    assert html_content.count('class="case-head"') == 25
    assert "Bug No." in html_content
    assert "実施日" in html_content

    get_result = runner.invoke(
        app,
        ["get", "--path", str(generated_html), "--testcase", "TC-001"],
    )
    assert get_result.exit_code == 0
    assert "テストケース番号: TC-001" in get_result.stdout


def test_get_command_reads_embedded_html_without_sibling_json(tmp_path):
    html_path = tmp_path / "pcl.html"
    source = Path("tests/fixtures/test_sample_pytest.py")

    result = runner.invoke(
        app,
        ["pcl", "generate", "--path", str(source), "--output", str(html_path)],
    )
    assert result.exit_code == 0

    generated_html = tmp_path / "test_sample_pytest" / "pcl-test-create-user-normal.html"
    generated_json = generated_html.with_suffix(".json")
    generated_json.unlink()

    get_result = runner.invoke(
        app,
        ["get", "--path", str(generated_html), "--testcase", "TC-001"],
    )
    assert get_result.exit_code == 0
    assert "テストケース番号: TC-001" in get_result.stdout


def test_help_command_shows_root_help():
    result = runner.invoke(app, ["help"])

    assert result.exit_code == 0
    assert "TeaForge CLI: generate PCL and coverage reports from automated tests." in result.stdout
    assert "pcl" in result.stdout
    assert "coverage" in result.stdout


def test_help_command_shows_nested_command_help():
    result = runner.invoke(app, ["help", "coverage", "generate"])

    assert result.exit_code == 0
    assert "Generate a file-level C0/C1 report" in result.stdout
    assert "--diagram-dir" in result.stdout


def test_help_command_rejects_unknown_path():
    result = runner.invoke(app, ["help", "unknown"])

    assert result.exit_code == 1
    assert "Unknown command path: unknown" in result.stderr


def test_generate_pcl_with_jest_framework(tmp_path):
    html_path = tmp_path / "pcl.html"
    source = Path("tests/fixtures/test_sample_jest.test.ts")

    result = runner.invoke(
        app,
        [
            "pcl",
            "generate",
            "--framework",
            "jest",
            "--path",
            str(source),
            "--output",
            str(html_path),
        ],
    )

    assert result.exit_code == 0
    output_dir = tmp_path / "user"
    assert (output_dir / "pcl-createuser.json").exists()
    assert (output_dir / "pcl-getuser.json").exists()


def test_generate_pcl_with_angular_framework(tmp_path):
    html_path = tmp_path / "pcl.html"
    source = Path("tests/fixtures/angular_sample")

    result = runner.invoke(
        app,
        [
            "pcl",
            "generate",
            "--framework",
            "angular",
            "--path",
            str(source),
            "--output",
            str(html_path),
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "user_page_component" / "pcl-userpagecomponent.json").exists()
    assert (tmp_path / "user_form_page_component" / "pcl-userformpagecomponent.json").exists()


def test_generate_pcl_with_playwright_framework(tmp_path):
    html_path = tmp_path / "pcl.html"
    source = Path("tests/fixtures/playwright_sample/user-page.spec.ts")

    result = runner.invoke(
        app,
        [
            "pcl",
            "generate",
            "--framework",
            "playwright",
            "--path",
            str(source),
            "--output",
            str(html_path),
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "user_page_spec" / "pcl-userspage.json").exists()
    assert (tmp_path / "user_page_spec" / "pcl-usersnewpage.json").exists()


def test_generate_pcl_rejects_unknown_framework(tmp_path):
    result = runner.invoke(
        app,
        [
            "pcl",
            "generate",
            "--framework",
            "unknown",
            "--path",
            str(Path("tests/fixtures/test_sample_pytest.py")),
            "--output",
            str(tmp_path / "pcl.html"),
        ],
    )

    assert result.exit_code == 1
    assert "Unsupported framework: unknown" in result.stderr


def test_generate_pcl_reports_missing_custom_template_without_traceback(tmp_path):
    missing_template = tmp_path / "missing-template.html"

    result = runner.invoke(
        app,
        [
            "pcl",
            "generate",
            "--path",
            "tests/fixtures/test_sample_pytest.py",
            "--output",
            str(tmp_path / "pcl.html"),
            "--template",
            str(missing_template),
        ],
    )

    assert result.exit_code == 1
    assert "PCL template does not exist" in result.stderr
    assert "Traceback" not in result.stderr


def test_runtime_report_returns_distinct_exit_code_when_jest_tests_failed(
    tmp_path, monkeypatch
):
    html_path = tmp_path / "pcl.html"
    json_path = tmp_path / "pcl.json"
    document = PCLDocument.create(
        file="user.js",
        method="createUser",
        source_path="src/user.js",
    )
    document.evidence_mode = "runtime"
    document.runtime_exit_code = 1
    document.runtime_tests_passed = False
    html_path.write_text("<html></html>", encoding="utf-8")
    json_path.write_text(
        json.dumps(document.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "teaforge.cli.generate_pcl",
        lambda **kwargs: [(html_path, json_path)],
    )

    result = runner.invoke(
        app,
        [
            "pcl",
            "generate",
            "--framework",
            "jest",
            "--evidence-mode",
            "runtime",
            "--path",
            "tests/fixtures/test_sample_jest.test.ts",
            "--output",
            str(html_path),
        ],
    )

    assert result.exit_code == 2
    assert "Reports were generated with failure evidence" in result.stderr

    accepted = runner.invoke(
        app,
        [
            "pcl",
            "generate",
            "--framework",
            "jest",
            "--evidence-mode",
            "runtime",
            "--allow-test-failures",
            "--path",
            "tests/fixtures/test_sample_jest.test.ts",
            "--output",
            str(html_path),
        ],
    )

    assert accepted.exit_code == 0


def test_pcl_document_rejects_unknown_future_schema():
    document = PCLDocument.create(
        file="user.py",
        method="create_user",
        source_path="src/user.py",
    )
    payload = document.to_dict()
    payload["schema_version"] = 999

    with pytest.raises(ValueError, match="Unsupported PCL schema version: 999"):
        PCLDocument.from_dict(payload)


def test_coverage_gate_preserves_report_and_returns_exit_code_three(
    tmp_path, monkeypatch
):
    output = tmp_path / "coverage.html"
    output.write_text("<html>coverage report</html>", encoding="utf-8")

    def fail_gate(**_kwargs):
        raise CoverageThresholdError(
            [output],
            [
                CoverageThresholdViolation(
                    output_path=output,
                    metric="C1",
                    actual=75.0,
                    required=100.0,
                )
            ],
        )

    monkeypatch.setattr("teaforge.cli.generate_coverage_reports", fail_gate)

    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--path",
            "demo/fastapi_crud/tests",
            "--output",
            str(output),
            "--min-c1",
            "100",
        ],
    )

    assert result.exit_code == 3
    assert output.exists()
    assert f"Generated coverage HTML: {output}" in result.stdout
    assert "C1 75.0% is below the required 100.0%" in result.stderr
