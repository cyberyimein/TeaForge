import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from teaforge.cli import app
from teaforge.coverage import mermaid as mermaid_module
from teaforge.coverage import service as coverage_service
from teaforge.coverage.analyzer import analyze_coverage
from teaforge.coverage.mermaid import save_mermaid_diagram
from teaforge.coverage.models import CoverageDocument, CoverageMetric
from teaforge.coverage.render import render_coverage_html
from teaforge.coverage.service import find_coverage_threshold_violations
from teaforge.jest.coverage import _collect_branch_sets
from teaforge.jest.project import JestProject

runner = CliRunner()


def test_coverage_embedded_json_cannot_close_its_script_element():
    document = CoverageDocument.create(
        file="</script><script>alert('tea')</script>.py",
        source_path="src/app.py",
        test_path="tests/test_app.py",
        c0=CoverageMetric(covered=1, total=1, percent=100.0),
        c1=CoverageMetric(covered=0, total=0, percent=0.0),
        requested_functions=[],
        functions=[],
        evidence_source="coverage.py JSON",
        c0_definition="covered statements / measurable statements",
        c1_definition="executed branches / measurable branches",
    )

    html = render_coverage_html(document)
    embedded_json = html.split(
        '<script id="teaforge-coverage-data" type="application/json">', 1
    )[1].split("</script>", 1)[0]

    assert "<script>" not in embedded_json
    assert "\\u003c/script\\u003e" in embedded_json


def test_coverage_thresholds_are_evaluated_per_output_file():
    document = CoverageDocument.create(
        file="user.py",
        source_path="src/user.py",
        test_path="tests/test_user.py",
        c0=CoverageMetric(covered=8, total=10, percent=80.0, missing=2),
        c1=CoverageMetric(covered=9, total=10, percent=90.0, missing=1),
        requested_functions=[],
        functions=[],
        evidence_source="coverage.py JSON",
        c0_definition="covered statements / measurable statements",
        c1_definition="executed branches / measurable branches",
    )

    violations = find_coverage_threshold_violations(
        [(Path("user-coverage.html"), document)],
        min_c0=85.0,
        min_c1=90.0,
    )

    assert len(violations) == 1
    assert violations[0].metric == "C0"
    assert "80.0% is below the required 85.0%" in violations[0].message()


def test_coverage_threshold_skips_non_applicable_metric():
    document = CoverageDocument.create(
        file="constant.py",
        source_path="src/constant.py",
        test_path="tests/test_constant.py",
        c0=CoverageMetric(covered=1, total=1, percent=100.0),
        c1=CoverageMetric(covered=0, total=0, percent=0.0),
        requested_functions=[],
        functions=[],
        evidence_source="coverage.py JSON",
        c0_definition="covered statements / measurable statements",
        c1_definition="executed branches / measurable branches",
    )

    violations = find_coverage_threshold_violations(
        [(Path("constant-coverage.html"), document)],
        min_c0=100.0,
        min_c1=100.0,
    )

    assert document.c1.applicable is False
    assert violations == []


def test_istanbul_branch_identity_does_not_collapse_same_line_locations():
    branches = {
        "0": {
            "line": 10,
            "locations": [
                {"start": {"line": 10}},
                {"start": {"line": 10}},
            ],
        }
    }

    executed, missing = _collect_branch_sets(branches, {"0": [1, 0]})

    assert executed == {(10, 10, "0:0")}
    assert missing == {(10, 10, "0:1")}


