from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from teaforge.pcl.parser import parse_pytest_documents


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


def discover_source_files(pytest_path: Path) -> list[Path]:
    documents = parse_pytest_documents(pytest_path)
    source_paths = sorted(
        {Path(document.source_path).resolve() for document in documents if document.source_path},
        key=lambda path: str(path),
    )
    if not source_paths:
        raise ValueError(f"Could not determine target source files from pytest path: {pytest_path}")
    return source_paths


def parse_source_functions(source_path: Path) -> list[SourceFunction]:
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


def analyze_coverage(pytest_path: Path, source_paths: list[Path]) -> dict[Path, SourceCoverageSnapshot]:
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
    if source_path in file_entries:
        return file_entries[source_path]

    by_name = [payload for path, payload in file_entries.items() if path.name == source_path.name]
    if len(by_name) == 1:
        return by_name[0]

    raise ValueError(f"coverage.py did not emit data for source file: {source_path}")
