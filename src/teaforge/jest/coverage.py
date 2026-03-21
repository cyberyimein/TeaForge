"""Extract Jest/Istanbul coverage data for resolved JS and TypeScript sources."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from teaforge.jest.parser import parse_jest_documents

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
    functions: list[SourceFunction] = []
    functions.extend(_parse_top_level_functions(source))
    functions.extend(_parse_arrow_functions(source))
    functions.extend(_parse_class_methods(source))
    functions.sort(key=lambda function: (function.lineno, function.name))
    return functions


def analyze_jest_coverage(
    test_path: Path,
    source_paths: list[Path],
) -> dict[Path, SourceCoverageSnapshot]:
    """Run Jest with Istanbul JSON coverage output and map it to resolved sources."""
    resolved_test_path = test_path.resolve()
    resolved_sources = [path.resolve() for path in source_paths]

    import tempfile

    with tempfile.TemporaryDirectory(prefix="teaforge-jest-coverage-") as temp_dir:
        temp_root = Path(temp_dir)
        coverage_dir = temp_root / "coverage"
        coverage_dir.mkdir(parents=True, exist_ok=True)
        coverage_file = coverage_dir / "coverage-final.json"

        try:
            run_result = subprocess.run(
                [
                    "npx",
                    "jest",
                    "--coverage",
                    "--coverageReporters=json",
                    "--coverageDirectory",
                    str(coverage_dir),
                    "--runInBand",
                    str(resolved_test_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Jest coverage execution requires `npx`. Install Node.js and Jest before running coverage reports."
            ) from exc

        if run_result.returncode != 0:
            detail = (run_result.stderr or run_result.stdout).strip()
            raise RuntimeError(
                "Jest failed while collecting coverage data. "
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
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Collect covered and missing branch edges from Istanbul branch maps."""
    executed_branches: set[tuple[int, int]] = set()
    missing_branches: set[tuple[int, int]] = set()
    for branch_id, branch in branches.items():
        branch_line = int(branch.get("line") or branch.get("loc", {}).get("start", {}).get("line", 0))
        locations = branch.get("locations", [])
        hits = branch_hits.get(branch_id, [])
        for index, location in enumerate(locations):
            destination = int(location.get("start", {}).get("line", branch_line))
            edge = (branch_line, destination)
            if index < len(hits) and int(hits[index]) > 0:
                executed_branches.add(edge)
            else:
                missing_branches.add(edge)

    missing_branches -= executed_branches
    return executed_branches, missing_branches


def _parse_top_level_functions(source: str) -> list[SourceFunction]:
    """Parse top-level function declarations from JS/TS source text."""
    from teaforge.coverage.analyzer import SourceFunction

    functions: list[SourceFunction] = []
    import re

    pattern = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
    for match in pattern.finditer(source):
        open_brace = match.end() - 1
        close_brace = _find_matching_brace(source, open_brace)
        if close_brace == -1:
            continue
        functions.append(
            SourceFunction(
                name=match.group("name"),
                lineno=_line_number_at(source, match.start()),
                end_lineno=_line_number_at(source, close_brace),
            )
        )
    return functions


def _parse_arrow_functions(source: str) -> list[SourceFunction]:
    """Parse top-level arrow-function variable declarations from JS/TS source text."""
    from teaforge.coverage.analyzer import SourceFunction

    functions: list[SourceFunction] = []
    import re

    pattern = re.compile(
        r"(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{"
    )
    for match in pattern.finditer(source):
        open_brace = match.end() - 1
        close_brace = _find_matching_brace(source, open_brace)
        if close_brace == -1:
            continue
        functions.append(
            SourceFunction(
                name=match.group("name"),
                lineno=_line_number_at(source, match.start()),
                end_lineno=_line_number_at(source, close_brace),
            )
        )
    return functions


def _parse_class_methods(source: str) -> list[SourceFunction]:
    """Parse class method declarations from JS/TS source text."""
    from teaforge.coverage.analyzer import SourceFunction

    methods: list[SourceFunction] = []
    import re

    class_pattern = re.compile(r"(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)[^\{]*\{")
    method_pattern = re.compile(r"^\s*(?:async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", re.MULTILINE)
    for class_match in class_pattern.finditer(source):
        class_name = class_match.group("name")
        class_open = class_match.end() - 1
        class_close = _find_matching_brace(source, class_open)
        if class_close == -1:
            continue
        body = source[class_open + 1 : class_close]
        body_offset = class_open + 1
        for method_match in method_pattern.finditer(body):
            method_name = method_match.group("name")
            if method_name == "constructor":
                continue
            method_start = body_offset + method_match.start()
            method_open = body_offset + method_match.end() - 1
            method_close = _find_matching_brace(source, method_open)
            if method_close == -1 or method_close > class_close:
                continue
            methods.append(
                SourceFunction(
                    name=f"{class_name}.{method_name}",
                    lineno=_line_number_at(source, method_start),
                    end_lineno=_line_number_at(source, method_close),
                )
            )
    return methods


def _find_matching_brace(source: str, open_index: int) -> int:
    """Find the matching closing brace in a JS/TS source block."""
    depth = 0
    cursor = open_index
    while cursor < len(source):
        char = source[cursor]
        if char in {'"', "'", "`"}:
            cursor = _skip_string_literal(source, cursor)
            if cursor == -1:
                return -1
            continue
        if source.startswith("//", cursor):
            newline = source.find("\n", cursor)
            if newline == -1:
                return -1
            cursor = newline + 1
            continue
        if source.startswith("/*", cursor):
            end_comment = source.find("*/", cursor + 2)
            if end_comment == -1:
                return -1
            cursor = end_comment + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return -1


def _skip_string_literal(source: str, cursor: int) -> int:
    """Skip past one string literal, returning the next cursor position."""
    quote = source[cursor]
    cursor += 1
    while cursor < len(source):
        char = source[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == quote:
            return cursor + 1
        cursor += 1
    return -1


def _line_number_at(source: str, index: int) -> int:
    """Translate a character offset into a 1-based source line number."""
    return source.count("\n", 0, index) + 1


def _document_uses_test_file_as_source(document) -> bool:
    """Detect parser fallbacks where the test file could not be resolved to production code."""
    return (
        document.source_path == document.test_source_path
        and document.file == document.test_file
        and document.method == document.test_method
    )