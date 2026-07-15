import importlib.util

import pytest
from typer.testing import CliRunner

from teaforge.cli import app

runner = CliRunner()


def test_export_command_reports_missing_input_before_loading_pdf_dependency(tmp_path):
    result = runner.invoke(
        app,
        [
            "export",
            "--path",
            str(tmp_path / "missing.html"),
            "--output",
            str(tmp_path / "report.pdf"),
        ],
    )

    assert result.exit_code == 1
    assert "Input HTML does not exist" in result.stderr


@pytest.mark.skipif(
    importlib.util.find_spec("weasyprint") is None,
    reason="weasyprint is not installed",
)
def test_export_command_generates_pdf(tmp_path):
    html_path = tmp_path / "sample.html"
    html_path.write_text("<html><body><h1>TeaForge</h1></body></html>", encoding="utf-8")
    pdf_path = tmp_path / "sample.pdf"

    result = runner.invoke(
        app,
        ["export", "--path", str(html_path), "--output", str(pdf_path)],
    )
    combined_output = result.stdout + getattr(result, "stderr", "")
    if result.exit_code != 0 and "WeasyPrint system libraries are missing" in combined_output:
        pytest.skip("weasyprint runtime libraries are unavailable in this environment")
    assert result.exit_code == 0
    assert pdf_path.exists()
