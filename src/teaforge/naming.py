"""Normalize user-facing names into stable filesystem-safe output names."""

from __future__ import annotations

import re


def slugify(value: str) -> str:
    """Create kebab-case names for artifact files."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "item"


def folder_name(value: str) -> str:
    """Create snake_case names for grouping output directories."""
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return name or "item"
