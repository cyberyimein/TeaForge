"""Extract coverage.py data for the source files proven to be under test."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from teaforge.pcl.backends import normalize_pcl_framework, parse_documents_for_framework
from teaforge.process import WorkflowDeadline, bounded_process_detail, run_process

CoverageBranch = tuple[int, int] | tuple[int, int, str]
PYTEST_PROJECT_MARKERS = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")


@dataclass(slots=True)
class SourceFunction:
    name: str
    lineno: int
    end_lineno: int


@dataclass(slots=True)
class SourceCoverageSnapshot:
    source_path: Path
    c0_covered: int
    c0_total: int
    c1_covered: int
    c1_total: int
    executed_lines: set[int]
    missing_lines: set[int]
    executed_branches: set[CoverageBranch]
    missing_branches: set[CoverageBranch]


def discover_source_files(test_path: Path, framework: str = "pytest") -> list[Path]:
    """Return only source files that were resolved away from the test files."""
    normalized = normalize_pcl_framework(framework)
    if normalized == "jest":
        from teaforge.jest.coverage import discover_jest_source_files

        return discover_jest_source_files(test_path)
    if normalized == "angular":
        from teaforge.angular.coverage import discover_angular_source_files

        return discover_angular_source_files(test_path)
    if normalized == "playwright":
        raise ValueError("Coverage reports do not support framework: playwright")

    documents = parse_documents_for_framework(test_path, normalized)
    unresolved_documents = [document for document in documents if _document_uses_test_file_as_source(document)]
    if unresolved_documents:
        unresolved_tests = ", ".join(sorted(document.test_method for document in unresolved_documents))
        raise ValueError(
            "Could not determine the tested source file for: "
            f"{unresolved_tests}. Coverage reports require a resolvable production source target."
        )

    source_paths = sorted(
        {Path(document.source_path).resolve() for document in documents if document.source_path},
        key=lambda path: str(path),
    )
    if not source_paths:
        raise ValueError(f"Could not determine target source files from test path: {test_path}")
    return source_paths


def parse_source_functions(source_path: Path, framework: str = "pytest") -> list[SourceFunction]:
    """Collect measurable functions from one source file using the selected backend."""
    normalized = normalize_pcl_framework(framework)
    if normalized == "jest":
        from teaforge.jest.coverage import parse_jest_source_functions

        return parse_jest_source_functions(source_path)
    if normalized == "angular":
        from teaforge.angular.coverage import parse_angular_source_functions

        return parse_angular_source_functions(source_path)
    if normalized == "playwright":
        raise ValueError("Coverage reports do not support framework: playwright")

    return _parse_python_source_functions(source_path)


def _parse_python_source_functions(source_path: Path) -> list[SourceFunction]:
    """Collect top-level functions and class methods from a Python source file."""
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    functions: list[SourceFunction] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                SourceFunction(
                    name=node.name,
                    lineno=node.lineno,
                    end_lineno=node.end_lineno or node.lineno,
                )
            )
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(
                        SourceFunction(
                            name=f"{node.name}.{member.name}",
                            lineno=member.lineno,
                            end_lineno=member.end_lineno or member.lineno,
                        )
                    )
    return functions


def analyze_coverage(
    test_path: Path,
    source_paths: list[Path],
    framework: str = "pytest",
    *,
    timeout_seconds: int = 120,
    python_executable: Path | None = None,
) -> dict[Path, SourceCoverageSnapshot]:
    """Run the selected test framework and map coverage payloads back to each source file."""
    normalized = normalize_pcl_framework(framework)
    if normalized == "jest":
        from teaforge.jest.coverage import analyze_jest_coverage

        return analyze_jest_coverage(
            test_path, source_paths, timeout_seconds=timeout_seconds
        )
    if normalized == "angular":
        from teaforge.angular.coverage import analyze_angular_coverage

        return analyze_angular_coverage(
            test_path, source_paths, timeout_seconds=timeout_seconds
        )
    if normalized == "playwright":
        raise ValueError("Coverage reports do not support framework: playwright")

    selected_python = (python_executable or Path(sys.executable)).expanduser().absolute()
    if not selected_python.is_file():
        raise FileNotFoundError(
            f"Python executable does not exist: {selected_python}"
        )
    return _analyze_pytest_coverage(
        test_path,
        source_paths,
        timeout_seconds=timeout_seconds,
        python_executable=selected_python,
    )


def _analyze_pytest_coverage(
    pytest_path: Path,
    source_paths: list[Path],
    *,
    timeout_seconds: int,
    python_executable: Path,
) -> dict[Path, SourceCoverageSnapshot]:
    """Run pytest through coverage.py and map the JSON payload back to each source file."""
    _ensure_runtime_dependencies()

    resolved_pytest_path = pytest_path.resolve()
    resolved_sources = [path.resolve() for path in source_paths]
    source_roots = ",".join(
        dict.fromkeys(str(path.parent) for path in resolved_sources)
    )
    project_root = discover_pytest_project_root(resolved_pytest_path)
    deadline = WorkflowDeadline.start(
        "pytest coverage workflow",
        timeout_seconds,
    )
    with tempfile.TemporaryDirectory(prefix="teaforge-coverage-") as temp_dir:
        temp_root = Path(temp_dir)
        data_file = temp_root / ".coverage"
        json_output = temp_root / "coverage.json"

        run_result = run_process(
            [
                str(python_executable),
                "-m",
                "coverage",
                "run",
                "--branch",
                f"--source={source_roots}",
                f"--data-file={data_file}",
                "-m",
                "pytest",
                str(resolved_pytest_path),
            ],
            operation="pytest coverage collection",
            timeout_seconds=deadline.remaining_seconds(),
            cwd=project_root,
        )
        if run_result.returncode != 0:
            detail = bounded_process_detail(run_result.stderr, run_result.stdout)
            raise RuntimeError(
                "pytest failed while collecting coverage data. "
                f"Exit code: {run_result.returncode}. {detail}"
            )

        include_arg = _coverage_include_argument(resolved_sources, project_root)
        json_result = run_process(
            [
                str(python_executable),
                "-m",
                "coverage",
                "json",
                f"--data-file={data_file}",
                "-o",
                str(json_output),
                f"--include={include_arg}",
            ],
            operation="coverage.py JSON export",
            timeout_seconds=deadline.remaining_seconds(),
            cwd=project_root,
        )
        if json_result.returncode != 0:
            detail = bounded_process_detail(json_result.stderr, json_result.stdout)
            raise RuntimeError(
                "coverage.py failed to export JSON data. "
                f"Exit code: {json_result.returncode}. {detail}"
            )

        payload = json.loads(json_output.read_text(encoding="utf-8"))
    return _extract_snapshots(
        payload,
        resolved_sources,
        project_root=project_root,
    )


def discover_pytest_project_root(test_path: Path) -> Path:
    """Find the nearest pytest configuration root, with a local-path fallback."""
    resolved = test_path.expanduser().resolve()
    start = resolved if resolved.is_dir() else resolved.parent
    for candidate in (start, *start.parents):
        if any((candidate / marker).is_file() for marker in PYTEST_PROJECT_MARKERS):
            return candidate
    return start


def _coverage_include_argument(source_paths: list[Path], project_root: Path) -> str:
    """Match coverage.py data whether it stores absolute or project-relative names."""
    patterns: list[str] = []
    for source_path in source_paths:
        absolute = str(source_path)
        if absolute not in patterns:
            patterns.append(absolute)
        try:
            relative = str(source_path.relative_to(project_root))
        except ValueError:
            continue
        if relative not in patterns:
            patterns.append(relative)
    return ",".join(patterns)


def _ensure_runtime_dependencies() -> None:
    """Check that runtime tools needed for coverage execution are importable."""
    if importlib.util.find_spec("coverage") is None:
        raise RuntimeError(
            "coverage.py is required for coverage reports. Install it with: pip install coverage"
        )
    if importlib.util.find_spec("pytest") is None:
        raise RuntimeError(
            "pytest is required to execute tests. Install it with: pip install -e '.[dev]'"
        )


def _extract_snapshots(
    payload: dict,
    source_paths: list[Path],
    *,
    project_root: Path | None = None,
) -> dict[Path, SourceCoverageSnapshot]:
    """Convert coverage.json payloads into per-source snapshot dataclasses."""
    # coverage.py commonly emits paths relative to the target project's execution root.
    resolution_root = (project_root or Path.cwd()).resolve()
    file_entries = {
        _resolve_coverage_entry_path(file_name, resolution_root): file_payload
        for file_name, file_payload in payload.get("files", {}).items()
    }

    snapshots: dict[Path, SourceCoverageSnapshot] = {}
    for source_path in source_paths:
        file_payload = _match_file_payload(file_entries, source_path)
        summary = file_payload.get("summary", {})
        executed_lines = set(file_payload.get("executed_lines", []))
        missing_lines = set(file_payload.get("missing_lines", []))
        executed_branches = {
            tuple(branch) for branch in file_payload.get("executed_branches", [])
        }
        missing_branches = {
            tuple(branch) for branch in file_payload.get("missing_branches", [])
        }
        snapshots[source_path] = SourceCoverageSnapshot(
            source_path=source_path,
            c0_covered=int(summary.get("covered_lines", len(executed_lines))),
            c0_total=int(summary.get("num_statements", len(executed_lines | missing_lines))),
            c1_covered=int(summary.get("covered_branches", len(executed_branches))),
            c1_total=int(summary.get("num_branches", len(executed_branches | missing_branches))),
            executed_lines=executed_lines,
            missing_lines=missing_lines,
            executed_branches=executed_branches,
            missing_branches=missing_branches,
        )
    return snapshots


def _resolve_coverage_entry_path(file_name: str, project_root: Path) -> Path:
    candidate = Path(file_name)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def _match_file_payload(file_entries: dict[Path, dict], source_path: Path) -> dict:
    """Find the exact coverage payload for one resolved source file."""
    if source_path in file_entries:
        return file_entries[source_path]

    raise ValueError(f"coverage.py did not emit data for source file: {source_path}")


def _document_uses_test_file_as_source(document) -> bool:
    """Detect parser fallbacks where the test file could not be resolved to production code."""
    return (
        document.source_path == document.test_source_path
        and document.file == document.test_file
        and document.method == document.test_method
    )
