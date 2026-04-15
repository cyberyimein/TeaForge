"""Coordinate PCL generation, persistence, and testcase lookup."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from math import ceil
from pathlib import Path

from teaforge.naming import folder_name, slugify

from .backends import parse_documents_for_framework
from .models import PCLDocument, PCLMatrixRow
from .render import render_pcl_html

MAX_CASES_PER_SHEET = 25


def generate_pcl(
    test_path: Path,
    html_output: Path,
    json_output: Path | None = None,
    template_path: Path | None = None,
    framework: str = "pytest",
) -> list[tuple[Path, Path]]:
    """Generate HTML and JSON outputs for each logical PCL document."""
    if not test_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {test_path}")

    documents = parse_documents_for_framework(test_path, framework)
    sheet_documents = _split_documents(documents, MAX_CASES_PER_SHEET)
    html_output.parent.mkdir(parents=True, exist_ok=True)

    outputs: list[tuple[Path, Path]] = []
    multiple_outputs = len(sheet_documents) > 1
    for document in sheet_documents:
        html_path, json_path = _resolve_output_paths(
            document=document,
            base_html=html_output,
            base_json=json_output,
            multiple_outputs=multiple_outputs,
        )
        html_content = render_pcl_html(document, template_path=template_path)
        html_path.write_text(html_content, encoding="utf-8")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(document.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        outputs.append((html_path, json_path))
    return outputs


def load_pcl_document(path: Path) -> PCLDocument:
    """Load PCL data from JSON first, then from embedded HTML when needed."""
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PCLDocument.from_dict(payload)

    if path.suffix.lower() == ".html":
        sibling_json = path.with_suffix(".json")
        if sibling_json.exists():
            payload = json.loads(sibling_json.read_text(encoding="utf-8"))
            return PCLDocument.from_dict(payload)

        payload = _extract_embedded_json(path.read_text(encoding="utf-8"))
        return PCLDocument.from_dict(payload)

    raise ValueError("Unsupported file type. Use .json or .html")


def get_testcase_description(document: PCLDocument, testcase: str) -> str:
    """Return a human-readable testcase description by exact or fuzzy match."""
    keyword = testcase.strip()
    for case in document.testcases:
        if case.testcasecode == keyword or case.testname == keyword:
            return _format_case_description(case)
    for case in document.testcases:
        if keyword in case.testname or keyword in case.testcase:
            return _format_case_description(case)
    raise ValueError(f"Test case not found: {testcase}")


def _split_documents(documents: list[PCLDocument], chunk_size: int) -> list[PCLDocument]:
    """Split oversized PCL documents into fixed-width sheets."""
    split_documents: list[PCLDocument] = []
    for document in documents:
        total_sheets = max(1, ceil(len(document.testcases) / chunk_size))
        for sheet_number in range(1, total_sheets + 1):
            start = (sheet_number - 1) * chunk_size
            end = start + chunk_size
            cases = document.testcases[start:end]
            testcase_codes = {case.testcasecode for case in cases}
            split_documents.append(
                PCLDocument(
                    title=document.title,
                    file=document.file,
                    method=document.method,
                    source_path=document.source_path,
                    test_file=document.test_file,
                    test_method=document.test_method,
                    test_source_path=document.test_source_path,
                    generated_at=document.generated_at,
                    sheet_number=sheet_number,
                    sheet_count=total_sheets,
                    testcases=[replace(case) for case in cases],
                    input_rows=_filter_rows(document.input_rows, testcase_codes),
                    output_rows=_filter_rows(document.output_rows, testcase_codes),
                )
            )
    return split_documents


def _filter_rows(rows: list[PCLMatrixRow], testcase_codes: set[str]) -> list[PCLMatrixRow]:
    """Keep only matrix cells that belong to the selected testcase codes."""
    filtered: list[PCLMatrixRow] = []
    for row in rows:
        values = {code: mark for code, mark in row.values.items() if code in testcase_codes and mark}
        if not values:
            continue
        filtered.append(
            PCLMatrixRow(
                category=row.category,
                item=row.item,
                value=row.value,
                values=values,
            )
        )
    return filtered


def _resolve_output_paths(
    document: PCLDocument,
    base_html: Path,
    base_json: Path | None,
    multiple_outputs: bool,
) -> tuple[Path, Path]:
    """Resolve the HTML and JSON output paths for one generated PCL document."""
    # Multi-document runs are grouped by production file so one tested module owns one folder.
    if not multiple_outputs:
        html_path = base_html
        json_path = base_json or base_html.with_suffix(".json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        return html_path, json_path

    output_dir = base_html.parent / folder_name(Path(document.file).stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _build_output_suffix(document)
    html_path = output_dir / f"{base_html.stem}-{suffix}{base_html.suffix}"
    if base_json is not None:
        json_dir = base_json.parent / folder_name(Path(document.file).stem)
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path = json_dir / f"{base_json.stem}-{suffix}{base_json.suffix}"
    else:
        json_path = html_path.with_suffix(".json")
    return html_path, json_path


def _build_output_suffix(document: PCLDocument) -> str:
    """Build a stable file suffix from the method name and optional sheet index."""
    method_slug = slugify(document.method)
    if document.sheet_count > 1:
        return f"{method_slug}-sheet-{document.sheet_number:02d}"
    return method_slug


def _extract_embedded_json(html_content: str) -> dict:
    """Read the JSON payload embedded in a generated PCL HTML report."""
    pattern = r"<script[^>]*id=[\"']teaforge-pcl-data[\"'][^>]*>(.*?)</script>"
    match = re.search(pattern, html_content, flags=re.DOTALL)
    if not match:
        raise ValueError("No embedded PCL JSON found in HTML.")
    raw_json = match.group(1).strip()
    return json.loads(raw_json)


def _format_case_description(case) -> str:
    """Format one testcase into the CLI response used by AI tooling."""
    input_text = ", ".join(f"{key}={value}" for key, value in case.inputs.items())
    lines = [
        f"テストケース番号: {case.testcasecode}\n"
        f"テスト目的: {case.testcase}\n"
        f"テスト名: {case.testname}\n"
        f"区分: {case.type} (N=正常値, I=境界値, E=異常値)"
    ]
    if getattr(case, "screen_name", ""):
        lines.append(f"画面: {case.screen_name}")
    if getattr(case, "entry_url", ""):
        lines.append(f"入口URL: {case.entry_url}")
    if getattr(case, "preconditions", None):
        lines.append(f"前提条件: {'; '.join(case.preconditions)}")
    lines.append(f"入力: {input_text}")
    if getattr(case, "input_actions", None):
        lines.append(f"操作: {'; '.join(case.input_actions)}")
    if getattr(case, "ui_outputs", None):
        lines.append(f"画面確認: {'; '.join(case.ui_outputs)}")
    if getattr(case, "navigation_outputs", None):
        lines.append(f"遷移確認: {'; '.join(case.navigation_outputs)}")
    if getattr(case, "verification_mode", ""):
        lines.append(f"確認方法: {case.verification_mode}")
    lines.append(f"期待結果: {case.output}")
    return "\n".join(lines)
