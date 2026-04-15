"""Extract Angular/Jest Istanbul coverage data for resolved sources."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from teaforge.angular.parser import parse_angular_documents
from teaforge.jest.coverage import _extract_snapshots, parse_jest_source_functions

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
) -> dict[Path, SourceCoverageSnapshot]:
    """Run Jest/Istanbul coverage for Angular page-level tests."""
    resolved_test_path = test_path.resolve()
    resolved_sources = [path.resolve() for path in source_paths]

    with tempfile.TemporaryDirectory(prefix="teaforge-angular-coverage-") as temp_dir:
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
                "Angular coverage execution requires `npx` and Jest. Install Node.js and Jest before running coverage reports."
            ) from exc

        if run_result.returncode != 0:
            detail = (run_result.stderr or run_result.stdout).strip()
            raise RuntimeError(
                "Angular/Jest failed while collecting coverage data. "
                f"Exit code: {run_result.returncode}. {detail}"
            )

        if not coverage_file.exists():
            raise RuntimeError(
                "Angular/Jest did not emit coverage-final.json. Ensure Istanbul JSON output is available."
            )

        payload = json.loads(coverage_file.read_text(encoding="utf-8"))

    return _extract_snapshots(payload, resolved_sources)


def _document_uses_test_file_as_source(document) -> bool:
    return (
        document.source_path == document.test_source_path
        and document.file == document.test_file
        and document.method == document.test_method
    )
