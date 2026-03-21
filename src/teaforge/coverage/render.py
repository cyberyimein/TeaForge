from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import CoverageDocument


def default_template_path() -> Path:
    return Path(__file__).resolve().parents[3] / "templates" / "coverage_report.html"


def render_coverage_html(
    document: CoverageDocument,
    template_path: Path | None = None,
) -> str:
    template_file = template_path or default_template_path()
    env = Environment(
        loader=FileSystemLoader(str(template_file.parent)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template(template_file.name)
    payload = document.to_dict()
    embedded_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return template.render(
        document=payload,
        embedded_json=embedded_json,
    )
