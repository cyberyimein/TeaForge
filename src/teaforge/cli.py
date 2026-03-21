from __future__ import annotations

from pathlib import Path

import typer

from teaforge.coverage.mermaid import save_mermaid_diagram, validate_mermaid_with_renderer
from teaforge.coverage.service import generate_coverage_reports
from teaforge.pcl.pdf import export_pdf_from_html
from teaforge.pcl.service import generate_pcl, get_testcase_description, load_pcl_document

app = typer.Typer(help="TeaForge CLI: generate PCL and coverage reports from pytest tests.")
pcl_app = typer.Typer(help="PCL commands")
mermaid_app = typer.Typer(help="Mermaid commands")
coverage_app = typer.Typer(help="Coverage report commands")
app.add_typer(pcl_app, name="pcl")
app.add_typer(mermaid_app, name="mermaid")
app.add_typer(coverage_app, name="coverage")


@pcl_app.command("generate")
def pcl_generate(
    path: Path = typer.Option(..., "--path", help="pytest test file or directory"),
    output: Path = typer.Option(..., "--output", help="output html path"),
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
) -> None:
    """Generate PCL HTML and JSON from pytest tests."""
    try:
        generated_files = generate_pcl(
            pytest_path=path,
            html_output=output,
            json_output=json_output,
            template_path=template,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for html_path, json_path in generated_files:
        typer.echo(f"Generated HTML: {html_path}")
        typer.echo(f"Generated JSON: {json_path}")


@app.command("export")
def export_command(
    path: Path = typer.Option(..., "--path", help="input html path"),
    output: Path = typer.Option(..., "--output", help="output pdf path"),
) -> None:
    """Export PCL HTML to PDF."""
    try:
        export_pdf_from_html(path, output)
    except (RuntimeError, FileNotFoundError) as exc:
        typer.echo(f"Error: {exc}", err=True)
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
        typer.echo(f"Error: {exc}", err=True)
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
        typer.echo(f"Error: {exc}", err=True)
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
) -> None:
    """Validate Mermaid text and save it as a per-business-function .mmd file."""
    try:
        mmd_path = save_mermaid_diagram(
            code=code,
            source_path=source,
            function_name=function,
            output_dir=output_dir,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Generated Mermaid file: {mmd_path}")


@coverage_app.command("generate")
def coverage_generate(
    path: Path = typer.Option(..., "--path", help="pytest test file or directory"),
    output: Path = typer.Option(..., "--output", help="output html path"),
    function: list[str] | None = typer.Option(
        None,
        "--function",
        help="repeat to include a business function flowchart page; only key business functions need diagrams",
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
) -> None:
    """Generate a file-level C0/C1 report and optional flowchart pages for selected business functions."""
    try:
        generated_files = generate_coverage_reports(
            pytest_path=path,
            html_output=output,
            diagram_dir=diagram_dir,
            diagram_functions=function,
            template_path=template,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for html_path in generated_files:
        typer.echo(f"Generated coverage HTML: {html_path}")


if __name__ == "__main__":
    app()
