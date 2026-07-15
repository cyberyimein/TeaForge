"""Normalize user-facing names into stable filesystem-safe output names."""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def slugify(value: str) -> str:
    """Create kebab-case names for artifact files."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "item"


def folder_name(value: str) -> str:
    """Create snake_case names for grouping output directories."""
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return name or "item"


def source_folder_names(source_paths: Iterable[Path]) -> dict[Path, str]:
    """Build collision-free, mostly human-readable folders for source artifacts."""
    paths = list(dict.fromkeys(path.resolve() for path in source_paths))
    grouped: defaultdict[str, list[Path]] = defaultdict(list)
    for path in paths:
        grouped[folder_name(path.stem)].append(path)

    result: dict[Path, str] = {}
    for base_name, related in grouped.items():
        if len(related) == 1:
            result[related[0]] = base_name
            continue
        try:
            common_root = Path(os.path.commonpath([str(path) for path in related]))
            if common_root.suffix:
                common_root = common_root.parent
        except ValueError:
            common_root = None

        used: set[str] = set()
        for path in related:
            if common_root is not None:
                relative = path.with_suffix("").relative_to(common_root)
                candidate = folder_name("_".join(relative.parts))
            else:
                candidate = folder_name(f"{path.parent.name}_{path.stem}")
            if candidate in used:
                digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:8]
                candidate = f"{candidate}_{digest}"
            used.add(candidate)
            result[path] = candidate
    return result
