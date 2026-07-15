"""Extract Jest/Istanbul coverage data for resolved JS and TypeScript sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from teaforge.javascript.syntax import parse_source_functions as parse_javascript_source_functions
from teaforge.jest.parser import parse_jest_documents
from teaforge.jest.project import JestProject
from teaforge.process import bounded_process_detail

if TYPE_CHECKING:
    from teaforge.coverage.analyzer import SourceCoverageSnapshot, SourceFunction


def discover_jest_source_files(test_path: Path) -> list[Path]:
    """Return only source files that the Jest parser resolved away from the test files."""
    documents = parse_jest_documents(test_path)
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
        raise ValueError(f"Could not determine target source files from Jest path: {test_path}")
    return source_paths


def parse_jest_source_functions(source_path: Path) -> list[SourceFunction]:
    """Collect top-level functions and class methods from a JS/TS source file."""
    from teaforge.coverage.analyzer import SourceFunction

    source = source_path.read_text(encoding="utf-8")
    return [
        SourceFunction(
            name=function.name,
            lineno=function.start_line,
            end_lineno=function.end_line,
        )
        for function in parse_javascript_source_functions(
            source,
            suffix=source_path.suffix,
            source_name=str(source_path),
        )
    ]


def analyze_jest_coverage(
    test_path: Path,
    source_paths: list[Path],
    *,
    timeout_seconds: int = 120,
) -> dict[Path, SourceCoverageSnapshot]:
    """Run Jest with Istanbul JSON coverage output and map it to resolved sources."""
    return _analyze_jest_coverage(
        test_path,
        source_paths,
        timeout_seconds=timeout_seconds,
        operation="Jest coverage collection",
    )


def _analyze_jest_coverage(
    test_path: Path,
    source_paths: list[Path],
    *,
    timeout_seconds: int,
    operation: str,
) -> dict[Path, SourceCoverageSnapshot]:
    """Execute the project-local Jest once and parse its Istanbul payload."""
    project = JestProject.discover(test_path)
    resolved_sources = [path.resolve() for path in source_paths]

    import tempfile

    with tempfile.TemporaryDirectory(prefix="teaforge-jest-coverage-") as temp_dir:
        temp_root = Path(temp_dir)
        coverage_dir = temp_root / "coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        coverage_file = coverage_dir / "coverage-final.json"

        run_result = project.run(
            [
                "--coverage",
                "--coverageReporters=json",
                "--coverageDirectory",
                str(coverage_dir),
                "--runInBand",
                "--runTestsByPath",
                *[str(path) for path in project.test_files],
            ],
            timeout_seconds=timeout_seconds,
            operation=operation,
        )

        if run_result.returncode != 0:
            detail = bounded_process_detail(run_result.stderr, run_result.stdout)
            raise RuntimeError(
                f"{operation} failed. "
                f"Exit code: {run_result.returncode}. {detail}"
            )

        if not coverage_file.exists():
            raise RuntimeError(
                "Jest did not emit coverage-final.json. Ensure Jest coverage is enabled and Istanbul JSON output is available."
            )

        payload = json.loads(coverage_file.read_text(encoding="utf-8"))

    return _extract_snapshots(payload, resolved_sources)


def _extract_snapshots(
    payload: dict,
    source_paths: list[Path],
) -> dict[Path, SourceCoverageSnapshot]:
    """Convert coverage-final.json payloads into per-source snapshot dataclasses."""
    from teaforge.coverage.analyzer import SourceCoverageSnapshot

    file_entries = {
        Path(file_name).resolve(): file_payload for file_name, file_payload in payload.items()
    }

    snapshots: dict[Path, SourceCoverageSnapshot] = {}
    for source_path in source_paths:
        file_payload = file_entries.get(source_path)
        if file_payload is None:
            raise ValueError(f"Jest coverage did not emit data for source file: {source_path}")

        statements = file_payload.get("statementMap", {})
        statement_hits = file_payload.get("s", {})
        branches = file_payload.get("branchMap", {})
        branch_hits = file_payload.get("b", {})

        executed_lines, missing_lines = _collect_line_sets(statements, statement_hits)
        executed_branches, missing_branches = _collect_branch_sets(branches, branch_hits)
        snapshots[source_path] = SourceCoverageSnapshot(
            source_path=source_path,
            c0_covered=sum(1 for value in statement_hits.values() if int(value) > 0),
            c0_total=len(statements),
            c1_covered=sum(sum(1 for hit in hits if int(hit) > 0) for hits in branch_hits.values()),
            c1_total=sum(len(branch.get("locations", [])) for branch in branches.values()),
            executed_lines=executed_lines,
            missing_lines=missing_lines,
            executed_branches=executed_branches,
            missing_branches=missing_branches,
        )
    return snapshots


def _collect_line_sets(
    statements: dict,
    statement_hits: dict,
) -> tuple[set[int], set[int]]:
    """Collect covered and missing source lines from Istanbul statement maps."""
    executed_lines: set[int] = set()
    missing_lines: set[int] = set()
    for statement_id, statement in statements.items():
        start_line = int(statement["start"]["line"])
        end_line = int(statement["end"]["line"])
        target = executed_lines if int(statement_hits.get(statement_id, 0)) > 0 else missing_lines
        target.update(range(start_line, end_line + 1))

    missing_lines -= executed_lines
    return executed_lines, missing_lines


def _collect_branch_sets(
    branches: dict,
    branch_hits: dict,
) -> tuple[set[tuple[int, int, str]], set[tuple[int, int, str]]]:
    """Collect covered and missing branch edges from Istanbul branch maps."""
    executed_branches: set[tuple[int, int, str]] = set()
    missing_branches: set[tuple[int, int, str]] = set()
    for branch_id, branch in branches.items():
        branch_line = int(branch.get("line") or branch.get("loc", {}).get("start", {}).get("line", 0))
        locations = branch.get("locations", [])
        hits = branch_hits.get(branch_id, [])
        for index, location in enumerate(locations):
            destination = int(location.get("start", {}).get("line", branch_line))
            edge = (branch_line, destination, f"{branch_id}:{index}")
            if index < len(hits) and int(hits[index]) > 0:
                executed_branches.add(edge)
            else:
                missing_branches.add(edge)

    missing_branches -= executed_branches
    return executed_branches, missing_branches


def _document_uses_test_file_as_source(document) -> bool:
    """Detect parser fallbacks where the test file could not be resolved to production code."""
    return (
        document.source_path == document.test_source_path
        and document.file == document.test_file
        and document.method == document.test_method
    )
