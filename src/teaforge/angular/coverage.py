"""Extract Angular/Jest Istanbul coverage data for resolved sources."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from teaforge.angular.parser import parse_angular_documents
from teaforge.jest.coverage import _analyze_jest_coverage, parse_jest_source_functions

if TYPE_CHECKING:
    from teaforge.coverage.analyzer import SourceCoverageSnapshot, SourceFunction


def discover_angular_source_files(test_path: Path) -> list[Path]:
    """Return resolved source files from Angular/Jest page-level tests."""
    documents = parse_angular_documents(test_path)
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
        raise ValueError(f"Could not determine target source files from Angular path: {test_path}")
    return source_paths


def parse_angular_source_functions(source_path: Path) -> list[SourceFunction]:
    """Collect measurable functions from one Angular TypeScript source file."""
    return parse_jest_source_functions(source_path)


def analyze_angular_coverage(
    test_path: Path,
    source_paths: list[Path],
    *,
    timeout_seconds: int = 120,
) -> dict[Path, SourceCoverageSnapshot]:
    """Run Jest/Istanbul coverage for Angular page-level tests."""
    return _analyze_jest_coverage(
        test_path,
        source_paths,
        timeout_seconds=timeout_seconds,
        operation="Angular/Jest coverage collection",
    )


def _document_uses_test_file_as_source(document) -> bool:
    return (
        document.source_path == document.test_source_path
        and document.file == document.test_file
        and document.method == document.test_method
    )
