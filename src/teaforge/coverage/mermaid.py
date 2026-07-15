"""Validate Mermaid text, persist diagram sources, and render SVG assets via mmdc."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from teaforge.artifacts import write_text_atomic
from teaforge.naming import folder_name
from teaforge.process import bounded_process_detail, run_process

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
DIAGRAM_TYPES = ("flowchart", "sequence")
DEFAULT_RENDER_TIMEOUT_SECONDS = 120
PUPPETEER_CONFIG_ENV = "TEAFORGE_MERMAID_PUPPETEER_CONFIG"


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


def detect_mermaid_diagram_type(code: str) -> str:
    """Classify the Mermaid source into a report-supported diagram type."""
    normalized = validate_mermaid(code)
    first_line = next(line.strip() for line in normalized.splitlines() if line.strip())
    if first_line.startswith("sequenceDiagram"):
        return "sequence"
    if first_line.startswith(("flowchart ", "graph ")):
        return "flowchart"
    raise ValueError(
        "TeaForge reports currently support Mermaid flowcharts and sequence diagrams only."
    )


def normalize_diagram_type(diagram_type: str, code: str | None = None) -> str:
    normalized = diagram_type.strip().lower()
    if normalized == "auto":
        if code is None:
            raise ValueError("Mermaid code is required when diagram type is auto.")
        return detect_mermaid_diagram_type(code)
    if normalized not in DIAGRAM_TYPES:
        raise ValueError(
            f"Unsupported diagram type: {diagram_type}. Supported values: auto, "
            + ", ".join(DIAGRAM_TYPES)
        )
    if code is not None and detect_mermaid_diagram_type(code) != normalized:
        raise ValueError(
            f"Mermaid source does not match --diagram-type {normalized}."
        )
    return normalized


def diagram_file_stem(
    source_path: Path,
    function_name: str,
    diagram_type: str = "flowchart",
) -> str:
    """Keep Mermaid source and SVG names aligned with coverage report naming."""
    base = f"{folder_name(source_path.stem)}_{folder_name(function_name)}"
    suffix = "sequence_diagram" if diagram_type == "sequence" else "coverage_report"
    return f"{base}_{suffix}"


def diagram_output_paths(
    diagram_dir: Path,
    source_path: Path,
    function_name: str,
    diagram_type: str = "flowchart",
) -> tuple[Path, Path]:
    """Return the expected Mermaid source path and rendered SVG path for one function."""
    stem = diagram_file_stem(source_path, function_name, diagram_type)
    return diagram_dir / f"{stem}.mmd", diagram_dir / f"{stem}.svg"


def save_mermaid_diagram(
    *,
    code: str,
    source_path: Path,
    function_name: str,
    output_dir: Path,
    diagram_type: str = "auto",
) -> Path:
    """Persist validated Mermaid text as the source-of-truth diagram artifact."""
    if not source_path.is_file():
        raise FileNotFoundError(f"Tested source file does not exist: {source_path}")
    resolved_type = normalize_diagram_type(diagram_type, code)
    normalized = validate_mermaid_with_renderer(code)
    output_dir.mkdir(parents=True, exist_ok=True)
    mmd_path, _ = diagram_output_paths(
        output_dir, source_path, function_name, resolved_type
    )
    write_text_atomic(mmd_path, normalized)
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
    command = [renderer, "-i", str(mmd_path), "-o", str(svg_path), "-b", "transparent"]
    puppeteer_config = os.environ.get(PUPPETEER_CONFIG_ENV)
    if puppeteer_config:
        config_path = Path(puppeteer_config).expanduser()
        if not config_path.is_file():
            raise FileNotFoundError(
                f"Mermaid Puppeteer config does not exist: {config_path}"
            )
        command.extend(["--puppeteerConfigFile", str(config_path)])
    result = run_process(
        command,
        operation=f"Mermaid rendering for {mmd_path.name}",
        timeout_seconds=DEFAULT_RENDER_TIMEOUT_SECONDS,
    )

    if result.returncode != 0:
        detail = bounded_process_detail(result.stderr, result.stdout)
        if "Parse error" in detail:
            raise ValueError(
                "Invalid Mermaid syntax. Please fix the diagram and try again.\n"
                f"{detail}"
            )
        raise RuntimeError(
            f"Failed to render Mermaid SVG from {mmd_path.name}. {detail or 'No renderer output.'}"
        )
