from pathlib import Path

import pytest
from typer.testing import CliRunner

import teaforge.cli as cli_module
from teaforge.cli import app
from teaforge.coverage import mermaid
from teaforge.coverage.mermaid import (
    detect_mermaid_diagram_type,
    diagram_output_paths,
    validate_mermaid,
)
from teaforge.process import ProcessResult, ProcessTimeoutError

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


def test_mermaid_generate_auto_detects_sequence_diagram(tmp_path, monkeypatch):
    source = Path("demo/fastapi_crud/app/main.py")
    code = (
        "sequenceDiagram\n"
        "    participant Client\n"
        "    participant API\n"
        "    Client->>API: create item\n"
        "    API-->>Client: created item"
    )
    monkeypatch.setattr(
        mermaid, "validate_mermaid_with_renderer", lambda value: validate_mermaid(value)
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
            code,
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert detect_mermaid_diagram_type(code) == "sequence"
    sequence_path, _ = diagram_output_paths(
        tmp_path, source, "create_item", "sequence"
    )
    flowchart_path, _ = diagram_output_paths(tmp_path, source, "create_item")
    assert sequence_path.exists()
    assert not flowchart_path.exists()


def test_mermaid_generate_rejects_unsupported_report_diagram_type(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        mermaid,
        "validate_mermaid_with_renderer",
        lambda value: validate_mermaid(value),
    )

    result = runner.invoke(
        app,
        [
            "mermaid",
            "generate",
            "--source",
            "demo/fastapi_crud/app/main.py",
            "--function",
            "create_item",
            "--code",
            "classDiagram\n    class User",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "flowcharts and sequence diagrams only" in result.stderr


def test_mermaid_generate_rejects_missing_source_file(tmp_path):
    result = runner.invoke(
        app,
        [
            "mermaid",
            "generate",
            "--source",
            str(tmp_path / "missing.py"),
            "--function",
            "create_item",
            "--code",
            "flowchart TD\n    A[Start] --> B[End]",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "Tested source file does not exist" in result.stderr


def test_mermaid_renderer_preserves_structured_timeout(tmp_path, monkeypatch):
    mmd_path = tmp_path / "diagram.mmd"
    svg_path = tmp_path / "diagram.svg"
    mmd_path.write_text("flowchart TD\n    A-->B\n", encoding="utf-8")
    monkeypatch.setattr(mermaid.shutil, "which", lambda _name: "/tools/mmdc")

    def time_out(command, **kwargs):
        raise ProcessTimeoutError(
            operation=kwargs["operation"],
            timeout_seconds=kwargs["timeout_seconds"],
            result=ProcessResult(
                args=tuple(command),
                returncode=-1,
                stdout="partial",
                stderr="",
                duration_seconds=120,
            ),
        )

    monkeypatch.setattr(mermaid, "run_process", time_out)

    with pytest.raises(ProcessTimeoutError) as error:
        mermaid.render_mermaid_svg(mmd_path, svg_path)

    assert error.value.code == "process-timeout"
    assert error.value.result.stdout == "partial"
