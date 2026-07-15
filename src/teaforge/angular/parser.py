"""Parse Angular/Jest page-level UT tests into PCL documents."""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from teaforge.jest.parser import (
    JestTestBlock,
    JSImport,
    SubjectLocation,
    _collect_test_files,
    _extract_imports,
    _extract_test_blocks,
    _find_matching,
    _parse_literal_expression,
    _split_top_level,
    _stringify_value,
)
from teaforge.pcl.assembly import build_input_rows, build_output_rows, merge_documents_by_subject
from teaforge.pcl.classification import classify_type
from teaforge.pcl.models import PCLDocument, PCLTestCase
from teaforge.pcl.parser import _display_path


def parse_angular_documents(test_path: Path) -> list[PCLDocument]:
    """Build one logical PCL document per Angular page subject."""
    files = _collect_test_files(test_path)
    if not files:
        raise ValueError(f"No Angular test files found under: {test_path}")

    raw_documents: list[PCLDocument] = []
    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        imports = _extract_imports(file_path, content)
        for index, block in enumerate(
            _extract_test_blocks(
                content,
                suffix=file_path.suffix,
                source_name=str(file_path),
            ),
            start=1,
        ):
            raw_documents.append(_build_document_for_block(file_path, block, imports, index))

    if not raw_documents:
        raise ValueError(f"No supported Angular tests found under: {test_path}")

    return merge_documents_by_subject(raw_documents)


def _build_document_for_block(
    file_path: Path,
    block: JestTestBlock,
    imports: dict[str, JSImport],
    index: int,
) -> PCLDocument:
    subject = _infer_subject_location(file_path, block, imports)
    screen_name = _screen_name_for_subject(subject.method)
    entry_url = _extract_entry_url(block.body)
    inputs = _extract_inputs(block.body)
    preconditions = _extract_preconditions(block.body)
    input_actions = _extract_input_actions(block.body, entry_url)
    ui_outputs, navigation_outputs = _extract_outputs(block.body)
    output_checks = [*ui_outputs, *navigation_outputs]
    output = "; ".join(output_checks) if output_checks else "No explicit frontend assertion found"

    document = PCLDocument.create(
        file=subject.file,
        method=subject.method,
        source_path=subject.source_path,
        test_file=file_path.name,
        test_method=block.identifier,
        test_source_path=_display_path(file_path),
    )
    document.testcases.append(
        PCLTestCase(
            testcase=block.title,
            testname=block.identifier,
            testcasecode=f"TC-{index:03d}",
            inputs=inputs,
            output=output,
            type=classify_type(block.title, block.identifier, output),
            screen_name=screen_name,
            entry_url=entry_url,
            preconditions=preconditions,
            input_actions=input_actions,
            ui_outputs=ui_outputs,
            navigation_outputs=navigation_outputs,
            verification_mode="unit",
            output_checks=output_checks,
            test_full_name=block.full_name or block.title,
        )
    )
    document.input_rows = build_input_rows(document.testcases)
    document.output_rows = build_output_rows(document.testcases)
    return document


def _infer_subject_location(
    file_path: Path,
    block: JestTestBlock,
    imports: dict[str, JSImport],
) -> SubjectLocation:
    component_name = _extract_component_name(block.body)
    if component_name and component_name in imports:
        imported = imports[component_name]
        if imported.file_path is not None:
            return SubjectLocation(
                file=imported.file_path.name,
                method=imported.original_name,
                source_path=_display_path(imported.file_path),
            )

    return SubjectLocation(
        file=file_path.name,
        method=block.identifier,
        source_path=_display_path(file_path),
    )


def _extract_component_name(body: str) -> str | None:
    patterns = (
        r"\brender\s*\(\s*(?P<name>[A-Za-z_$][\w$]*)",
        r"\bcreateComponent\s*\(\s*(?P<name>[A-Za-z_$][\w$]*)",
    )
    for pattern in patterns:
        match = re.search(pattern, body)
        if match is not None:
            return match.group("name")
    return None


def _screen_name_for_subject(subject_method: str) -> str:
    if subject_method.endswith("Component"):
        return subject_method.removesuffix("Component")
    return subject_method


