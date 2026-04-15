"""Render PCL documents into HTML using the bundled Jinja template."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import PCLDocument

CASE_SLOTS_PER_SHEET = 25


def default_template_path() -> Path:
    """Return the built-in PCL template path."""
    return Path(__file__).resolve().parents[3] / "templates" / "pcl.html"


def render_pcl_html(document: PCLDocument, template_path: Path | None = None) -> str:
    """Render one PCL document and embed its JSON payload for later lookup."""
    template_file = template_path or default_template_path()
    env = Environment(
        loader=FileSystemLoader(str(template_file.parent)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template(template_file.name)
    payload = document.to_dict()
    embedded_json = json.dumps(payload, ensure_ascii=False, indent=2)
    case_columns = [
        {
            "index": index,
            "testcasecode": case["testcasecode"],
            "type": case["type"],
            "testcase": case["testcase"],
            "testname": case["testname"],
            "screen_name": case.get("screen_name", ""),
            "entry_url": case.get("entry_url", ""),
            "preconditions": case.get("preconditions", []),
            "input_actions": case.get("input_actions", []),
            "ui_outputs": case.get("ui_outputs", []),
            "navigation_outputs": case.get("navigation_outputs", []),
            "verification_mode": case.get("verification_mode", ""),
            "executed_date": case.get("executed_date", ""),
            "bug_number": case.get("bug_number", ""),
        }
        for index, case in enumerate(payload["testcases"], start=1)
    ]
    decision_columns = [
        case_columns[index] if index < len(case_columns) else None
        for index in range(CASE_SLOTS_PER_SHEET)
    ]
    input_rows = _prepare_grouped_rows(payload["input_rows"])
    output_rows = _prepare_grouped_rows(payload["output_rows"])
    frontend_cases = [
        case
        for case in case_columns
        if case["screen_name"]
        or case["entry_url"]
        or case["preconditions"]
        or case["input_actions"]
        or case["ui_outputs"]
        or case["navigation_outputs"]
        or case["verification_mode"]
    ]
    return template.render(
        document=payload,
        embedded_json=embedded_json,
        case_columns=case_columns,
        decision_columns=decision_columns,
        input_rows=input_rows,
        output_rows=output_rows,
        frontend_cases=frontend_cases,
    )


def _prepare_grouped_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add rowspan metadata so repeated items render as grouped table cells."""
    prepared: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(rows):
        item = rows[cursor]["item"]
        end = cursor + 1
        while end < len(rows) and rows[end]["item"] == item:
            end += 1

        rowspan = end - cursor
        for index in range(cursor, end):
            row = dict(rows[index])
            row["show_item"] = index == cursor
            row["item_rowspan"] = rowspan if index == cursor else 0
            prepared.append(row)
        cursor = end
    return prepared