def test_python_coverage_can_use_target_project_interpreter(tmp_path, monkeypatch):
    python_executable = tmp_path / "project-venv" / "bin" / "python"
    python_executable.parent.mkdir(parents=True)
    python_executable.write_text("", encoding="utf-8")
    project_root = tmp_path / "project"
    source = project_root / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    test_file = project_root / "tests" / "test_app.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
        encoding="utf-8",
    )
    now = [100.0]
    timeout_budgets: list[float] = []
    monkeypatch.setattr("teaforge.process.time.monotonic", lambda: now[0])

    def fake_coverage_run(
        command: list[str],
        *,
        operation: str,
        timeout_seconds: float,
        cwd: Path,
    ):
        assert command[0] == str(python_executable)
        assert cwd == project_root
        timeout_budgets.append(timeout_seconds)
        if "json" in command:
            include_value = next(
                value.removeprefix("--include=")
                for value in command
                if value.startswith("--include=")
            )
            assert Path("src/app.py") in [
                Path(value) for value in include_value.split(",")
            ]
            output_path = Path(command[command.index("-o") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "src/app.py": {
                                "summary": {
                                    "covered_lines": 2,
                                    "num_statements": 2,
                                    "covered_branches": 0,
                                    "num_branches": 0,
                                },
                                "executed_lines": [1, 2],
                                "missing_lines": [],
                                "executed_branches": [],
                                "missing_branches": [],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
        else:
            now[0] += 7
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("teaforge.coverage.analyzer.run_process", fake_coverage_run)

    snapshots = analyze_coverage(
        test_file,
        [source],
        python_executable=python_executable,
    )

    assert snapshots[source.resolve()].c0_covered == 2
    assert timeout_budgets == pytest.approx([120.0, 113.0])


@pytest.fixture(autouse=True)
def bypass_mermaid_binary_for_source_persistence(monkeypatch):
    monkeypatch.setattr(
        mermaid_module,
        "validate_mermaid_with_renderer",
        lambda code: mermaid_module.validate_mermaid(code),
    )


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


@pytest.mark.skipif(
    importlib.util.find_spec("coverage") is None,
    reason="coverage.py is not installed",
)
def test_coverage_report_can_include_flowchart_and_sequence_for_same_function(
    tmp_path, monkeypatch
):
    source = Path("demo/fastapi_crud/app/main.py")
    diagram_dir = tmp_path / "files"
    save_mermaid_diagram(
        code=(
            "flowchart TD\n"
            "    A[Request] --> B{Valid?}\n"
            "    B -- Yes --> C[Create item]\n"
            "    B -- No --> D[Return error]"
        ),
        source_path=source,
        function_name="create_item",
        output_dir=diagram_dir,
    )
    save_mermaid_diagram(
        code=(
            "sequenceDiagram\n"
            "    participant Client\n"
            "    participant API\n"
            "    participant DB\n"
            "    Client->>API: create item\n"
            "    API->>DB: insert\n"
            "    DB-->>API: row\n"
            "    API-->>Client: response"
        ),
        source_path=source,
        function_name="create_item",
        output_dir=diagram_dir,
    )

    def fake_render_mermaid_svg(mmd_path: Path, svg_path: Path) -> None:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(
            f"<svg xmlns='http://www.w3.org/2000/svg'><text>{mmd_path.stem}</text></svg>",
            encoding="utf-8",
        )

    monkeypatch.setattr(coverage_service, "render_mermaid_svg", fake_render_mermaid_svg)
    output = tmp_path / "combined_coverage_report.html"

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
            "--sequence",
            "create_item",
        ],
    )

    assert result.exit_code == 0
    html = output.read_text(encoding="utf-8")
    assert html.count('class="page flowchart-page"') == 1
    assert html.count('class="page sequence-page"') == 1
    assert "シーケンス図" in html
    assert "2 / 3" in html
    assert "3 / 3" in html


def test_coverage_generate_with_jest_framework(tmp_path, monkeypatch):
    source = Path("tests/fixtures/jest_sample/src/user.ts").resolve()
    test_file = Path("tests/fixtures/test_sample_jest.test.ts").resolve()
    project = JestProject(
        root=test_file.parent,
        executable=test_file.parent / "node_modules" / ".bin" / "jest",
        test_files=(test_file,),
    )
    monkeypatch.setattr(
        JestProject,
        "discover",
        classmethod(lambda cls, path: project),
    )
    diagram_dir = tmp_path / "files"
    save_mermaid_diagram(
        code="flowchart TD\n    A[Receive input] --> B{Name valid?}\n    B -- Yes --> C[Create user]\n    B -- No --> D[Throw error]\n    C --> E[Return result]",
        source_path=source,
        function_name="createUser",
        output_dir=diagram_dir,
    )

    def fake_jest_run(
        command: list[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: int,
        operation: str,
    ):
        assert Path(command[0]) == project.executable
        assert "--runTestsByPath" in command
        assert cwd == Path("tests/fixtures").resolve()
        assert timeout_seconds == 120
        coverage_dir = Path(command[command.index("--coverageDirectory") + 1])
        payload = {
            str(source): {
                "path": str(source),
                "statementMap": {
                    "0": {"start": {"line": 1}, "end": {"line": 1}},
                    "1": {"start": {"line": 2}, "end": {"line": 3}},
                    "2": {"start": {"line": 5}, "end": {"line": 9}},
                    "3": {"start": {"line": 12}, "end": {"line": 14}},
                    "4": {"start": {"line": 15}, "end": {"line": 18}},
                },
                "s": {"0": 1, "1": 1, "2": 1, "3": 1, "4": 0},
                "branchMap": {
                    "0": {
                        "line": 2,
                        "type": "if",
                        "locations": [
                            {"start": {"line": 2}, "end": {"line": 3}},
                            {"start": {"line": 5}, "end": {"line": 9}},
                        ],
                    },
                    "1": {
                        "line": 12,
                        "type": "if",
                        "locations": [
                            {"start": {"line": 12}, "end": {"line": 14}},
                            {"start": {"line": 15}, "end": {"line": 18}},
                        ],
                    },
                },
                "b": {"0": [1, 1], "1": [1, 0]},
            }
        }
        coverage_dir.mkdir(parents=True, exist_ok=True)
        (coverage_dir / "coverage-final.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_render_mermaid_svg(mmd_path: Path, svg_path: Path) -> None:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(
            f"<svg xmlns='http://www.w3.org/2000/svg'><text>{mmd_path.stem}</text></svg>",
            encoding="utf-8",
        )

    monkeypatch.setattr("teaforge.jest.project.run_process", fake_jest_run)
    monkeypatch.setattr(coverage_service, "render_mermaid_svg", fake_render_mermaid_svg)

    output = tmp_path / "user_coverage_report.html"
    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--framework",
            "jest",
            "--path",
            "tests/fixtures/test_sample_jest.test.ts",
            "--output",
            str(output),
            "--diagram-dir",
            str(diagram_dir),
            "--function",
            "createUser",
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    html = output.read_text(encoding="utf-8")
    assert "Coverage Report - createUser" in html
    assert "getUser" in html
    assert "Not requested" in html
    assert "data:image/svg+xml;base64," in html


def test_coverage_generate_rejects_unknown_framework(tmp_path):
    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--framework",
            "unknown",
            "--path",
            "demo/fastapi_crud/tests",
            "--output",
            str(tmp_path / "main_coverage_report.html"),
            "--diagram-dir",
            str(tmp_path / "files"),
        ],
    )

    assert result.exit_code == 1
    assert "Unsupported framework: unknown" in result.stderr


