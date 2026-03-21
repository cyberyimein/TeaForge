"""Bridge generated HTML reports to WeasyPrint without leaking its import details."""

from __future__ import annotations

from pathlib import Path


def export_pdf_from_html(html_path: Path, output_pdf: Path) -> None:
    """Export one HTML report to PDF and surface dependency errors as runtime guidance."""
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint is required for PDF export. Install with: pip install -e '.[pdf]'"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "WeasyPrint system libraries are missing. "
            "Please install GTK/Pango/Cairo runtime dependencies for your OS."
        ) from exc

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        HTML(filename=str(html_path)).write_pdf(str(output_pdf))
    except OSError as exc:
        raise RuntimeError(
            "WeasyPrint system libraries are missing. "
            "Please install GTK/Pango/Cairo runtime dependencies for your OS."
        ) from exc
