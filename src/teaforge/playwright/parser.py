"""Parse Playwright page tests into PCL documents."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from teaforge.jest.parser import (
    JestTestBlock,
    _collect_test_files,
    _extract_test_blocks,
    _find_matching,
    _parse_literal_expression,
    _stringify_value,
)
from teaforge.pcl.assembly import build_input_rows, build_output_rows, merge_documents_by_subject
from teaforge.pcl.classification import classify_type
from teaforge.pcl.models import PCLDocument, PCLTestCase
from teaforge.pcl.parser import _display_path


def parse_playwright_documents(test_path: Path) -> list[PCLDocument]:
    """Build one logical PCL document per Playwright page target."""
    files = _collect_test_files(test_path)
    if not files:
        raise ValueError(f"No Playwright test files found under: {test_path}")

    raw_documents: list[PCLDocument] = []
    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        for index, block in enumerate(
            _extract_test_blocks(
                content,
                suffix=file_path.suffix,
                source_name=str(file_path),
            ),
            start=1,
        ):
            raw_documents.append(_build_document_for_block(file_path, block, index))

    if not raw_documents:
        raise ValueError(f"No supported Playwright tests found under: {test_path}")

    return merge_documents_by_subject(raw_documents)


def _build_document_for_block(file_path: Path, block: JestTestBlock, index: int) -> PCLDocument:
    entry_url = _extract_entry_url(block.body)
    screen_name = _screen_name_for_entry(entry_url, file_path)
    input_actions = _extract_input_actions(block.body, entry_url)
    ui_outputs, navigation_outputs = _extract_outputs(block.body)
    output_checks = [*ui_outputs, *navigation_outputs]
    output = "; ".join(output_checks) if output_checks else "No explicit Playwright assertion found"

    document = PCLDocument.create(
        file=file_path.name,
        method=screen_name,
        source_path=_display_path(file_path),
        test_file=file_path.name,
        test_method=block.identifier,
        test_source_path=_display_path(file_path),
    )
    document.testcases.append(
        PCLTestCase(
            testcase=block.title,
            testname=block.identifier,
            testcasecode=f"TC-{index:03d}",
            inputs={},
            output=output,
            type=classify_type(block.title, block.identifier, output),
            screen_name=screen_name,
            entry_url=entry_url,
            input_actions=input_actions,
            ui_outputs=ui_outputs,
            navigation_outputs=navigation_outputs,
            verification_mode="playwright",
            output_checks=output_checks,
            test_full_name=block.full_name or block.title,
        )
    )
    document.input_rows = build_input_rows(document.testcases)
    document.output_rows = build_output_rows(document.testcases)
    return document


def _extract_entry_url(body: str) -> str:
    match = re.search(r"\bpage\.goto\s*\(\s*['\"`](?P<url>[^'\"`]+)['\"`]", body)
    if match is not None:
        return match.group("url")
    return ""


def _screen_name_for_entry(entry_url: str, file_path: Path) -> str:
    if not entry_url:
        return file_path.stem.replace(".spec", "").replace(".test", "")
    segments = [segment for segment in urlsplit(entry_url).path.split("/") if segment]
    if not segments:
        return "RootPage"
    return "".join(part.title() for part in segments) + "Page"


def _extract_input_actions(body: str, entry_url: str) -> list[str]:
    actions: list[str] = []
    if entry_url:
        actions.append(f"open:{entry_url}")
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.search(r"page\.click\((?P<target>.+?)\)", line)
        if match is not None:
            actions.append(f"click:{_stringify_value(_parse_literal_expression(match.group('target').strip()))}")
            continue
        match = re.search(r"page\.fill\((?P<target>.+?),\s*(?P<value>.+?)\)", line)
        if match is not None:
            target = _stringify_value(_parse_literal_expression(match.group("target").strip()))
            value = _stringify_value(_parse_literal_expression(match.group("value").strip()))
            actions.append(f"type:{target}={value}")
            continue
        match = re.search(r"page\.focus\((?P<target>.+?)\)", line)
        if match is not None:
            actions.append(f"focus:{_stringify_value(_parse_literal_expression(match.group('target').strip()))}")
            continue
        match = re.search(r"page\.locator\((?P<target>.+?)\)\.click\(\)", line)
        if match is not None:
            actions.append(f"click:{_stringify_value(_parse_literal_expression(match.group('target').strip()))}")
    return actions


def _extract_outputs(body: str) -> tuple[list[str], list[str]]:
    ui_outputs: list[str] = []
    navigation_outputs: list[str] = []
    pattern = re.compile(r"\bexpect\s*\(")
    cursor = 0
    while True:
        match = pattern.search(body, cursor)
        if match is None:
            break
        open_paren = body.find("(", match.start())
        close_paren = _find_matching(body, open_paren, "(", ")")
        if close_paren == -1:
            break
        actual = body[open_paren + 1 : close_paren].strip()
        tail = body[close_paren + 1 :]
        matcher_match = re.match(
            r"\s*\.(?P<matcher>toHaveURL|toContainText)\s*\(",
            tail,
        )
        if matcher_match is None:
            cursor = close_paren + 1
            continue
        matcher = matcher_match.group("matcher")
        matcher_open = close_paren + 1 + matcher_match.end() - 1
        matcher_close = _find_matching(body, matcher_open, "(", ")")
        if matcher_close == -1:
            break
        expected = body[matcher_open + 1 : matcher_close].strip()
        rendered = _stringify_value(_parse_literal_expression(expected))
        if matcher == "toHaveURL":
            navigation_outputs.extend(_expand_url_outputs(rendered))
        elif matcher == "toContainText":
            ui_outputs.append(f"dom:{actual} contains {rendered}")
        cursor = matcher_close + 1
    return ui_outputs, navigation_outputs


def _expand_url_outputs(url: str) -> list[str]:
    outputs = [f"url == {url}"]
    parsed = urlsplit(url)
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        outputs.append(f"url.query.{key} == {value}")
    return outputs
