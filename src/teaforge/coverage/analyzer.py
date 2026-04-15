"""Extract coverage.py data for the source files proven to be under test."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from teaforge.pcl.backends import normalize_pcl_framework, parse_documents_for_framework


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
    executed_branches: set[tuple[int, int]]
    missing_branches: set[tuple[int, int]]


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
) -> dict[Path, SourceCoverageSnapshot]:
    """Run the selected test framework and map coverage payloads back to each source file."""
    normalized = normalize_pcl_framework(framework)
    if normalized == "jest":
        from teaforge.jest.coverage import analyze_jest_coverage

        return analyze_jest_coverage(test_path, source_paths)
    if normalized == "angular":
        from teaforge.angular.coverage import analyze_angular_coverage

        return analyze_angular_coverage(test_path, source_paths)
    if normalized == "playwright":
        raise ValueError("Coverage reports do not support framework: playwright")

    return _analyze_pytest_coverage(test_path, source_paths)


def _analyze_pytest_coverage(
    pytest_path: Path,
    source_paths: list[Path],
) -> dict[Path, SourceCoverageSnapshot]:
    """Run pytest through coverage.py and map the JSON payload back to each source file."""
    _ensure_runtime_dependencies()

    resolved_pytest_path = pytest_path.resolve()
    resolved_sources = [path.resolve() for path in source_paths]
    with tempfile.TemporaryDirectory(prefix="teaforge-coverage-") as temp_dir:
        temp_root = Path(temp_dir)
        data_file = temp_root / ".coverage"
        json_output = temp_root / "coverage.json"

        run_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--branch",
                f"--data-file={data_file}",
                "-m",
                "pytest",
                str(resolved_pytest_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if run_result.returncode != 0:
            detail = (run_result.stderr or run_result.stdout).strip()
            raise RuntimeError(
                "pytest failed while collecting coverage data. "
                f"Exit code: {run_result.returncode}. {detail}"
            )

        include_arg = ",".join(str(path) for path in resolved_sources)
        json_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                f"--data-file={data_file}",
                "-o",
                str(json_output),
                f"--include={include_arg}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if json_result.returncode != 0:
            detail = (json_result.stderr or json_result.stdout).strip()
            raise RuntimeError(
                "coverage.py failed to export JSON data. "
                f"Exit code: {json_result.returncode}. {detail}"
            )

        payload = json.loads(json_output.read_text(encoding="utf-8"))
    return _extract_snapshots(payload, resolved_sources)


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
) -> dict[Path, SourceCoverageSnapshot]:
    """Convert coverage.json payloads into per-source snapshot dataclasses."""
    # coverage.py may emit relative paths; resolving them once keeps matching deterministic.
    file_entries = {
        Path(file_name).resolve(): file_payload
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