def _extract_entry_url(body: str) -> str:
    match = re.search(r"\bnavigateByUrl\s*\(\s*['\"`](?P<url>[^'\"`]+)['\"`]", body)
    if match is not None:
        return match.group("url")
    return ""


def _extract_inputs(body: str) -> dict[str, str]:
    rendered: OrderedDict[str, str] = OrderedDict()
    pattern = re.compile(r"(?P<target>[A-Za-z_$][\w$.]*)\.(?P<method>setValue|patchValue)\s*\(")
    cursor = 0
    while True:
        match = pattern.search(body, cursor)
        if match is None:
            break
        open_paren = body.find("(", match.start())
        close_paren = _find_matching(body, open_paren, "(", ")")
        if close_paren == -1:
            break
        payload = _parse_literal_expression(body[open_paren + 1 : close_paren].strip())
        if isinstance(payload, dict):
            for key, value in payload.items():
                rendered[f"form.{key}"] = _stringify_value(value)
        cursor = close_paren + 1

    for assignment in re.finditer(r"\bcomponent\.(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<expr>.+?);", body, re.DOTALL):
        rendered[f"input.{assignment.group('name')}"] = _stringify_value(
            _parse_literal_expression(assignment.group("expr").strip())
        )

    return dict(rendered)


def _extract_preconditions(body: str) -> list[str]:
    preconditions: list[str] = []
    pattern = re.compile(
        r"(?:jest\.)?spyOn\((?P<service>[^,]+),\s*['\"](?P<method>[A-Za-z_$][\w$]*)['\"]\)"
        r"\.(?P<mock>mockReturnValue|mockResolvedValue)\((?P<value>.+?)\);",
        re.DOTALL,
    )
    for match in pattern.finditer(body):
        service_name = match.group("service").strip().split(".")[-1]
        value = _stringify_value(_parse_literal_expression(match.group("value").strip()))
        preconditions.append(f"provider.{service_name}.{match.group('method')} returns {value}")
    return preconditions


def _extract_input_actions(body: str, entry_url: str) -> list[str]:
    actions: list[str] = []
    if entry_url:
        actions.append(f"open:{entry_url}")

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.search(r"userEvent\.click\((?P<target>.+?)\)", line)
        if match is not None:
            actions.append(f"click:{match.group('target').strip()}")
            continue
        match = re.search(r"fireEvent\.click\((?P<target>.+?)\)", line)
        if match is not None:
            actions.append(f"click:{match.group('target').strip()}")
            continue
        match = re.search(r"fireEvent\.focus\((?P<target>.+?)\)", line)
        if match is not None:
            actions.append(f"focus:{match.group('target').strip()}")
            continue
        match = re.search(r"fireEvent\.blur\((?P<target>.+?)\)", line)
        if match is not None:
            actions.append(f"blur:{match.group('target').strip()}")
            continue
        match = re.search(r"userEvent\.type\((?P<target>.+?),\s*(?P<value>.+?)\)", line)
        if match is not None:
            rendered = _stringify_value(_parse_literal_expression(match.group("value").strip()))
            actions.append(f"type:{match.group('target').strip()}={rendered}")
            continue
        match = re.search(r"(?P<target>[A-Za-z_$][\w$.]*)\.dispatchEvent\(new\s+FocusEvent\(['\"]focus['\"]\)\)", line)
        if match is not None:
            actions.append(f"focus:{match.group('target')}")
            continue
        match = re.search(r"(?P<target>[A-Za-z_$][\w$.]*)\.dispatchEvent\(new\s+Event\(['\"]blur['\"]\)\)", line)
        if match is not None:
            actions.append(f"blur:{match.group('target')}")
            continue
        match = re.search(r"(?P<target>[A-Za-z_$][\w$.]*)\.dispatchEvent\(new\s+Event\(['\"]submit['\"]\)\)", line)
        if match is not None:
            actions.append(f"submit:{match.group('target')}")
            continue
        match = re.search(r"(?P<target>[A-Za-z_$][\w$.]*)\.click\(\)", line)
        if match is not None:
            actions.append(f"click:{match.group('target')}")
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
            r"\s*\.(?P<matcher>toBe|toEqual|toStrictEqual|toContain|toBeTruthy|toBeFalsy|toHaveTextContent|toBeDisabled|toHaveFocus|toHaveBeenCalled|toHaveBeenCalledWith)\s*\(",
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
        ui_additions, nav_additions = _format_expectation(actual, matcher, expected)
        ui_outputs.extend(ui_additions)
        navigation_outputs.extend(nav_additions)
        cursor = matcher_close + 1
    return ui_outputs, navigation_outputs