def test_coverage_generate_with_angular_framework(tmp_path, monkeypatch):
    source = Path("tests/fixtures/angular_sample/user-page.component.ts").resolve()
    test_file = Path(
        "tests/fixtures/angular_sample/user-page.component.spec.ts"
    ).resolve()
    project = JestProject(
        root=test_file.parent,
        executable=test_file.parent / "node_modules" / ".bin" / "jest",
        test_files=(test_file,),
    )
    monkeypatch.setattr(
        JestProject,
        "discover",
        classmethod(lambda cls, path: project),
    )
    diagram_dir = tmp_path / "files"
    save_mermaid_diagram(
        code="flowchart TD\n    A[Open page] --> B{Name valid?}\n    B -- Yes --> C[Submit form]\n    B -- No --> D[Show validation error]\n    C --> E[Emit result]",
        source_path=source,
        function_name="submitForm",
        output_dir=diagram_dir,
    )

    def fake_angular_run(
        command: list[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: int,
        operation: str,
    ):
        assert Path(command[0]) == project.executable
        assert "--runTestsByPath" in command
        assert cwd == Path("tests/fixtures/angular_sample").resolve()
        assert timeout_seconds == 120
        coverage_dir = Path(command[command.index("--coverageDirectory") + 1])
        payload = {
            str(source): {
                "path": str(source),
                "statementMap": {
                    "0": {"start": {"line": 1}, "end": {"line": 1}},
                    "1": {"start": {"line": 4}, "end": {"line": 10}},
                    "2": {"start": {"line": 12}, "end": {"line": 17}},
                },
                "s": {"0": 1, "1": 1, "2": 1},
                "branchMap": {
                    "0": {
                        "line": 5,
                        "type": "if",
                        "locations": [
                            {"start": {"line": 5}, "end": {"line": 7}},
                            {"start": {"line": 8}, "end": {"line": 10}},
                        ],
                    }
                },
                "b": {"0": [1, 1]},
            }
        }
        coverage_dir.mkdir(parents=True, exist_ok=True)
        (coverage_dir / "coverage-final.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_render_mermaid_svg(mmd_path: Path, svg_path: Path) -> None:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(
            f"<svg xmlns='http://www.w3.org/2000/svg'><text>{mmd_path.stem}</text></svg>",
            encoding="utf-8",
        )

    monkeypatch.setattr("teaforge.jest.project.run_process", fake_angular_run)
    monkeypatch.setattr(coverage_service, "render_mermaid_svg", fake_render_mermaid_svg)

    output = tmp_path / "user_page_coverage_report.html"
    result = runner.invoke(
        app,
        [
            "coverage",
            "generate",
            "--framework",
            "angular",
            "--path",
            "tests/fixtures/angular_sample/user-page.component.spec.ts",
            "--output",
            str(output),
            "--diagram-dir",
            str(diagram_dir),
            "--function",
            "submitForm",
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    html = output.read_text(encoding="utf-8")
    assert "Coverage Report - submitForm" in html
    assert "data:image/svg+xml;base64," in html
