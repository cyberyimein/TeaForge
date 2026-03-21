"""Validate Mermaid text, persist diagram sources, and render SVG assets via mmdc."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from teaforge.naming import folder_name

MERMAID_EXAMPLE = """flowchart TD
    A[Start] --> B{Input valid?}
    B -- Yes --> C[Execute function]
    B -- No --> D[Return validation error]
    C --> E[Return response]
"""

_MERMAID_PREFIXES = (
    "flowchart ",
    "graph ",
    "sequenceDiagram",
    "stateDiagram",
    "classDiagram",
    "erDiagram",
    "journey",
    "gantt",
    "mindmap",
    "timeline",
)


def mmdc_install_message() -> str:
    """Return the canonical installation hint for the Mermaid CLI renderer."""
    return "Mermaid validation/rendering requires `mmdc`. Install it with: npm install -g @mermaid-js/mermaid-cli"


def validate_mermaid(code: str) -> str:
    """Reject empty or obviously invalid diagrams before invoking the external renderer."""
    normalized = code.strip()
    if not normalized:
        raise ValueError(
            "Mermaid code is required.\n"
            "Example:\n"
            f"{MERMAID_EXAMPLE}"
        )

    first_line = next((line.strip() for line in normalized.splitlines() if line.strip()), "")
    if not first_line.startswith(_MERMAID_PREFIXES):
        raise ValueError(
            "Invalid Mermaid syntax. Start the diagram with a Mermaid keyword such as "
            "`flowchart TD`.\n"
            "Example:\n"
            f"{MERMAID_EXAMPLE}"
        )
    return normalized + "\n"


def validate_mermaid_with_renderer(code: str) -> str:
    """Use mmdc for real syntax validation so generated assets match the report pipeline."""
    normalized = validate_mermaid(code)
    with tempfile.TemporaryDirectory(prefix="teaforge-mermaid-validate-") as temp_dir:
        temp_root = Path(temp_dir)
        mmd_path = temp_root / "diagram.mmd"
        svg_path = temp_root / "diagram.svg"
        mmd_path.write_text(normalized, encoding="utf-8")
        _run_mmdc(mmd_path, svg_path)
    return normalized


def diagram_file_stem(source_path: Path, function_name: str) -> str:
    """Keep Mermaid source and SVG names aligned with coverage report naming."""
    return f"{folder_name(source_path.stem)}_{folder_name(function_name)}_coverage_report"


def diagram_output_paths(diagram_dir: Path, source_path: Path, function_name: str) -> tuple[Path, Path]:
    """Return the expected Mermaid source path and rendered SVG path for one function."""
    stem = diagram_file_stem(source_path, function_name)
    return diagram_dir / f"{stem}.mmd", diagram_dir / f"{stem}.svg"


def save_mermaid_diagram(
    *,
    code: str,
    source_path: Path,
    function_name: str,
    output_dir: Path,
) -> Path:
    """Persist validated Mermaid text as the source-of-truth diagram artifact."""
    normalized = validate_mermaid_with_renderer(code)
    output_dir.mkdir(parents=True, exist_ok=True)
    mmd_path, _ = diagram_output_paths(output_dir, source_path, function_name)
    mmd_path.write_text(normalized, encoding="utf-8")
    return mmd_path


def render_mermaid_svg(mmd_path: Path, svg_path: Path) -> None:
    """Render one Mermaid source file into an SVG artifact using mmdc."""
    _run_mmdc(mmd_path, svg_path)


def _run_mmdc(mmd_path: Path, svg_path: Path) -> None:
    """Invoke the Mermaid CLI renderer and translate failures into actionable errors."""
    # Rendering is intentionally strict: if the external tool fails, report generation must fail too.
    renderer = shutil.which("mmdc")
    if renderer is None:
        raise RuntimeError(mmdc_install_message())

    svg_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [renderer, "-i", str(mmd_path), "-o", str(svg_path), "-b", "transparent"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if "Parse error" in detail:
            raise ValueError(
                "Invalid Mermaid syntax. Please fix the diagram and try again.\n"
                f"{detail}"
            )
        raise RuntimeError(
            f"Failed to render Mermaid SVG from {mmd_path.name}. {detail or 'No renderer output.'}"
        )
