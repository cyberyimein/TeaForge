"""Expose TeaForge workflows as a small CLI surface over the service layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from typer.main import get_command as get_typer_command

from teaforge import __version__
from teaforge.coverage.mermaid import save_mermaid_diagram, validate_mermaid_with_renderer
from teaforge.coverage.service import CoverageThresholdError, generate_coverage_reports
from teaforge.doctor import format_doctor_report, inspect_capabilities
from teaforge.pcl.pdf import export_pdf_from_html
from teaforge.pcl.service import generate_pcl, get_testcase_description, load_pcl_document

app = typer.Typer(help="TeaForge CLI: generate PCL and coverage reports from automated tests.")
pcl_app = typer.Typer(help="PCL commands")
mermaid_app = typer.Typer(help="Mermaid commands")
coverage_app = typer.Typer(help="Coverage report commands")
app.add_typer(pcl_app, name="pcl")
app.add_typer(mermaid_app, name="mermaid")
app.add_typer(coverage_app, name="coverage")


def _error_code(error: Exception) -> str:
    """Map public failures to stable codes without leaking implementation types."""
    explicit_code = getattr(error, "code", None)
    if isinstance(explicit_code, str) and explicit_code:
        return explicit_code
    if isinstance(error, FileNotFoundError):
        return "file-not-found"
    if isinstance(error, ValueError):
        return "invalid-input"
    return "runtime-error"


def _emit_cli_error(error: Exception, *, json_output: bool = False) -> None:
    """Keep human errors concise and JSON-mode failures machine readable."""
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "schema_version": 1,
                    "teaforge_version": __version__,
                    "ready": False,
                    "error": {
                        "code": _error_code(error),
                        "message": str(error),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    typer.echo(f"Error: {error}", err=True)


def _version_callback(value: bool) -> bool:
    """Print the installed TeaForge version before command dispatch."""
    if value:
        typer.echo(__version__)
        raise typer.Exit()
    return value


@app.callback()
def root_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="show the TeaForge version and exit",
    ),
) -> None:
    """Generate auditable test specifications and coverage reports."""


@app.command("help")
def help_command(
    command_path: list[str] | None = typer.Argument(
        None,
        help="Optional command path such as 'pcl generate' or 'coverage generate'.",
    ),
) -> None:
    """Show help text for the CLI root or a nested command path."""
    try:
        command, info_name = _resolve_help_target(command_path or [])
    except ValueError as exc:
        _emit_cli_error(exc)
        raise typer.Exit(code=1) from exc

    with command.make_context(info_name, [], resilient_parsing=True) as context:
        help_text = command.get_help(context).rstrip()
    option_names = [
        option
        for parameter in command.params
        for option in getattr(parameter, "opts", ())
        if option.startswith("--")
    ]
    typer.echo(help_text)
    if option_names:
        typer.echo("\nOption names: " + ", ".join(dict.fromkeys(option_names)))


@app.command("doctor")
def doctor_command(
    framework: str = typer.Option(
        "pytest",
        "--framework",
        help="workflow to inspect: pytest, jest, angular, or playwright",
    ),
    path: Path | None = typer.Option(
        None,
        "--path",
        help="optional target test file or directory for project discovery",
    ),
    require_mermaid: bool = typer.Option(
        False,
        "--require-mermaid",
        help="treat a missing Mermaid renderer as an error",
    ),
    require_pdf: bool = typer.Option(
        False,
        "--require-pdf",
        help="treat an unavailable PDF renderer as an error",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="emit a machine-readable readiness report",
    ),
    timeout: int = typer.Option(
        10,
        "--timeout",
        min=1,
        help="maximum seconds for each version/capability check",
    ),
    python_executable: Path | None = typer.Option(
        None,
        "--python-executable",
        help="Python interpreter from the target project environment (pytest only)",
    ),
) -> None:
    """Check dependencies and target-project discovery without running tests."""
    try:
        report = inspect_capabilities(
            framework=framework,
            test_path=path,
            require_mermaid=require_mermaid,
            require_pdf=require_pdf,
            timeout_seconds=timeout,
            python_executable=python_executable,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit_cli_error(exc, json_output=json_output)
        raise typer.Exit(code=1) from exc
    typer.echo(report.to_json() if json_output else format_doctor_report(report))
    if not report.ready:
        raise typer.Exit(code=1)


@pcl_app.command("generate")
def pcl_generate(
    path: Path = typer.Option(..., "--path", help="test file or directory"),
    output: Path = typer.Option(..., "--output", help="output html path"),
    framework: str = typer.Option(
        "pytest",
        "--framework",
        help="test framework to parse: pytest, jest, angular, or playwright",
    ),
    json_output: Path | None = typer.Option(
        None,
        "--json-output",
        help="optional output json path (default: same name as html)",
    ),
    template: Path | None = typer.Option(
        None,
        "--template",
        help="optional custom html template path",
    ),
    evidence_mode: str = typer.Option(
        "static",
        "--evidence-mode",
        help="Jest assertion evidence: static, runtime, or auto fallback",
    ),
    runtime_timeout: int = typer.Option(
        120,
        "--runtime-timeout",
        min=1,
        help="maximum seconds for Jest runtime evidence collection",
    ),
    allow_test_failures: bool = typer.Option(
        False,
        "--allow-test-failures",
        help="return exit code 0 after writing a report that contains failing Jest tests",
    ),
) -> None:
    """Generate PCL HTML and JSON from pytest, Jest, Angular, or Playwright tests."""
    try:
        generated_files = generate_pcl(
            test_path=path,
            html_output=output,
            json_output=json_output,
            template_path=template,
            framework=framework,
            evidence_mode=evidence_mode,
            runtime_timeout=runtime_timeout,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        _emit_cli_error(exc)
        raise typer.Exit(code=1) from exc
    for html_path, json_path in generated_files:
        typer.echo(f"Generated HTML: {html_path}")
        typer.echo(f"Generated JSON: {json_path}")
    runtime_failed = any(
        load_pcl_document(json_path).runtime_tests_passed is False
        for _, json_path in generated_files
    )
    if runtime_failed and not allow_test_failures:
        typer.echo(
            "Warning: Jest tests failed. Reports were generated with failure evidence; "
            "TeaForge is returning exit code 2. Use --allow-test-failures to accept this result.",
            err=True,
        )
        raise typer.Exit(code=2)


@app.command("export")
def export_command(
    path: Path = typer.Option(..., "--path", help="input html path"),
    output: Path = typer.Option(..., "--output", help="output pdf path"),
) -> None:
    """Export PCL HTML to PDF."""
    try:
        export_pdf_from_html(path, output)
    except (RuntimeError, FileNotFoundError) as exc:
        _emit_cli_error(exc)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Generated PDF: {output}")


@app.command("get")
def get_command(
    path: Path = typer.Option(..., "--path", help="input json or html path"),
    testcase: str = typer.Option(..., "--testcase", help="testcase code or name"),
) -> None:
    """Get natural language description for one testcase."""
    try:
        document = load_pcl_document(path)
        description = get_testcase_description(document, testcase)
    except (FileNotFoundError, ValueError) as exc:
        _emit_cli_error(exc)
        raise typer.Exit(code=1) from exc
    typer.echo(description)


@mermaid_app.command("validate")
def mermaid_validate(
    code: str = typer.Option(
        ...,
        "--code",
        help="Mermaid text for one business function. Include if/else, validation, and error branches.",
    ),
) -> None:
    """Validate a detailed Mermaid flowchart for one business function."""
    try:
        validate_mermaid_with_renderer(code)
    except (RuntimeError, ValueError) as exc:
        _emit_cli_error(exc)
        raise typer.Exit(code=1) from exc
    typer.echo("Mermaid syntax looks valid.")


@mermaid_app.command("generate")
def mermaid_generate(
    source: Path = typer.Option(..., "--source", help="tested source file path"),
    function: str = typer.Option(
        ...,
        "--function",
        help="target business function or method name",
    ),
    code: str = typer.Option(
        ...,
        "--code",
        help="Detailed Mermaid for one business function. Include if/else, validation, and error branches.",
    ),
    output_dir: Path = typer.Option(
        Path("output/files"),
        "--output-dir",
        help="directory used to store .mmd files",
    ),
    diagram_type: str = typer.Option(
        "auto",
        "--diagram-type",
        help="diagram type: auto, flowchart, or sequence",
    ),
) -> None:
    """Validate Mermaid text and save it as a per-business-function .mmd file."""
    try:
        mmd_path = save_mermaid_diagram(
            code=code,
            source_path=source,
            function_name=function,
            output_dir=output_dir,
            diagram_type=diagram_type,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        _emit_cli_error(exc)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Generated Mermaid file: {mmd_path}")


@coverage_app.command("generate")
def coverage_generate(
    path: Path = typer.Option(..., "--path", help="test file or directory"),
    output: Path = typer.Option(..., "--output", help="output html path"),
    framework: str = typer.Option(
        "pytest",
        "--framework",
        help="test framework to analyze: pytest, jest, or angular",
    ),
    function: list[str] | None = typer.Option(
        None,
        "--function",
        help="repeat to include a business function flowchart page; only key business functions need diagrams",
    ),
    sequence: list[str] | None = typer.Option(
        None,
        "--sequence",
        help="repeat to include a business function sequence-diagram page",
    ),
    diagram_dir: Path = typer.Option(
        Path("output/files"),
        "--diagram-dir",
        help="directory containing per-function Mermaid files",
    ),
    template: Path | None = typer.Option(
        None,
        "--template",
        help="optional custom coverage report html template path",
    ),
    runtime_timeout: int = typer.Option(
        120,
        "--runtime-timeout",
        min=1,
        help="maximum seconds for test coverage collection",
    ),
    python_executable: Path | None = typer.Option(
        None,
        "--python-executable",
        help="Python interpreter from the target project environment (pytest coverage only)",
    ),
    min_c0: float | None = typer.Option(
        None,
        "--min-c0",
        min=0.0,
        max=100.0,
        help="minimum required file-level C0 percentage; writes reports and exits 3 on failure",
    ),
    min_c1: float | None = typer.Option(
        None,
        "--min-c1",
        min=0.0,
        max=100.0,
        help="minimum required file-level C1 percentage; writes reports and exits 3 on failure",
    ),
) -> None:
    """Generate a file-level C0/C1 report and optional flowchart pages for selected business functions."""
    try:
        generated_files = generate_coverage_reports(
            pytest_path=path,
            html_output=output,
            diagram_dir=diagram_dir,
            diagram_functions=function,
            sequence_functions=sequence,
            template_path=template,
            framework=framework,
            runtime_timeout=runtime_timeout,
            python_executable=python_executable,
            min_c0=min_c0,
            min_c1=min_c1,
        )
    except CoverageThresholdError as exc:
        for html_path in exc.outputs:
            typer.echo(f"Generated coverage HTML: {html_path}")
        typer.echo(f"Warning: {exc}", err=True)
        raise typer.Exit(code=3) from exc
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        _emit_cli_error(exc)
        raise typer.Exit(code=1) from exc
    for html_path in generated_files:
        typer.echo(f"Generated coverage HTML: {html_path}")


def _resolve_help_target(command_path: list[str]) -> tuple[Any, str]:
    """Resolve a nested command path into the Click command that owns its help text."""
    command = get_typer_command(app)
    resolved_path: list[str] = []
    for part in command_path:
        commands = getattr(command, "commands", None)
        if not isinstance(commands, dict):
            current_path = " ".join(resolved_path) or "teaforge"
            raise ValueError(f"Command path '{current_path}' does not accept subcommands.")

        next_command = commands.get(part)
        if next_command is None:
            requested_path = " ".join([*resolved_path, part])
            raise ValueError(f"Unknown command path: {requested_path}")

        command = next_command
        resolved_path.append(part)

    info_name = "teaforge"
    if resolved_path:
        info_name += " " + " ".join(resolved_path)
    return command, info_name


if __name__ == "__main__":
    app()
