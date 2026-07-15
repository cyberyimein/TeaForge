"""Discover and execute the target project's own Jest installation safely."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from teaforge.discovery import discover_files
from teaforge.jest.parser import TEST_FILE_SUFFIXES
from teaforge.process import (
    ProcessResult,
    bounded_process_detail,
    run_process,
)


@dataclass(slots=True, frozen=True)
class JestProject:
    """Resolved Jest execution context for one test path."""

    root: Path
    executable: Path
    test_files: tuple[Path, ...]

    @classmethod
    def discover(cls, test_path: Path) -> "JestProject":
        """Resolve test files, config root, and the nearest installed Jest binary."""
        test_files = tuple(path.resolve() for path in collect_jest_test_files(test_path))
        if not test_files:
            raise RuntimeError(f"No executable Jest test files found under: {test_path}")
        root = discover_jest_project_root(test_path)
        return cls(
            root=root,
            executable=find_local_jest(root),
            test_files=test_files,
        )

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
        operation: str,
        environment: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        """Run Jest with stable cwd, timeout, and actionable process errors."""
        command = [str(self.executable), *arguments]
        try:
            return run_process(
                command,
                cwd=self.root,
                environment=(
                    dict(environment) if environment is not None else os.environ.copy()
                ),
                timeout_seconds=timeout_seconds,
                operation=operation,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"The project-local Jest executable disappeared: {self.executable}. "
                "Reinstall the target project's dependencies."
            ) from exc

    def setup_files_after_env(self, *, timeout_seconds: float) -> list[str]:
        """Read resolved setup files so listener injection preserves project behavior."""
        result = self.run(
            ["--showConfig", "--json"],
            timeout_seconds=timeout_seconds,
            operation="Reading the Jest configuration",
        )
        if result.returncode != 0:
            detail = bounded_process_detail(result.stderr, result.stdout)
            raise RuntimeError(
                "TeaForge could not read the Jest configuration before injecting its listener. "
                f"Exit code: {result.returncode}. {detail}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Jest --showConfig did not return valid JSON; TeaForge refused to replace "
                "the project's setupFilesAfterEnv configuration."
            ) from exc

        setup_files: list[str] = []
        for config in payload.get("configs", []):
            for setup_file in config.get("setupFilesAfterEnv", []):
                normalized = str(setup_file)
                if normalized and normalized not in setup_files:
                    setup_files.append(normalized)
        return setup_files


def discover_jest_project_root(test_path: Path) -> Path:
    """Find the nearest directory that owns Jest/package configuration."""
    start = test_path.resolve() if test_path.is_dir() else test_path.resolve().parent
    for candidate in (start, *start.parents):
        if any(
            (candidate / marker).exists()
            for marker in (
                "package.json",
                "jest.config.js",
                "jest.config.cjs",
                "jest.config.mjs",
                "jest.config.ts",
            )
        ):
            return candidate
    raise RuntimeError(
        f"Could not find a Jest project root for: {test_path}. "
        "TeaForge looks for package.json or jest.config.* in parent directories."
    )


def find_local_jest(project_root: Path) -> Path:
    """Find the nearest ancestor-installed Jest without invoking npx downloads."""
    executable_name = "jest.cmd" if os.name == "nt" else "jest"
    for candidate in (project_root, *project_root.parents):
        executable = candidate / "node_modules" / ".bin" / executable_name
        if executable.exists() and executable.is_file():
            return executable
    raise RuntimeError(
        f"No project-local Jest executable found from: {project_root}. "
        "Install the target project's dependencies before running TeaForge."
    )


def collect_jest_test_files(test_path: Path) -> list[Path]:
    """Expand a file or directory into exact Jest test paths."""
    return discover_files(
        test_path,
        is_candidate=lambda path: path.name.endswith(TEST_FILE_SUFFIXES),
    )