def _format_expectation(actual: str, matcher: str, expected: str) -> tuple[list[str], list[str]]:
    ui_outputs: list[str] = []
    navigation_outputs: list[str] = []
    rendered_expected = _stringify_value(_parse_literal_expression(expected)) if expected else ""

    if matcher == "toHaveBeenCalledWith":
        args = [segment.strip() for segment in _split_top_level(expected, ",") if segment.strip()]
        if actual.endswith(".emit"):
            emit_name = actual.rsplit(".", 1)[0].split(".")[-1]
            rendered = ", ".join(_stringify_value(_parse_literal_expression(arg)) for arg in args)
            ui_outputs.append(f"output.{emit_name} emitted with {rendered}")
            return ui_outputs, navigation_outputs
        if actual.endswith("navigate"):
            navigation_outputs.extend(_format_router_navigation(args))
            return ui_outputs, navigation_outputs
        rendered = ", ".join(_stringify_value(_parse_literal_expression(arg)) for arg in args)
        ui_outputs.append(f"{actual} called with {rendered}")
        return ui_outputs, navigation_outputs

    if matcher == "toHaveBeenCalled":
        ui_outputs.append(f"{actual} called")
        return ui_outputs, navigation_outputs

    if matcher in {"toContain", "toHaveTextContent"}:
        ui_outputs.append(f"dom:{actual} contains {rendered_expected}")
        return ui_outputs, navigation_outputs

    if matcher == "toBeDisabled":
        ui_outputs.append(f"dom:{actual} disabled == true")
        return ui_outputs, navigation_outputs

    if matcher == "toHaveFocus":
        ui_outputs.append(f"dom:{actual} focused == true")
        return ui_outputs, navigation_outputs

    if matcher == "toBeTruthy":
        ui_outputs.append(f"{actual} == true")
        return ui_outputs, navigation_outputs

    if matcher == "toBeFalsy":
        ui_outputs.append(f"{actual} == false")
        return ui_outputs, navigation_outputs

    if actual == "location.path()":
        navigation_outputs.extend(_expand_url_outputs(rendered_expected))
        return ui_outputs, navigation_outputs

    ui_outputs.append(f"{actual} == {rendered_expected}")
    return ui_outputs, navigation_outputs


def _format_router_navigation(args: list[str]) -> list[str]:
    outputs: list[str] = []
    if not args:
        return outputs

    path_value = _parse_literal_expression(args[0])
    if isinstance(path_value, list):
        segments = [str(item).strip("/") for item in path_value]
        path = "/" + "/".join(segment for segment in segments if segment)
    else:
        path = str(path_value)
    query_outputs = _extract_query_outputs(args[1] if len(args) > 1 else "")
    if query_outputs:
        outputs.append(f"navigate:{path} {' '.join(query_outputs)}")
    else:
        outputs.append(f"navigate:{path}")
    return outputs


def _extract_query_outputs(raw_options: str) -> list[str]:
    match = re.search(r"queryParams\s*:\s*\{(?P<body>.*?)\}", raw_options)
    if match is None:
        return []
    outputs: list[str] = []
    for segment in _split_top_level(match.group("body"), ","):
        if ":" not in segment:
            continue
        key, value = segment.split(":", 1)
        rendered = _stringify_value(_parse_literal_expression(value.strip()))
        outputs.append(f"query.{key.strip()}={rendered}")
    return outputs


def _expand_url_outputs(url: str) -> list[str]:
    outputs = [f"url == {url}"]
    parsed = urlsplit(url)
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        outputs.append(f"url.query.{key} == {value}")
    return outputs
