"""Build HTML coverage reports from validated source files and Mermaid assets."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path

from teaforge.artifacts import write_text_atomic
from teaforge.naming import folder_name, source_folder_names

from .analyzer import (
    SourceCoverageSnapshot,
    SourceFunction,
    analyze_coverage,
    discover_source_files,
    parse_source_functions,
)
from .mermaid import diagram_output_paths, render_mermaid_svg
from .models import CoverageDocument, CoverageMetric, DiagramArtifact, FunctionCoverage
from .render import render_coverage_html


@dataclass(slots=True, frozen=True)
class CoverageThresholdViolation:
    output_path: Path
    metric: str
    actual: float
    required: float

    def message(self) -> str:
        return (
            f"{self.output_path}: {self.metric} {self.actual:.1f}% is below "
            f"the required {self.required:.1f}%"
        )


class CoverageThresholdError(RuntimeError):
    """Signal that reports were written but one or more coverage gates failed."""

    def __init__(
        self,
        outputs: list[Path],
        violations: list[CoverageThresholdViolation],
    ) -> None:
        self.outputs = tuple(outputs)
        self.violations = tuple(violations)
        details = "\n".join(f"- {item.message()}" for item in violations)
        super().__init__(f"Coverage thresholds were not met:\n{details}")


def generate_coverage_reports(
    *,
    pytest_path: Path,
    html_output: Path,
    diagram_dir: Path,
    diagram_functions: list[str] | None = None,
    sequence_functions: list[str] | None = None,
    template_path: Path | None = None,
    framework: str = "pytest",
    runtime_timeout: int = 120,
    python_executable: Path | None = None,
    min_c0: float | None = None,
    min_c1: float | None = None,
) -> list[Path]:
    """Generate one report per source file, plus optional function flowchart pages."""
    if not pytest_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {pytest_path}")
    _validate_threshold("min_c0", min_c0)
    _validate_threshold("min_c1", min_c1)

    source_paths = discover_source_files(pytest_path, framework=framework)
    function_index = {
        source_path: parse_source_functions(source_path, framework=framework) for source_path in source_paths
    }
    _ensure_functions(function_index)
    flowchart_names = _resolve_selected_names(
        function_index, _normalize_requested_functions(diagram_functions)
    )
    sequence_names = _resolve_selected_names(
        function_index, _normalize_requested_functions(sequence_functions)
    )
    flowchart_index = _build_selected_index(function_index, flowchart_names)
    sequence_index = _build_selected_index(function_index, sequence_names)
    _ensure_diagrams(flowchart_index, diagram_dir, "flowchart")
    _ensure_diagrams(sequence_index, diagram_dir, "sequence")

    snapshots = analyze_coverage(
        pytest_path,
        source_paths,
        framework=framework,
        timeout_seconds=runtime_timeout,
        python_executable=python_executable,
    )
    html_output.parent.mkdir(parents=True, exist_ok=True)

    prepared_outputs: list[tuple[Path, str, CoverageDocument]] = []
    multiple_outputs = len(source_paths) > 1
    source_folders = source_folder_names(source_paths)
    for source_path in source_paths:
        snapshot = snapshots[source_path.resolve()]
        functions = function_index[source_path]
        flowcharts_for_source = {
            function.name for function in flowchart_index[source_path]
        }
        sequences_for_source = {
            function.name for function in sequence_index[source_path]
        }
        page_number = 2
        sections: list[FunctionCoverage] = []
        for function in functions:
            diagram_types: list[str] = []
            if function.name in flowcharts_for_source:
                diagram_types.append("flowchart")
            if function.name in sequences_for_source:
                diagram_types.append("sequence")
            page_numbers = list(range(page_number, page_number + len(diagram_types)))
            sections.append(
                _build_function_section(
                    source_path=source_path,
                    function=function,
                    snapshot=snapshot,
                    diagram_dir=diagram_dir,
                    diagram_types=diagram_types,
                    page_numbers=page_numbers,
                )
            )
            page_number += len(diagram_types)
        document = CoverageDocument.create(
            file=source_path.name,
            source_path=str(source_path),
            test_path=str(pytest_path.resolve()),
            c0=_build_metric(snapshot.c0_covered, snapshot.c0_total),
            c1=_build_metric(snapshot.c1_covered, snapshot.c1_total),
            requested_functions=sorted(flowcharts_for_source | sequences_for_source),
            functions=sections,
            evidence_source=_coverage_evidence_source(framework),
            c0_definition="covered statement lines / measurable statement lines",
            c1_definition="executed branch destinations / measurable branch destinations",
        )
        html_path = _resolve_output_path(
            source_path,
            html_output,
            multiple_outputs,
            source_folders[source_path.resolve()],
        )
        prepared_outputs.append(
            (
                html_path,
                render_coverage_html(document, template_path=template_path),
                document,
            )
        )

    outputs: list[Path] = []
    for html_path, html_content, _document in prepared_outputs:
        write_text_atomic(html_path, html_content)
        outputs.append(html_path)
    violations = find_coverage_threshold_violations(
        [(path, document) for path, _html, document in prepared_outputs],
        min_c0=min_c0,
        min_c1=min_c1,
    )
    if violations:
        raise CoverageThresholdError(outputs, violations)
    return outputs


def find_coverage_threshold_violations(
    reports: list[tuple[Path, CoverageDocument]],
    *,
    min_c0: float | None,
    min_c1: float | None,
) -> list[CoverageThresholdViolation]:
    """Evaluate file-level coverage metrics for deterministic CI gating."""
    violations: list[CoverageThresholdViolation] = []
    for output_path, document in reports:
        for metric_name, metric, required in (
            ("C0", document.c0, min_c0),
            ("C1", document.c1, min_c1),
        ):
            if required is not None and metric.applicable and metric.percent < required:
                violations.append(
                    CoverageThresholdViolation(
                        output_path=output_path,
                        metric=metric_name,
                        actual=metric.percent,
                        required=required,
                    )
                )
    return violations


def _validate_threshold(name: str, value: float | None) -> None:
    if value is not None and not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100: {value}")


def _coverage_evidence_source(framework: str) -> str:
    normalized = framework.strip().lower()
    if normalized == "pytest":
        return "coverage.py JSON"
    return "Jest/Istanbul coverage-final.json"


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


def _resolve_selected_names(
    function_index: dict[Path, list[SourceFunction]],
    selected_names: set[str],
) -> set[str]:
    """Resolve requested function names, allowing unique short-name matches for methods."""
    if not selected_names:
        return set()

    available_names = {function.name for functions in function_index.values() for function in functions}
    resolved_names: set[str] = set()
    missing_names: list[str] = []
    ambiguous_names: list[str] = []

    for requested_name in selected_names:
        if requested_name in available_names:
            resolved_names.add(requested_name)
            continue
        suffix_matches = sorted(
            name for name in available_names if name.endswith(f".{requested_name}")
        )
        if len(suffix_matches) == 1:
            resolved_names.add(suffix_matches[0])
            continue
        if len(suffix_matches) > 1:
            ambiguous_names.append(requested_name)
            continue
        missing_names.append(requested_name)

    if not missing_names and not ambiguous_names:
        return resolved_names

    message_parts: list[str] = []
    if missing_names:
        message_parts.append(
            "Requested flowchart functions were not found in the analyzed source files: "
            + ", ".join(sorted(missing_names))
        )
    if ambiguous_names:
        message_parts.append(
            "Requested flowchart functions matched multiple class methods. Use the full method name: "
            + ", ".join(sorted(ambiguous_names))
        )
    raise ValueError("\n".join(message_parts))


def _build_selected_index(
    function_index: dict[Path, list[SourceFunction]],
    selected_names: set[str],
) -> dict[Path, list[SourceFunction]]:
    """Filter the parsed function index down to the requested flowchart targets."""
    return {
        source_path: [function for function in functions if function.name in selected_names]
        for source_path, functions in function_index.items()
    }


def _ensure_diagrams(
    function_index: dict[Path, list[SourceFunction]],
    diagram_dir: Path,
    diagram_type: str,
) -> None:
    """Require Mermaid source files for every function selected for diagram pages."""
    if not any(functions for functions in function_index.values()):
        return

    missing: dict[Path, list[str]] = {}
    for source_path, functions in function_index.items():
        missing_functions = []
        for function in functions:
            mmd_path, _ = _resolve_diagram_paths(
                diagram_dir, source_path, function.name, diagram_type
            )
            if not mmd_path.exists():
                missing_functions.append(function.name)
        if missing_functions:
            missing[source_path] = missing_functions

    if not missing:
        return

    diagram_label = "flowcharts" if diagram_type == "flowchart" else "sequence diagrams"
    lines = [f"Missing Mermaid {diagram_label} for the coverage report:"]
    for source_path, function_names in missing.items():
        lines.append(f"- {source_path}: {', '.join(function_names)}")
    first_source, first_functions = next(iter(missing.items()))
    lines.append("")
    lines.append("Generate only the required business-function diagrams before creating the report. Example:")
    example_code = (
        "sequenceDiagram\\n    participant Client\\n    participant Target\\n"
        "    Client->>Target: Call business function\\n"
        "    Target-->>Client: Return result"
        if diagram_type == "sequence"
        else "flowchart TD\\n    A[Start] --> B{Valid?}\\n"
        "    B -- Yes --> C[Execute business logic]\\n"
        "    B -- No --> D[Return validation error]\\n"
        "    C --> E[Return result]"
    )
    lines.append(
        "teaforge mermaid generate "
        f"--source {first_source} "
        f"--function {first_functions[0]} "
        f"--diagram-type {diagram_type} "
        f'--code "{example_code}" '
        f"--output-dir {diagram_dir}"
    )
    raise ValueError("\n".join(lines))


def _build_function_section(
    *,
    source_path: Path,
    function: SourceFunction,
    snapshot: SourceCoverageSnapshot,
    diagram_dir: Path,
    diagram_types: list[str],
    page_numbers: list[int],
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

    diagrams: list[DiagramArtifact] = []
    for diagram_type, diagram_page_number in zip(
        diagram_types, page_numbers, strict=True
    ):
        mermaid_file, svg_file = _resolve_diagram_paths(
            diagram_dir, source_path, function.name, diagram_type
        )
        render_mermaid_svg(mermaid_file, svg_file)
        diagrams.append(
            DiagramArtifact(
                kind=diagram_type,
                page_number=diagram_page_number,
                mermaid_path=str(mermaid_file),
                svg_path=str(svg_file),
                svg_data_uri=_load_svg_data_uri(svg_file),
            )
        )

    primary_diagram = diagrams[0] if diagrams else None

    return FunctionCoverage(
        name=function.name,
        lineno=function.lineno,
        end_lineno=function.end_lineno,
        page_number=primary_diagram.page_number if primary_diagram else None,
        c0=_build_metric(covered_lines, len(relevant_lines)),
        c1=_build_metric(len(executed_branches), len(executed_branches | missing_branches)),
        missing_lines=missing_lines,
        missing_branches=[_format_branch(branch) for branch in sorted(missing_branches)],
        diagram_included=bool(diagrams),
        mermaid_path=primary_diagram.mermaid_path if primary_diagram else "",
        svg_path=primary_diagram.svg_path if primary_diagram else "",
        svg_data_uri=primary_diagram.svg_data_uri if primary_diagram else "",
        diagrams=diagrams,
    )


def _resolve_output_path(
    source_path: Path,
    base_html: Path,
    multiple_outputs: bool,
    output_folder: str,
) -> Path:
    """Choose either the user path or a per-source report path for multi-file runs."""
    if not multiple_outputs:
        return base_html

    output_dir = base_html.parent / output_folder
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{folder_name(source_path.stem)}_coverage_report{base_html.suffix}"


def _build_metric(covered: int, total: int) -> CoverageMetric:
    """Build a coverage metric object with explicit missing and percent fields."""
    # A zero-sized metric means there was nothing measurable, not that coverage was perfect.
    percent = 0.0 if total == 0 else round((covered / total) * 100, 1)
    missing = max(total - covered, 0)
    return CoverageMetric(covered=covered, total=total, percent=percent, missing=missing)


def _branch_in_function(
    branch: tuple[int, int] | tuple[int, int, str],
    function: SourceFunction,
) -> bool:
    """Check whether a branch record starts inside the function line range."""
    start_line = branch[0]
    return function.lineno <= start_line <= function.end_lineno


def _format_branch(branch: tuple[int, int] | tuple[int, int, str]) -> str:
    """Render a branch tuple into a readable report label."""
    start, end = branch[:2]
    identity = f" [{branch[2]}]" if len(branch) == 3 else ""
    return f"{start} -> {'exit' if end < 0 else end}{identity}"


def _load_svg_data_uri(svg_path: Path) -> str:
    """Encode a rendered SVG file as a data URI for self-contained HTML output."""
    svg_content = svg_path.read_text(encoding="utf-8").strip()
    normalized = re.sub(r"^<\?xml[^>]*\?>\s*", "", svg_content, count=1)
    encoded = base64.b64encode(normalized.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _resolve_diagram_paths(
    diagram_dir: Path,
    source_path: Path,
    function_name: str,
    diagram_type: str = "flowchart",
) -> tuple[Path, Path]:
    """Resolve a Mermaid file path, allowing short-name fallback for class methods."""
    exact_paths = diagram_output_paths(
        diagram_dir, source_path, function_name, diagram_type
    )
    if exact_paths[0].exists() or "." not in function_name:
        return exact_paths

    short_name = function_name.rsplit(".", 1)[1]
    short_paths = diagram_output_paths(
        diagram_dir, source_path, short_name, diagram_type
    )
    if short_paths[0].exists():
        return short_paths
    return exact_paths
