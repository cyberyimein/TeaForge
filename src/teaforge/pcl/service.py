from __future__ import annotations

import json
import re
from dataclasses import replace
from math import ceil
from pathlib import Path

from .models import PCLDocument, PCLMatrixRow
from .parser import parse_pytest_documents
from .render import render_pcl_html

MAX_CASES_PER_SHEET = 25


def generate_pcl(
    pytest_path: Path,
    html_output: Path,
    json_output: Path | None = None,
    template_path: Path | None = None,
) -> list[tuple[Path, Path]]:
    if not pytest_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {pytest_path}")

    documents = parse_pytest_documents(pytest_path)
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
    keyword = testcase.strip()
    for case in document.testcases:
        if case.testcasecode == keyword or case.testname == keyword:
            return _format_case_description(case)
    for case in document.testcases:
        if keyword in case.testname or keyword in case.testcase:
            return _format_case_description(case)
    raise ValueError(f"Test case not found: {testcase}")


def _split_documents(documents: list[PCLDocument], chunk_size: int) -> list[PCLDocument]:
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
    if not multiple_outputs:
        html_path = base_html
        json_path = base_json or base_html.with_suffix(".json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        return html_path, json_path

    output_dir = base_html.parent / _folder_name(Path(document.file).stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _build_output_suffix(document)
    html_path = output_dir / f"{base_html.stem}-{suffix}{base_html.suffix}"
    if base_json is not None:
        json_dir = base_json.parent / _folder_name(Path(document.file).stem)
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path = json_dir / f"{base_json.stem}-{suffix}{base_json.suffix}"
    else:
        json_path = html_path.with_suffix(".json")
    return html_path, json_path


def _build_output_suffix(document: PCLDocument) -> str:
    method_slug = _slugify(document.method)
    if document.sheet_count > 1:
        return f"{method_slug}-sheet-{document.sheet_number:02d}"
    return method_slug


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "pcl"


def _folder_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return name or "pcl"


def _extract_embedded_json(html_content: str) -> dict:
    pattern = r"<script[^>]*id=[\"']teaforge-pcl-data[\"'][^>]*>(.*?)</script>"
    match = re.search(pattern, html_content, flags=re.DOTALL)
    if not match:
        raise ValueError("No embedded PCL JSON found in HTML.")
    raw_json = match.group(1).strip()
    return json.loads(raw_json)


def _format_case_description(case) -> str:
    input_text = ", ".join(f"{key}={value}" for key, value in case.inputs.items())
    return (
        f"テストケース番号: {case.testcasecode}\n"
        f"テスト目的: {case.testcase}\n"
        f"テスト名: {case.testname}\n"
        f"区分: {case.type} (N=正常値, I=境界値, E=異常値)\n"
        f"入力: {input_text}\n"
        f"期待結果: {case.output}"
    )
