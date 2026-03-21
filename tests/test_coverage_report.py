import importlib.util
from pathlib import Path

import pytest
from typer.testing import CliRunner

from teaforge.cli import app
from teaforge.coverage import service as coverage_service
from teaforge.coverage.analyzer import parse_source_functions
from teaforge.coverage.mermaid import save_mermaid_diagram

runner = CliRunner()


def test_coverage_generate_without_selected_functions_builds_summary_only_report(tmp_path):
    output = tmp_path / "main_coverage_report.html"

    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--path",
            "demo/fastapi_crud/tests",
            "--output",
            str(output),
            "--diagram-dir",
            str(tmp_path / "files"),
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    html = output.read_text(encoding="utf-8")
    assert html.count('class="page summary-page"') == 1
    assert html.count('class="page flowchart-page"') == 0
    assert "必要な業務関数だけ `--function` を指定" in html


def test_coverage_generate_requires_selected_function_diagram(tmp_path):
    output = tmp_path / "main_coverage_report.html"

    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--path",
            "demo/fastapi_crud/tests",
            "--output",
            str(output),
            "--diagram-dir",
            str(tmp_path / "files"),
            "--function",
            "create_item",
        ],
    )

    assert result.exit_code == 1
    assert "Missing Mermaid flowcharts" in result.output
    assert "create_item" in result.output
    assert "business-function diagrams" in result.output


def test_coverage_generate_fails_when_source_cannot_be_inferred(tmp_path):
    output = tmp_path / "sample_coverage_report.html"

    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--path",
            "tests/fixtures/test_sample_pytest.py",
            "--output",
            str(output),
            "--diagram-dir",
            str(tmp_path / "files"),
        ],
    )

    assert result.exit_code == 1
    assert "Could not determine the tested source file" in result.output
    assert "Coverage reports require a resolvable production source target" in result.output


@pytest.mark.skipif(
    importlib.util.find_spec("coverage") is None,
    reason="coverage.py is not installed",
)
def test_coverage_generate_surfaces_missing_mmdc_message(tmp_path, monkeypatch):
    source = Path("demo/fastapi_crud/app/main.py")
    diagram_dir = tmp_path / "files"
    save_mermaid_diagram(
        code="flowchart TD\n    A[Start] --> B{Valid?}\n    B -- Yes --> C[Create item]\n    B -- No --> D[Return error]",
        source_path=source,
        function_name="create_item",
        output_dir=diagram_dir,
    )

    def fake_render_mermaid_svg(_mmd_path: Path, _svg_path: Path) -> None:
        raise RuntimeError(
            "Mermaid SVG rendering requires `mmdc`. Install it with: "
            "npm install -g @mermaid-js/mermaid-cli"
        )

    monkeypatch.setattr(coverage_service, "render_mermaid_svg", fake_render_mermaid_svg)

    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--path",
            "demo/fastapi_crud/tests",
            "--output",
            str(tmp_path / "main_coverage_report.html"),
            "--diagram-dir",
            str(diagram_dir),
            "--function",
            "create_item",
        ],
    )

    assert result.exit_code == 1
    assert "requires `mmdc`" in result.output
    assert "npm install -g @mermaid-js/mermaid-cli" in result.output


@pytest.mark.skipif(
    importlib.util.find_spec("coverage") is None,
    reason="coverage.py is not installed",
)
def test_coverage_generate_creates_multi_page_report(tmp_path, monkeypatch):
    source = Path("demo/fastapi_crud/app/main.py")
    diagram_dir = tmp_path / "files"
    for function_name in ["create_item", "list_items"]:
        save_mermaid_diagram(
            code="flowchart TD\n    A[Start] --> B{Valid?}\n    B -- Yes --> C[Run business logic]\n    B -- No --> D[Return error]\n    C --> E[Return response]",
            source_path=source,
            function_name=function_name,
            output_dir=diagram_dir,
        )

    def fake_render_mermaid_svg(mmd_path: Path, svg_path: Path) -> None:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(
            f"<svg xmlns='http://www.w3.org/2000/svg'><text>{mmd_path.stem}</text></svg>",
            encoding="utf-8",
        )

    monkeypatch.setattr(coverage_service, "render_mermaid_svg", fake_render_mermaid_svg)

    output = tmp_path / "main_coverage_report.html"
    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--path",
            "demo/fastapi_crud/tests",
            "--output",
            str(output),
            "--diagram-dir",
            str(diagram_dir),
            "--function",
            "create_item",
            "--function",
            "list_items",
        ],
    )

    assert result.exit_code == 0
    assert output.exists()

    html = output.read_text(encoding="utf-8")
    assert html.count('class="page summary-page"') == 1
    assert html.count('class="page flowchart-page"') == 2
    assert "Coverage Report - create_item" in html
    assert "Coverage Report - list_items" in html
    assert "Not requested" in html
    assert "data:image/svg+xml;base64," in html
    assert '<div class="diagram-box"><svg' not in html
    assert "@page summary" in html
    assert "@page flowchart" in html
    assert 'class="page summary-page"' in html
    assert 'class="page flowchart-page"' in html
    assert "Your AI agent generated this coverage report using TeaForge." in html
