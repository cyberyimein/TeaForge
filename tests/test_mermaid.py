from pathlib import Path

import pytest
from typer.testing import CliRunner

import teaforge.cli as cli_module
from teaforge.cli import app
from teaforge.coverage import mermaid
from teaforge.coverage.mermaid import diagram_output_paths, validate_mermaid

runner = CliRunner()


def test_validate_mermaid_rejects_empty_input():
    with pytest.raises(ValueError, match="Mermaid code is required"):
        validate_mermaid("")


def test_mermaid_validate_command_shows_example_on_error():
    result = runner.invoke(app, ["mermaid", "validate", "--code", "start -> end"])

    assert result.exit_code == 1
    assert "Invalid Mermaid syntax" in result.output
    assert "flowchart TD" in result.output


def test_mermaid_validate_command_reports_missing_mmdc(monkeypatch):
    monkeypatch.setattr(
        cli_module,
        "validate_mermaid_with_renderer",
        lambda _code: (_ for _ in ()).throw(RuntimeError(mermaid.mmdc_install_message())),
    )

    result = runner.invoke(app, ["mermaid", "validate", "--code", "flowchart TD\n    A-->B"])

    assert result.exit_code == 1
    assert "requires `mmdc`" in result.output
    assert "npm install -g @mermaid-js/mermaid-cli" in result.output


def test_mermaid_generate_command_writes_expected_file(tmp_path, monkeypatch):
    source = Path("demo/fastapi_crud/app/main.py")
    monkeypatch.setattr(mermaid, "validate_mermaid_with_renderer", lambda code: validate_mermaid(code))

    result = runner.invoke(
        app,
        [
            "mermaid",
            "generate",
            "--source",
            str(source),
            "--function",
            "create_item",
            "--code",
            "flowchart TD\n    A[Start] --> B[End]",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    mmd_path, _ = diagram_output_paths(tmp_path, source, "create_item")
    assert mmd_path.exists()
    assert "flowchart TD" in mmd_path.read_text(encoding="utf-8")


def test_mermaid_generate_command_reports_missing_mmdc(tmp_path, monkeypatch):
    source = Path("demo/fastapi_crud/app/main.py")
    monkeypatch.setattr(
        mermaid,
        "validate_mermaid_with_renderer",
        lambda _code: (_ for _ in ()).throw(RuntimeError(mermaid.mmdc_install_message())),
    )

    result = runner.invoke(
        app,
        [
            "mermaid",
            "generate",
            "--source",
            str(source),
            "--function",
            "create_item",
            "--code",
            "flowchart TD\n    A[Start] --> B[End]",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "requires `mmdc`" in result.output
