"""Discover target-project files without descending into generated dependency trees."""

from __future__ import annotations

import os
from collections.abc import Callable, Collection
from pathlib import Path

DEFAULT_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)


def discover_files(
    path: Path,
    *,
    is_candidate: Callable[[Path], bool],
    excluded_directory_names: Collection[str] = DEFAULT_EXCLUDED_DIRECTORY_NAMES,
) -> list[Path]:
    """Return deterministic candidates while pruning known generated directories."""
    if path.is_file():
        return [path] if is_candidate(path) else []
    if not path.is_dir():
        return []

    excluded = frozenset(excluded_directory_names)
    files: list[Path] = []
    for current_root, directory_names, file_names in os.walk(
        path,
        topdown=True,
        followlinks=False,
    ):
        directory_names[:] = sorted(
            name for name in directory_names if name not in excluded
        )
        root = Path(current_root)
        for file_name in sorted(file_names):
            candidate = root / file_name
            if is_candidate(candidate):
                files.append(candidate)
    return files
