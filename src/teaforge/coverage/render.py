"""Render coverage documents into standalone HTML reports."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from teaforge.artifacts import json_for_html_script

from .models import CoverageDocument


def default_template_path() -> Path:
    """Return the built-in coverage report template path."""
    return Path(
        str(resources.files("teaforge.templates").joinpath("coverage_report.html"))
    )


def render_coverage_html(
    document: CoverageDocument,
    template_path: Path | None = None,
) -> str:
    """Render one coverage document and embed the JSON payload for downstream tooling."""
    if template_path is None:
        env = Environment(autoescape=select_autoescape(["html", "xml"]))
        template = env.from_string(
            resources.files("teaforge.templates")
            .joinpath("coverage_report.html")
            .read_text(encoding="utf-8")
        )
    else:
        if not template_path.is_file():
            raise FileNotFoundError(
                f"Coverage template does not exist: {template_path}"
            )
        env = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        template = env.get_template(template_path.name)
    payload = document.to_dict()
    embedded_json = json_for_html_script(payload)
    return template.render(
        document=payload,
        embedded_json=embedded_json,
    )
