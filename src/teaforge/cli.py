from __future__ import annotations

from pathlib import Path

import typer

from teaforge.pcl.pdf import export_pdf_from_html
from teaforge.pcl.service import generate_pcl, get_testcase_description, load_pcl_document

app = typer.Typer(help="TeaForge CLI: generate PCL from pytest tests.")
pcl_app = typer.Typer(help="PCL commands")
app.add_typer(pcl_app, name="pcl")


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


if __name__ == "__main__":
    app()
