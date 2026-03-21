"""Build HTML coverage reports from validated source files and Mermaid assets."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from teaforge.naming import folder_name

from .analyzer import (
    SourceCoverageSnapshot,
    SourceFunction,
    analyze_coverage,
    discover_source_files,
    parse_source_functions,
)
from .mermaid import diagram_output_paths, render_mermaid_svg
from .models import CoverageDocument, CoverageMetric, FunctionCoverage
from .render import render_coverage_html


def generate_coverage_reports(
    *,
    pytest_path: Path,
    html_output: Path,
    diagram_dir: Path,
    diagram_functions: list[str] | None = None,
    template_path: Path | None = None,
    framework: str = "pytest",
) -> list[Path]:
    """Generate one report per source file, plus optional function flowchart pages."""
    if not pytest_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {pytest_path}")

    source_paths = discover_source_files(pytest_path, framework=framework)
    function_index = {
        source_path: parse_source_functions(source_path, framework=framework) for source_path in source_paths
    }
    _ensure_functions(function_index)
    selected_names = _normalize_requested_functions(diagram_functions)
    _ensure_requested_functions_exist(function_index, selected_names)
    selected_index = _build_selected_index(function_index, selected_names)
    _ensure_diagrams(selected_index, diagram_dir)

    snapshots = analyze_coverage(pytest_path, source_paths, framework=framework)
    html_output.parent.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    multiple_outputs = len(source_paths) > 1
    for source_path in source_paths:
        snapshot = snapshots[source_path.resolve()]
        functions = function_index[source_path]
        selected_for_source = {function.name for function in selected_index[source_path]}
        page_number = 2
        sections: list[FunctionCoverage] = []
        for function in functions:
            include_diagram = function.name in selected_for_source
            sections.append(
                _build_function_section(
                    source_path=source_path,
                    function=function,
                    snapshot=snapshot,
                    diagram_dir=diagram_dir,
                    page_number=page_number if include_diagram else None,
                    include_diagram=include_diagram,
                )
            )
            if include_diagram:
                page_number += 1
        document = CoverageDocument.create(
            file=source_path.name,
            source_path=str(source_path),
            test_path=str(pytest_path.resolve()),
            c0=_build_metric(snapshot.c0_covered, snapshot.c0_total),
            c1=_build_metric(snapshot.c1_covered, snapshot.c1_total),
            requested_functions=[function.name for function in selected_index[source_path]],
            functions=sections,
        )
        html_path = _resolve_output_path(source_path, html_output, multiple_outputs)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(
            render_coverage_html(document, template_path=template_path),
            encoding="utf-8",
        )
        outputs.append(html_path)
    return outputs


def _ensure_functions(function_index: dict[Path, list[SourceFunction]]) -> None:
    """Fail early when a resolved source file contains no measurable functions."""
    empty_sources = [str(source_path) for source_path, functions in function_index.items() if not functions]
    if empty_sources:
        raise ValueError(
            "No functions were found in the following source files: "
            + ", ".join(empty_sources)
        )


def _normalize_requested_functions(diagram_functions: list[str] | None) -> set[str]:
    """Normalize repeated CLI function flags into a trimmed unique set."""
    if not diagram_functions:
        return set()
    return {name.strip() for name in diagram_functions if name.strip()}


def _ensure_requested_functions_exist(
    function_index: dict[Path, list[SourceFunction]],
    selected_names: set[str],
) -> None:
    """Reject requested flowchart names that do not exist in analyzed sources."""
    if not selected_names:
        return

    available_names = {function.name for functions in function_index.values() for function in functions}
    missing_names = sorted(selected_names - available_names)
    if not missing_names:
        return

    raise ValueError(
        "Requested flowchart functions were not found in the analyzed source files: "
        + ", ".join(missing_names)
    )


def _build_selected_index(
    function_index: dict[Path, list[SourceFunction]],
    selected_names: set[str],
) -> dict[Path, list[SourceFunction]]:
    """Filter the parsed function index down to the requested flowchart targets."""
    return {
        source_path: [function for function in functions if function.name in selected_names]
        for source_path, functions in function_index.items()
    }


def _ensure_diagrams(function_index: dict[Path, list[SourceFunction]], diagram_dir: Path) -> None:
    """Require Mermaid source files for every function selected for diagram pages."""
    if not any(functions for functions in function_index.values()):
        return

    missing: dict[Path, list[str]] = {}
    for source_path, functions in function_index.items():
        missing_functions = []
        for function in functions:
            mmd_path, _ = diagram_output_paths(diagram_dir, source_path, function.name)
            if not mmd_path.exists():
                missing_functions.append(function.name)
        if missing_functions:
            missing[source_path] = missing_functions

    if not missing:
        return

    lines = ["Missing Mermaid flowcharts for the coverage report:"]
    for source_path, function_names in missing.items():
        lines.append(f"- {source_path}: {', '.join(function_names)}")
    first_source, first_functions = next(iter(missing.items()))
    lines.append("")
    lines.append("Generate only the required business-function diagrams before creating the report. Example:")
    lines.append(
        "teaforge mermaid generate "
        f"--source {first_source} "
        f"--function {first_functions[0]} "
        '--code "flowchart TD\\n    A[Start] --> B{Valid?}\\n    B -- Yes --> C[Execute business logic]\\n    B -- No --> D[Return validation error]\\n    C --> E[Return result]" '
        f"--output-dir {diagram_dir}"
    )
    raise ValueError("\n".join(lines))


def _build_function_section(
    *,
    source_path: Path,
    function: SourceFunction,
    snapshot: SourceCoverageSnapshot,
    diagram_dir: Path,
    page_number: int | None,
    include_diagram: bool,
) -> FunctionCoverage:
    """Build the per-function coverage section rendered in the final HTML report."""
    # Function-level metrics are derived from the source line span already parsed from AST.
    line_scope = snapshot.executed_lines | snapshot.missing_lines
    relevant_lines = {
        line for line in line_scope if function.lineno <= line <= function.end_lineno
    }
    missing_lines = sorted(line for line in snapshot.missing_lines if line in relevant_lines)
    covered_lines = len(relevant_lines) - len(missing_lines)

    executed_branches = {
        branch for branch in snapshot.executed_branches if _branch_in_function(branch, function)
    }
    missing_branches = {
        branch for branch in snapshot.missing_branches if _branch_in_function(branch, function)
    }

    mermaid_path = ""
    svg_path = ""
    svg_data_uri = ""
    if include_diagram:
        mermaid_file, svg_file = diagram_output_paths(diagram_dir, source_path, function.name)
        render_mermaid_svg(mermaid_file, svg_file)
        mermaid_path = str(mermaid_file)
        svg_path = str(svg_file)
        svg_data_uri = _load_svg_data_uri(svg_file)

    return FunctionCoverage(
        name=function.name,
        lineno=function.lineno,
        end_lineno=function.end_lineno,
        page_number=page_number,
        c0=_build_metric(covered_lines, len(relevant_lines)),
        c1=_build_metric(len(executed_branches), len(executed_branches | missing_branches)),
        missing_lines=missing_lines,
        missing_branches=[_format_branch(branch) for branch in sorted(missing_branches)],
        diagram_included=include_diagram,
        mermaid_path=mermaid_path,
        svg_path=svg_path,
        svg_data_uri=svg_data_uri,
    )


def _resolve_output_path(source_path: Path, base_html: Path, multiple_outputs: bool) -> Path:
    """Choose either the user path or a per-source report path for multi-file runs."""
    if not multiple_outputs:
        return base_html

    output_dir = base_html.parent / folder_name(source_path.stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{folder_name(source_path.stem)}_coverage_report{base_html.suffix}"


def _build_metric(covered: int, total: int) -> CoverageMetric:
    """Build a coverage metric object with explicit missing and percent fields."""
    # A zero-sized metric means there was nothing measurable, not that coverage was perfect.
    percent = 0.0 if total == 0 else round((covered / total) * 100, 1)
    missing = max(total - covered, 0)
    return CoverageMetric(covered=covered, total=total, percent=percent, missing=missing)


def _branch_in_function(branch: tuple[int, int], function: SourceFunction) -> bool:
    """Check whether a branch record starts inside the function line range."""
    start_line = branch[0]
    return function.lineno <= start_line <= function.end_lineno


def _format_branch(branch: tuple[int, int]) -> str:
    """Render a branch tuple into a readable report label."""
    start, end = branch
    return f"{start} -> {'exit' if end < 0 else end}"


def _load_svg_data_uri(svg_path: Path) -> str:
    """Encode a rendered SVG file as a data URI for self-contained HTML output."""
    svg_content = svg_path.read_text(encoding="utf-8").strip()
    normalized = re.sub(r"^<\?xml[^>]*\?>\s*", "", svg_content, count=1)
    encoded = base64.b64encode(normalized.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
