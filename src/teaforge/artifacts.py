"""Persist generated artifacts without exposing partially written files."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def json_for_html_script(payload: Any, *, indent: int | None = 2) -> str:
    """Serialize JSON without allowing values to terminate an HTML script element."""
    serialized = json.dumps(payload, ensure_ascii=False, indent=indent)
    return (
        serialized.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write and fsync a sibling temporary file before atomically replacing the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
